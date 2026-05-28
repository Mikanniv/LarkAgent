import argparse
import csv
import json
import random
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

import torch
from torch import nn


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_LABEL_FILE = PROJECT_ROOT / "data" / "label.csv"
DEFAULT_OUTPUT_FILE = PROJECT_ROOT / "models" / "valence_fusion_weights.json"


@dataclass
class LabelRow:
    video_id: str
    clip_id: str
    text: str
    label: float
    label_t: float
    label_a: float
    label_v: float
    annotation: str
    split: str


def project_path(value: str | Path) -> Path:
    path = Path(value)
    return path if path.is_absolute() else PROJECT_ROOT / path


def parse_label_csv(path: Path) -> list[LabelRow]:
    rows: list[LabelRow] = []
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.reader(handle)
        for line_no, row in enumerate(reader, start=1):
            if not row or row[0].strip().lower() in {"video_id", "video"}:
                continue
            if len(row) < 9:
                raise ValueError(f"{path}:{line_no} expected 9 columns, got {len(row)}")
            rows.append(
                LabelRow(
                    video_id=row[0].strip(),
                    clip_id=row[1].strip(),
                    text=row[2].strip(),
                    label=float(row[3]),
                    label_t=float(row[4]),
                    label_a=float(row[5]),
                    label_v=float(row[6]),
                    annotation=row[7].strip(),
                    split=row[8].strip().lower(),
                )
            )
    if not rows:
        raise ValueError(f"No rows found in {path}")
    return rows


def rows_to_tensors(rows: Iterable[LabelRow]) -> tuple[torch.Tensor, torch.Tensor]:
    items = list(rows)
    features = [[item.label_t, item.label_a, item.label_v] for item in items]
    labels = [item.label for item in items]
    return torch.tensor(features, dtype=torch.float32), torch.tensor(labels, dtype=torch.float32)


class SoftmaxFusionRegressor(nn.Module):
    def __init__(self) -> None:
        super().__init__()
        self.logits = nn.Parameter(torch.zeros(3, dtype=torch.float32))

    @property
    def weights(self) -> torch.Tensor:
        return torch.softmax(self.logits, dim=0)

    def forward(self, features: torch.Tensor) -> torch.Tensor:
        return features @ self.weights


def evaluate(model: SoftmaxFusionRegressor, rows: list[LabelRow]) -> dict[str, float | int]:
    if not rows:
        return {"count": 0}
    features, labels = rows_to_tensors(rows)
    with torch.inference_mode():
        pred = model(features)
        mse = torch.mean((pred - labels) ** 2).item()
        mae = torch.mean(torch.abs(pred - labels)).item()
    return {
        "count": len(rows),
        "mse": round(mse, 6),
        "mae": round(mae, 6),
    }


def split_rows(rows: list[LabelRow]) -> dict[str, list[LabelRow]]:
    splits = {"train": [], "valid": [], "test": []}
    for row in rows:
        if row.split in {"train", "valid", "test"}:
            splits[row.split].append(row)
        elif row.split == "val":
            splits["valid"].append(row)
    if not splits["train"]:
        raise ValueError("No train rows found. Expected split column to contain train/valid/test.")
    return splits


def train(args: argparse.Namespace) -> dict:
    random.seed(args.seed)
    torch.manual_seed(args.seed)

    label_file = project_path(args.label_file)
    output_file = project_path(args.output_file)
    rows = parse_label_csv(label_file)
    splits = split_rows(rows)
    train_features, train_labels = rows_to_tensors(splits["train"])

    model = SoftmaxFusionRegressor()
    optimizer = torch.optim.AdamW(model.parameters(), lr=args.lr, weight_decay=args.weight_decay)
    loss_fn = nn.MSELoss()

    best_loss = float("inf")
    best_logits = model.logits.detach().clone()
    stale_epochs = 0

    for epoch in range(1, args.epochs + 1):
        model.train()
        optimizer.zero_grad()
        pred = model(train_features)
        loss = loss_fn(pred, train_labels)
        loss.backward()
        optimizer.step()

        current_loss = float(loss.item())
        if current_loss < best_loss - args.min_delta:
            best_loss = current_loss
            best_logits = model.logits.detach().clone()
            stale_epochs = 0
        else:
            stale_epochs += 1

        if args.log_every > 0 and (epoch == 1 or epoch % args.log_every == 0):
            weights = model.weights.detach().tolist()
            print(
                f"epoch={epoch} train_mse={current_loss:.6f} "
                f"weights=text:{weights[0]:.4f},audio:{weights[1]:.4f},video:{weights[2]:.4f}"
            )

        if args.patience > 0 and stale_epochs >= args.patience:
            break

    model.logits.data.copy_(best_logits)
    weights = model.weights.detach().tolist()

    result = {
        "formula": "fusion = w_text * label_T + w_audio * label_A + w_video * label_V",
        "label_file": str(label_file),
        "target": "label",
        "features": ["label_T", "label_A", "label_V"],
        "constraint": "softmax weights; each weight >= 0 and sum(weights) = 1",
        "loss": "mse",
        "weights": {
            "text": round(float(weights[0]), 6),
            "audio": round(float(weights[1]), 6),
            "video": round(float(weights[2]), 6),
        },
        "raw_logits": {
            "text": round(float(model.logits[0].item()), 6),
            "audio": round(float(model.logits[1].item()), 6),
            "video": round(float(model.logits[2].item()), 6),
        },
        "metrics": {
            "train": evaluate(model, splits["train"]),
            "valid": evaluate(model, splits["valid"]),
            "test": evaluate(model, splits["test"]),
        },
        "training": {
            "epochs_requested": args.epochs,
            "epochs_run": epoch,
            "lr": args.lr,
            "weight_decay": args.weight_decay,
            "patience": args.patience,
            "seed": args.seed,
        },
    }

    output_file.parent.mkdir(parents=True, exist_ok=True)
    with output_file.open("w", encoding="utf-8") as handle:
        json.dump(result, handle, ensure_ascii=False, indent=2)
        handle.write("\n")
    return result


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Train three-input CH-SIMS valence fusion weights with MSE."
    )
    parser.add_argument("--label-file", default=str(DEFAULT_LABEL_FILE))
    parser.add_argument("--output-file", default=str(DEFAULT_OUTPUT_FILE))
    parser.add_argument("--epochs", type=int, default=2000)
    parser.add_argument("--lr", type=float, default=0.03)
    parser.add_argument("--weight-decay", type=float, default=0.0)
    parser.add_argument("--patience", type=int, default=300)
    parser.add_argument("--min-delta", type=float, default=1e-8)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--log-every", type=int, default=200)
    return parser


def main() -> None:
    args = build_parser().parse_args()
    result = train(args)
    print(json.dumps({"weights": result["weights"], "metrics": result["metrics"]}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
