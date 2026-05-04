import argparse
import csv
import math
import os
import pickle
import random
import shutil
import subprocess
import sys
import tempfile
import ctypes.util
from dataclasses import dataclass
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DATA_DIR = ROOT / "data"
DEFAULT_LABEL_FILE = DEFAULT_DATA_DIR / "label.csv"
DEFAULT_FEATURE_FILE = DEFAULT_DATA_DIR / "self_mm_mediapipe_features.pkl"
LEGACY_FEATURE_FILE = ROOT / "models" / "self_mm_mediapipe_features.pkl"
DEFAULT_MODEL_FILE = ROOT / "models" / "self_mm_mediapipe_best.pth"
DEFAULT_LAST_MODEL_FILE = ROOT / "models" / "self_mm_mediapipe_last.pth"
DEFAULT_FACE_TASK = ROOT / "face_landmarker.task"
DEFAULT_BERT_MODEL = ROOT / "models" / "bert-base-chinese"

LOCAL_CACHE_DIR = ROOT / ".cache"
ASCII_CACHE_DIR = Path(tempfile.gettempdir()) / "yunque_mediapipe"
LOCAL_FACE_TASK = ASCII_CACHE_DIR / "face_landmarker.task"
LOCAL_CACHE_DIR.mkdir(parents=True, exist_ok=True)
(LOCAL_CACHE_DIR / "numba").mkdir(parents=True, exist_ok=True)
(LOCAL_CACHE_DIR / "matplotlib").mkdir(parents=True, exist_ok=True)
(LOCAL_CACHE_DIR / "fontconfig").mkdir(parents=True, exist_ok=True)
ASCII_CACHE_DIR.mkdir(parents=True, exist_ok=True)
os.environ.setdefault("NUMBA_CACHE_DIR", str(LOCAL_CACHE_DIR / "numba"))
os.environ.setdefault("MPLCONFIGDIR", str(LOCAL_CACHE_DIR / "matplotlib"))
os.environ.setdefault("FONTCONFIG_PATH", str(LOCAL_CACHE_DIR / "fontconfig"))
os.environ.setdefault("HF_HOME", str(LOCAL_CACHE_DIR / "huggingface"))
os.environ.setdefault("HF_HUB_DISABLE_TELEMETRY", "1")


def configure_python_runtime_paths() -> None:
    python_bin_dir = Path(sys.executable).resolve().parent
    python_env_dir = python_bin_dir if (python_bin_dir / "Library" / "bin").exists() else python_bin_dir.parent
    library_bin = python_env_dir / "Library" / "bin"
    path_parts = [str(p) for p in (python_bin_dir, library_bin) if p.exists()]
    if path_parts:
        os.environ["PATH"] = os.pathsep.join(path_parts + [os.environ.get("PATH", "")])
    if library_bin.exists() and hasattr(os, "add_dll_directory"):
        os.add_dll_directory(str(library_bin))
    sndfile_dll = library_bin / "sndfile.dll"
    if sndfile_dll.exists():
        original_find_library = ctypes.util.find_library

        def find_library_with_conda_env(name: str) -> str | None:
            if name == "sndfile":
                return str(sndfile_dll)
            return original_find_library(name)

        ctypes.util.find_library = find_library_with_conda_env


def project_path(path: str | Path) -> Path:
    candidate = Path(path).expanduser()
    return candidate if candidate.is_absolute() else ROOT / candidate


def existing_feature_file(path: Path) -> Path:
    if path.exists():
        return path
    if path == DEFAULT_FEATURE_FILE and LEGACY_FEATURE_FILE.exists():
        return LEGACY_FEATURE_FILE
    return path


configure_python_runtime_paths()

TEXT_SEQ_LEN = 39
AUDIO_SEQ_LEN = 400
VIDEO_SEQ_LEN = 55
AUDIO_DIM = 33
VIDEO_DIM = 9

VIDEO_FEATURE_ORDER = [
    "smile",
    "frown",
    "mouthOpen",
    "browRaise",
    "eyeWiden",
    "jawOpen",
    "cheekRaise",
    "squint",
    "blink",
]


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

    @property
    def sample_id(self) -> str:
        return f"{self.video_id}/{self.clip_id}"


def require_module(name: str, install_hint: str | None = None) -> Any:
    try:
        return __import__(name)
    except ImportError as exc:
        hint = install_hint or name
        raise SystemExit(
            f"Missing dependency `{name}`. Suggested install command for your ai env:\n"
            f"pip install {hint}"
        ) from exc


def resolve_device(device: str, torch: Any) -> str:
    requested = (device or "auto").lower()
    if requested == "auto":
        return "cuda" if torch.cuda.is_available() else "cpu"
    if requested == "cuda" and not torch.cuda.is_available():
        print("[device] CUDA is not available in this Python environment; falling back to CPU.")
        return "cpu"
    return requested


def load_bert_components(args: argparse.Namespace, transformers: Any, torch: Any, device: str) -> tuple[Any, Any]:
    BertModel = transformers.BertModel
    BertTokenizerFast = transformers.BertTokenizerFast
    model_name = project_path(args.bert_model)
    try:
        tokenizer = BertTokenizerFast.from_pretrained(str(model_name), local_files_only=True)
        bert_model = BertModel.from_pretrained(str(model_name), local_files_only=True).to(device)
        bert_model.eval()
        return tokenizer, bert_model
    except Exception as exc:
        model_dir = model_name
        torch_version = getattr(torch, "__version__", "unknown")
        safetensors_hint = ""
        if model_dir.exists() and (model_dir / "pytorch_model.bin").exists() and not (model_dir / "model.safetensors").exists():
            safetensors_hint = (
                "\nThis local directory has pytorch_model.bin but no model.safetensors. "
                f"Your torch version is {torch_version}; recent transformers requires torch >= 2.6 to load .bin weights. "
                "Either download model.safetensors into the same directory, or upgrade CUDA PyTorch to >= 2.6."
            )
        raise SystemExit(
            "Could not load local BERT text encoder.\n"
            f"- requested local model/path: {model_name}\n"
            "Expected a local bert-base-chinese directory containing config.json, vocab.txt, and model weights.\n"
            "Example:\n"
            "  python emotion_model/train_self_mm_mediapipe.py all --bert-model models/bert-base-chinese\n"
            f"{safetensors_hint}\n"
            f"Original error: {type(exc).__name__}: {exc}"
        ) from exc


def prepare_face_task(face_task: Path) -> Path:
    source = face_task.resolve()
    if not source.exists():
        raise SystemExit(f"MediaPipe face task file not found: {source}")

    LOCAL_FACE_TASK.parent.mkdir(parents=True, exist_ok=True)
    needs_copy = not LOCAL_FACE_TASK.exists() or LOCAL_FACE_TASK.stat().st_size != source.stat().st_size
    if needs_copy:
        shutil.copy2(source, LOCAL_FACE_TASK)
        print(f"[extract] copied MediaPipe task to ASCII path: {LOCAL_FACE_TASK}")
    return LOCAL_FACE_TASK.resolve()


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
    return rows


def find_video_path(data_dir: Path, row: LabelRow) -> Path | None:
    candidates = [
        data_dir / row.video_id / f"{row.clip_id}.mp4",
        data_dir / row.video_id / f"{int(row.clip_id):04d}.mp4" if row.clip_id.isdigit() else data_dir / row.video_id / f"{row.clip_id}.mp4",
    ]
    for path in candidates:
        if path.exists():
            return path
    return None


def resample_sequence(sequence: Any, target_len: int, dim: int) -> Any:
    np = require_module("numpy")
    arr = np.asarray(sequence, dtype=np.float32)
    if arr.size == 0:
        return np.zeros((target_len, dim), dtype=np.float32)
    if arr.ndim == 1:
        arr = arr.reshape(-1, dim)
    if arr.shape[0] == target_len:
        return arr.astype(np.float32)

    source_x = np.linspace(0.0, 1.0, arr.shape[0], dtype=np.float32)
    target_x = np.linspace(0.0, 1.0, target_len, dtype=np.float32)
    columns = [np.interp(target_x, source_x, arr[:, col]) for col in range(arr.shape[1])]
    return np.stack(columns, axis=1).astype(np.float32)


def z_norm(sequence: Any) -> Any:
    np = require_module("numpy")
    arr = np.asarray(sequence, dtype=np.float32)
    mean = arr.mean(axis=0, keepdims=True)
    std = arr.std(axis=0, keepdims=True) + 1e-6
    return ((arr - mean) / std).astype(np.float32)


def extract_text_feature(text: str, tokenizer: Any, bert_model: Any, torch: Any, device: str) -> Any:
    encoded = tokenizer(
        text or "",
        max_length=TEXT_SEQ_LEN,
        padding="max_length",
        truncation=True,
        return_tensors="pt",
    )
    encoded = {key: value.to(device) for key, value in encoded.items()}
    with torch.inference_mode():
        output = bert_model(**encoded).last_hidden_state
    return output[0].detach().cpu().numpy().astype("float32")


def extract_audio_track(video_path: Path, sample_rate: int = 22050) -> tuple[Any, int]:
    librosa = require_module("librosa")
    try:
        y, sr = librosa.load(str(video_path), sr=sample_rate, mono=True)
        return y, sr
    except Exception:
        cmd = ["where", "ffmpeg"] if os.name == "nt" else ["which", "ffmpeg"]
        ffmpeg = subprocess.run(cmd, capture_output=True, text=True)
        if ffmpeg.returncode != 0:
            raise RuntimeError(
                f"LibROSA could not read audio from {video_path}, and ffmpeg is not available for fallback extraction.\n"
                "Suggested install command for your ai env, please review before running:\n"
                "conda install -c conda-forge ffmpeg"
            )
        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
            tmp_name = tmp.name
        try:
            subprocess.run(
                [
                    "ffmpeg",
                    "-y",
                    "-i",
                    str(video_path),
                    "-vn",
                    "-ac",
                    "1",
                    "-ar",
                    str(sample_rate),
                    tmp_name,
                ],
                check=True,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            y, sr = librosa.load(tmp_name, sr=sample_rate, mono=True)
            return y, sr
        finally:
            if os.path.exists(tmp_name):
                os.remove(tmp_name)


def extract_audio_feature(video_path: Path) -> Any:
    np = require_module("numpy")
    librosa = require_module("librosa")
    y, sr = extract_audio_track(video_path, sample_rate=22050)
    if y.size == 0:
        return np.zeros((AUDIO_SEQ_LEN, AUDIO_DIM), dtype=np.float32)

    hop_length = 512
    frame_length = 2048
    f0 = librosa.yin(y, fmin=50, fmax=500, sr=sr, frame_length=frame_length, hop_length=hop_length)
    log_f0 = np.log(np.nan_to_num(f0, nan=0.0, posinf=0.0, neginf=0.0) + 1e-6)[None, :]
    mfcc = librosa.feature.mfcc(y=y, sr=sr, n_mfcc=20, hop_length=hop_length, n_fft=frame_length, htk=True)
    cqt = np.abs(librosa.cqt(y=y, sr=sr, hop_length=hop_length, n_bins=12, bins_per_octave=12))
    cqt = librosa.amplitude_to_db(cqt, ref=np.max)

    min_len = min(log_f0.shape[1], mfcc.shape[1], cqt.shape[1])
    stacked = np.concatenate([log_f0[:, :min_len], mfcc[:, :min_len], cqt[:, :min_len]], axis=0).T
    return z_norm(resample_sequence(stacked, AUDIO_SEQ_LEN, AUDIO_DIM))


def blendshape_map(result: Any) -> dict[str, float]:
    categories = []
    if result.face_blendshapes:
        categories = result.face_blendshapes[0]
    return {item.category_name: float(item.score) for item in categories}


def mean_values(scores: dict[str, float], names: list[str]) -> float:
    if not names:
        return 0.0
    return float(sum(scores.get(name, 0.0) for name in names) / len(names))


def mediapipe_feature_from_scores(scores: dict[str, float]) -> list[float]:
    return [
        mean_values(scores, ["mouthSmileLeft", "mouthSmileRight"]),
        mean_values(scores, ["browDownLeft", "browDownRight"]),
        float(scores.get("mouthOpen", 0.0)),
        mean_values(scores, ["browOuterUpLeft", "browOuterUpRight", "browInnerUp"]),
        mean_values(scores, ["eyeWideLeft", "eyeWideRight"]),
        float(scores.get("jawOpen", 0.0)),
        mean_values(scores, ["cheekSquintLeft", "cheekSquintRight"]),
        mean_values(scores, ["eyeSquintLeft", "eyeSquintRight"]),
        mean_values(scores, ["eyeBlinkLeft", "eyeBlinkRight"]),
    ]


def extract_video_feature_in_process(video_path: Path, face_task: Path) -> Any:
    np = require_module("numpy")
    cv2 = require_module("cv2", "opencv-python")
    mp = require_module("mediapipe")
    from mediapipe.tasks import python
    from mediapipe.tasks.python import vision

    if not face_task.exists():
        raise FileNotFoundError(f"MediaPipe face task file not found: {face_task}")

    cap = cv2.VideoCapture(str(video_path))
    if not cap.isOpened():
        raise RuntimeError(f"Could not open video: {video_path}")
    source_fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
    sample_every = max(1, round(source_fps / 30.0))

    options = vision.FaceLandmarkerOptions(
        base_options=python.BaseOptions(
            model_asset_path=str(face_task),
            delegate=python.BaseOptions.Delegate.CPU,
        ),
        running_mode=vision.RunningMode.IMAGE,
        output_face_blendshapes=True,
        num_faces=1,
    )
    features: list[list[float]] = []
    with vision.FaceLandmarker.create_from_options(options) as detector:
        frame_index = 0
        while True:
            ok, frame = cap.read()
            if not ok:
                break
            if frame_index % sample_every == 0:
                rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
                image = mp.Image(image_format=mp.ImageFormat.SRGB, data=rgb)
                result = detector.detect(image)
                scores = blendshape_map(result)
                features.append(mediapipe_feature_from_scores(scores))
            frame_index += 1
    cap.release()

    if not features:
        return np.zeros((VIDEO_SEQ_LEN, VIDEO_DIM), dtype=np.float32)
    return resample_sequence(features, VIDEO_SEQ_LEN, VIDEO_DIM)


def extract_video_feature(video_path: Path, face_task: Path) -> Any:
    np = require_module("numpy")
    if not face_task.exists():
        raise FileNotFoundError(f"Prepared MediaPipe face task file not found: {face_task}")
    with tempfile.NamedTemporaryFile(suffix=".pkl", delete=False) as tmp:
        out_path = Path(tmp.name)
    command = [
        sys.executable,
        str(Path(__file__).resolve()),
        "_video_one",
        "--video",
        str(video_path),
        "--face-task",
        str(face_task),
        "--out",
        str(out_path),
    ]
    result = subprocess.run(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    if result.returncode == 0 and out_path.exists():
        with out_path.open("rb") as handle:
            feature = pickle.load(handle)
        out_path.unlink(missing_ok=True)
        return np.asarray(feature, dtype=np.float32)

    out_path.unlink(missing_ok=True)
    print(
        "[extract] MediaPipe child process failed; using zero video features for "
        f"{video_path.name}. returncode={result.returncode}; face_task={face_task}; exists={face_task.exists()}"
    )
    if result.stderr:
        print(result.stderr[-1200:])
    return np.zeros((VIDEO_SEQ_LEN, VIDEO_DIM), dtype=np.float32)


def extract_dataset(args: argparse.Namespace) -> None:
    np = require_module("numpy")
    torch = require_module("torch")
    transformers = require_module("transformers")

    data_dir = project_path(args.data_dir)
    label_file = project_path(args.label_file)
    out_file = project_path(args.out_file)
    out_file.parent.mkdir(parents=True, exist_ok=True)

    rows = parse_label_csv(label_file)
    rows_with_video = [(row, find_video_path(data_dir, row)) for row in rows]
    rows_with_video = [(row, path) for row, path in rows_with_video if path is not None]
    if args.limit:
        rows_with_video = rows_with_video[: args.limit]
    if not rows_with_video:
        raise SystemExit(f"No videos found under {data_dir}; checked labels from {label_file}")

    device = resolve_device(args.device, torch)
    tokenizer, bert_model = load_bert_components(args, transformers, torch, device)
    face_task = prepare_face_task(project_path(args.face_task))

    dataset: dict[str, list[dict[str, Any]]] = {"train": [], "valid": [], "test": []}
    for index, (row, video_path) in enumerate(rows_with_video, start=1):
        print(f"[extract] {index}/{len(rows_with_video)} {row.sample_id} {video_path.name}")
        text_feature = extract_text_feature(row.text, tokenizer, bert_model, torch, device)
        audio_feature = extract_audio_feature(video_path)
        video_feature = extract_video_feature(video_path, face_task)
        sample = {
            "id": row.sample_id,
            "video_path": str(video_path),
            "raw_text": row.text,
            "text": text_feature.astype(np.float32),
            "audio": audio_feature.astype(np.float32),
            "vision": video_feature.astype(np.float32),
            "labels": {
                "fusion": np.float32(row.label),
                "text": np.float32(row.label_t),
                "audio": np.float32(row.label_a),
                "vision": np.float32(row.label_v),
            },
            "annotation": row.annotation,
        }
        split = row.split if row.split in dataset else "train"
        dataset[split].append(sample)

    payload = {
        "meta": {
            "text_seq_len": TEXT_SEQ_LEN,
            "audio_seq_len": AUDIO_SEQ_LEN,
            "video_seq_len": VIDEO_SEQ_LEN,
            "text_dim": 768,
            "audio_dim": AUDIO_DIM,
            "video_dim": VIDEO_DIM,
            "video_feature_order": VIDEO_FEATURE_ORDER,
            "source": "CH-SIMS-style labels with LibROSA audio and MediaPipe blendshape video features",
        },
        "data": dataset,
    }
    with out_file.open("wb") as handle:
        pickle.dump(payload, handle)
    counts = {split: len(items) for split, items in dataset.items()}
    print(f"[extract] saved {out_file} counts={counts}")


def make_self_mm_class(torch: Any, nn: Any, F: Any):
    class AuViSubNet(nn.Module):
        def __init__(self, in_size: int, hidden_size: int, out_size: int, dropout: float = 0.1):
            super().__init__()
            self.rnn = nn.LSTM(in_size, hidden_size, batch_first=True)
            self.dropout = nn.Dropout(dropout)
            self.linear = nn.Linear(hidden_size, out_size)

        def forward(self, x: Any) -> Any:
            _, final_states = self.rnn(x)
            hidden = self.dropout(final_states[0][-1])
            return self.linear(hidden)

    class SelfMMMediaPipe(nn.Module):
        def __init__(self, text_dim: int = 768, audio_dim: int = 33, video_dim: int = 9):
            super().__init__()
            self.audio_model = AuViSubNet(audio_dim, 16, 16)
            self.video_model = AuViSubNet(video_dim, 32, 32)

            self.post_fusion_dropout = nn.Dropout(0.1)
            self.post_fusion_layer_1 = nn.Linear(text_dim + 16 + 32, 128)
            self.post_fusion_layer_2 = nn.Linear(128, 128)
            self.post_fusion_layer_3 = nn.Linear(128, 1)

            self.post_text_dropout = nn.Dropout(0.1)
            self.post_text_layer_1 = nn.Linear(text_dim, 64)
            self.post_text_layer_2 = nn.Linear(64, 64)
            self.post_text_layer_3 = nn.Linear(64, 1)

            self.post_audio_dropout = nn.Dropout(0.1)
            self.post_audio_layer_1 = nn.Linear(16, 16)
            self.post_audio_layer_2 = nn.Linear(16, 16)
            self.post_audio_layer_3 = nn.Linear(16, 1)

            self.post_video_dropout = nn.Dropout(0.1)
            self.post_video_layer_1 = nn.Linear(32, 32)
            self.post_video_layer_2 = nn.Linear(32, 32)
            self.post_video_layer_3 = nn.Linear(32, 1)

        def forward(self, text: Any, audio: Any, video: Any) -> dict[str, Any]:
            text_features = text[:, 0, :]
            audio_features = self.audio_model(audio)
            video_features = self.video_model(video)

            fusion_h = torch.cat([text_features, audio_features, video_features], dim=-1)
            fusion_h = F.relu(self.post_fusion_layer_1(self.post_fusion_dropout(fusion_h)), inplace=False)
            text_h = F.relu(self.post_text_layer_1(self.post_text_dropout(text_features)), inplace=False)
            audio_h = F.relu(self.post_audio_layer_1(self.post_audio_dropout(audio_features)), inplace=False)
            video_h = F.relu(self.post_video_layer_1(self.post_video_dropout(video_features)), inplace=False)

            fusion_out = self.post_fusion_layer_3(F.relu(self.post_fusion_layer_2(fusion_h), inplace=False))
            text_out = self.post_text_layer_3(F.relu(self.post_text_layer_2(text_h), inplace=False))
            audio_out = self.post_audio_layer_3(F.relu(self.post_audio_layer_2(audio_h), inplace=False))
            video_out = self.post_video_layer_3(F.relu(self.post_video_layer_2(video_h), inplace=False))
            return {"M": fusion_out, "T": text_out, "A": audio_out, "V": video_out}

    return SelfMMMediaPipe


def train_model(args: argparse.Namespace) -> None:
    np = require_module("numpy")
    torch = require_module("torch")
    nn = torch.nn
    F = torch.nn.functional
    import copy
    from torch.utils.data import DataLoader, Dataset

    class SimsFeatureDataset(Dataset):
        def __init__(self, samples: list[dict[str, Any]]):
            self.samples = samples

        def __len__(self) -> int:
            return len(self.samples)

        def __getitem__(self, index: int) -> dict[str, Any]:
            item = self.samples[index]
            labels = item["labels"]
            return {
                "text": torch.tensor(item["text"], dtype=torch.float32),
                "audio": torch.tensor(item["audio"], dtype=torch.float32),
                "vision": torch.tensor(item["vision"], dtype=torch.float32),
                "labels": torch.tensor(
                    [labels["fusion"], labels["text"], labels["audio"], labels["vision"]],
                    dtype=torch.float32,
                ),
            }

    def evaluate(model: Any, loader: Any, device: str) -> dict[str, float]:
        if loader is None:
            return {}
        model.eval()
        errors = []
        with torch.inference_mode():
            for batch in loader:
                text = batch["text"].to(device)
                audio = batch["audio"].to(device)
                vision = batch["vision"].to(device)
                labels = batch["labels"].to(device)
                out = model(text, audio, vision)
                pred = torch.cat([out["M"], out["T"], out["A"], out["V"]], dim=1)
                errors.append(torch.abs(pred - labels).cpu().numpy())
        if not errors:
            return {}
        mae = np.concatenate(errors, axis=0).mean(axis=0)
        return {"mae_fusion": float(mae[0]), "mae_text": float(mae[1]), "mae_audio": float(mae[2]), "mae_vision": float(mae[3])}

    feature_file = existing_feature_file(project_path(args.feature_file))
    with feature_file.open("rb") as handle:
        payload = pickle.load(handle)
    data = payload["data"]
    train_samples = data.get("train", [])
    if not train_samples:
        raise SystemExit(f"No train samples in {feature_file}")

    random.seed(args.seed)
    torch.manual_seed(args.seed)
    device = resolve_device(args.device, torch)
    SelfMMMediaPipe = make_self_mm_class(torch, nn, F)
    model = SelfMMMediaPipe(text_dim=768, audio_dim=AUDIO_DIM, video_dim=VIDEO_DIM).to(device)
    optimizer = torch.optim.AdamW(model.parameters(), lr=args.lr, weight_decay=args.weight_decay)
    loss_fn = nn.MSELoss()

    train_loader = DataLoader(SimsFeatureDataset(train_samples), batch_size=args.batch_size, shuffle=True)
    valid_loader = DataLoader(SimsFeatureDataset(data.get("valid", [])), batch_size=args.batch_size) if data.get("valid") else None
    test_loader = DataLoader(SimsFeatureDataset(data.get("test", [])), batch_size=args.batch_size) if data.get("test") else None
    monitor_loader = valid_loader or test_loader
    monitor_name = "valid" if valid_loader is not None else "test"
    best_score = float("inf")
    best_epoch = 0
    best_metrics: dict[str, float] = {}
    best_state = copy.deepcopy(model.state_dict())
    patience = max(int(args.patience), 0)
    stale_epochs = 0

    for epoch in range(1, args.epochs + 1):
        model.train()
        losses = []
        for batch in train_loader:
            text = batch["text"].to(device)
            audio = batch["audio"].to(device)
            vision = batch["vision"].to(device)
            labels = batch["labels"].to(device)
            out = model(text, audio, vision)
            loss_f = loss_fn(out["M"].squeeze(-1), labels[:, 0])
            loss_t = loss_fn(out["T"].squeeze(-1), labels[:, 1])
            loss_a = loss_fn(out["A"].squeeze(-1), labels[:, 2])
            loss_v = loss_fn(out["V"].squeeze(-1), labels[:, 3])
            loss = loss_f + args.modal_loss_weight * (loss_t + loss_a + loss_v)
            optimizer.zero_grad()
            loss.backward()
            torch.nn.utils.clip_grad_norm_(model.parameters(), max_norm=2.0)
            optimizer.step()
            losses.append(float(loss.detach().cpu().item()))
        metrics = evaluate(model, monitor_loader, device)
        train_loss = sum(losses) / max(len(losses), 1)
        score = metrics.get("mae_fusion", train_loss)
        improved = score < best_score - args.min_delta
        if improved:
            best_score = score
            best_epoch = epoch
            best_metrics = metrics
            best_state = copy.deepcopy(model.state_dict())
            stale_epochs = 0
        else:
            stale_epochs += 1
        marker = " *best*" if improved else ""
        print(
            f"[train] epoch={epoch} loss={train_loss:.4f} {monitor_name}_metrics={metrics}"
            f" best_epoch={best_epoch}{marker}"
        )
        if patience and stale_epochs >= patience:
            print(f"[train] early stopping at epoch={epoch}; no {monitor_name} mae_fusion improvement for {patience} epochs.")
            break

    out_file = project_path(args.model_file)
    out_file.parent.mkdir(parents=True, exist_ok=True)
    last_state = copy.deepcopy(model.state_dict())
    model.load_state_dict(best_state)
    saved_args = {key: value for key, value in vars(args).items() if key != "func"}
    torch.save(
        {
            "model": best_state,
            "meta": payload["meta"],
            "args": saved_args,
            "best_epoch": best_epoch,
            "best_metrics": best_metrics,
            "monitor": monitor_name,
        },
        out_file,
    )
    last_file = project_path(args.last_model_file)
    last_file.parent.mkdir(parents=True, exist_ok=True)
    torch.save(
        {
            "model": last_state,
            "meta": payload["meta"],
            "args": saved_args,
            "best_epoch": best_epoch,
            "best_metrics": best_metrics,
            "monitor": monitor_name,
        },
        last_file,
    )
    print(f"[train] saved_best {out_file} best_epoch={best_epoch} best_metrics={best_metrics}")
    print(f"[train] saved_last {last_file}")
    print(f"[train] test_metrics={evaluate(model, test_loader, device)}")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Extract CH-SIMS-style features with LibROSA + MediaPipe and train SELF-MM.")
    subparsers = parser.add_subparsers(dest="command", required=True)

    video_one = subparsers.add_parser("_video_one")
    video_one.add_argument("--video", required=True)
    video_one.add_argument("--face-task", required=True)
    video_one.add_argument("--out", required=True)
    video_one.set_defaults(func=run_video_one)

    extract = subparsers.add_parser("extract")
    extract.add_argument("--data-dir", default=str(DEFAULT_DATA_DIR))
    extract.add_argument("--label-file", default=str(DEFAULT_LABEL_FILE))
    extract.add_argument("--out-file", default=str(DEFAULT_FEATURE_FILE))
    extract.add_argument("--face-task", default=str(DEFAULT_FACE_TASK))
    extract.add_argument("--bert-model", default=str(DEFAULT_BERT_MODEL))
    extract.add_argument("--device", default="auto")
    extract.add_argument("--limit", type=int, default=0)
    extract.set_defaults(func=extract_dataset)

    train = subparsers.add_parser("train")
    train.add_argument("--feature-file", default=str(DEFAULT_FEATURE_FILE))
    train.add_argument("--model-file", default=str(DEFAULT_MODEL_FILE))
    train.add_argument("--last-model-file", default=str(DEFAULT_LAST_MODEL_FILE))
    train.add_argument("--device", default="auto")
    train.add_argument("--epochs", type=int, default=50)
    train.add_argument("--batch-size", type=int, default=32)
    train.add_argument("--lr", type=float, default=1e-3)
    train.add_argument("--weight-decay", type=float, default=1e-4)
    train.add_argument("--modal-loss-weight", type=float, default=0.5)
    train.add_argument("--patience", type=int, default=8)
    train.add_argument("--min-delta", type=float, default=1e-4)
    train.add_argument("--seed", type=int, default=1111)
    train.set_defaults(func=train_model)

    all_cmd = subparsers.add_parser("all")
    all_cmd.add_argument("--data-dir", default=str(DEFAULT_DATA_DIR))
    all_cmd.add_argument("--label-file", default=str(DEFAULT_LABEL_FILE))
    all_cmd.add_argument("--feature-file", default=str(DEFAULT_FEATURE_FILE))
    all_cmd.add_argument("--model-file", default=str(DEFAULT_MODEL_FILE))
    all_cmd.add_argument("--last-model-file", default=str(DEFAULT_LAST_MODEL_FILE))
    all_cmd.add_argument("--face-task", default=str(DEFAULT_FACE_TASK))
    all_cmd.add_argument("--bert-model", default=str(DEFAULT_BERT_MODEL))
    all_cmd.add_argument("--device", default="auto")
    all_cmd.add_argument("--limit", type=int, default=0)
    all_cmd.add_argument("--epochs", type=int, default=50)
    all_cmd.add_argument("--batch-size", type=int, default=32)
    all_cmd.add_argument("--lr", type=float, default=1e-3)
    all_cmd.add_argument("--weight-decay", type=float, default=1e-4)
    all_cmd.add_argument("--modal-loss-weight", type=float, default=0.5)
    all_cmd.add_argument("--patience", type=int, default=8)
    all_cmd.add_argument("--min-delta", type=float, default=1e-4)
    all_cmd.add_argument("--seed", type=int, default=1111)
    all_cmd.set_defaults(func=run_all)
    return parser


def run_video_one(args: argparse.Namespace) -> None:
    feature = extract_video_feature_in_process(project_path(args.video), project_path(args.face_task))
    with project_path(args.out).open("wb") as handle:
        pickle.dump(feature, handle)


def run_all(args: argparse.Namespace) -> None:
    extract_args = argparse.Namespace(
        data_dir=args.data_dir,
        label_file=args.label_file,
        out_file=args.feature_file,
        face_task=args.face_task,
        bert_model=args.bert_model,
        device=args.device,
        limit=args.limit,
    )
    extract_dataset(extract_args)
    train_args = argparse.Namespace(
        feature_file=args.feature_file,
        model_file=args.model_file,
        last_model_file=args.last_model_file,
        device=args.device,
        epochs=args.epochs,
        batch_size=args.batch_size,
        lr=args.lr,
        weight_decay=args.weight_decay,
        modal_loss_weight=args.modal_loss_weight,
        patience=args.patience,
        min_delta=args.min_delta,
        seed=args.seed,
    )
    train_model(train_args)


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
