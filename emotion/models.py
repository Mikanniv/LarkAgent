import __main__
from typing import Dict

import torch
import torch.nn as nn
import torch.nn.functional as F
from transformers import BertModel, BertTokenizerFast

from core.config import BERT_MODEL_PATH
from emotion_model.train_self_mm_mediapipe import (
    AUDIO_DIM,
    AUDIO_SEQ_LEN,
    TEXT_SEQ_LEN,
    VIDEO_DIM,
    VIDEO_SEQ_LEN,
    extract_text_feature,
)


SEQ_LENS = (TEXT_SEQ_LEN, AUDIO_SEQ_LEN, VIDEO_SEQ_LEN)
FEATURE_DIMS = (768, AUDIO_DIM, VIDEO_DIM)


def checkpoint_callable_placeholder(*args, **kwargs):
    raise RuntimeError("Checkpoint CLI callable placeholder should never be executed.")


for _checkpoint_name in ("train_model", "extract_dataset", "run_all", "run_video_one"):
    if not hasattr(__main__, _checkpoint_name):
        setattr(__main__, _checkpoint_name, checkpoint_callable_placeholder)


class AuViSubNet(nn.Module):
    def __init__(self, in_size: int, hidden_size: int, out_size: int, dropout: float = 0.1):
        super().__init__()
        self.rnn = nn.LSTM(in_size, hidden_size, batch_first=True)
        self.dropout = nn.Dropout(dropout)
        self.linear = nn.Linear(hidden_size, out_size)

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        _, final_states = self.rnn(x)
        hidden = self.dropout(final_states[0][-1])
        return self.linear(hidden)


class SELFMM(nn.Module):
    def __init__(self):
        super().__init__()
        self.audio_model = AuViSubNet(AUDIO_DIM, 16, 16)
        self.video_model = AuViSubNet(VIDEO_DIM, 32, 32)

        self.post_fusion_dropout = nn.Dropout(0.1)
        self.post_fusion_layer_1 = nn.Linear(816, 128)
        self.post_fusion_layer_2 = nn.Linear(128, 128)
        self.post_fusion_layer_3 = nn.Linear(128, 1)

        self.post_text_dropout = nn.Dropout(0.1)
        self.post_text_layer_1 = nn.Linear(768, 64)
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

    def forward(self, text: torch.Tensor, audio: torch.Tensor, video: torch.Tensor):
        text_features = text[:, 0, :]
        audio_features = self.audio_model(audio)
        video_features = self.video_model(video)

        fusion_h = torch.cat([text_features, audio_features, video_features], dim=-1)
        fusion_h = self.post_fusion_dropout(fusion_h)
        fusion_h = F.relu(self.post_fusion_layer_1(fusion_h), inplace=False)

        text_h = F.relu(self.post_text_layer_1(self.post_text_dropout(text_features)), inplace=False)
        audio_h = F.relu(self.post_audio_layer_1(self.post_audio_dropout(audio_features)), inplace=False)
        video_h = F.relu(self.post_video_layer_1(self.post_video_dropout(video_features)), inplace=False)

        output_fusion = self.post_fusion_layer_3(F.relu(self.post_fusion_layer_2(fusion_h), inplace=False))
        output_text = self.post_text_layer_3(F.relu(self.post_text_layer_2(text_h), inplace=False))
        output_audio = self.post_audio_layer_3(F.relu(self.post_audio_layer_2(audio_h), inplace=False))
        output_video = self.post_video_layer_3(F.relu(self.post_video_layer_2(video_h), inplace=False))

        return {
            "M": output_fusion,
            "T": output_text,
            "A": output_audio,
            "V": output_video,
            "Feature_t": text_h,
            "Feature_a": audio_h,
            "Feature_v": video_h,
            "Feature_f": fusion_h,
        }


class SelfMMRunner:
    model_name = "self_mm"

    def __init__(self, model_path):
        self.model_path = model_path
        self.device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
        self.model = SELFMM().to(self.device)
        self.tokenizer = BertTokenizerFast.from_pretrained(str(BERT_MODEL_PATH), local_files_only=True)
        self.bert_model = BertModel.from_pretrained(str(BERT_MODEL_PATH), local_files_only=True).to(self.device)
        checkpoint = torch.load(model_path, map_location=self.device, weights_only=False)
        state_dict = checkpoint["model"] if isinstance(checkpoint, dict) and "model" in checkpoint else checkpoint
        cleaned = {key.replace("Model.", "", 1): value for key, value in state_dict.items()}
        self.model.load_state_dict(cleaned)
        self.model.eval()
        self.bert_model.eval()

    def encode_text(self, text: str) -> torch.Tensor:
        feature = extract_text_feature(text, self.tokenizer, self.bert_model, torch, str(self.device))
        return torch.from_numpy(feature).unsqueeze(0).to(self.device)

    @torch.inference_mode()
    def predict(self, text: str, audio_tensor: torch.Tensor, video_tensor: torch.Tensor) -> Dict[str, float]:
        output = self.model(
            self.encode_text(text),
            audio_tensor.to(self.device),
            video_tensor.to(self.device),
        )
        return {
            "fusion": float(output["M"][0, 0].cpu().item()),
            "text": float(output["T"][0, 0].cpu().item()),
            "audio": float(output["A"][0, 0].cpu().item()),
            "video": float(output["V"][0, 0].cpu().item()),
            "feature_norm_fusion": float(output["Feature_f"].norm(dim=-1)[0].cpu().item()),
            "feature_norm_text": float(output["Feature_t"].norm(dim=-1)[0].cpu().item()),
            "feature_norm_audio": float(output["Feature_a"].norm(dim=-1)[0].cpu().item()),
            "feature_norm_video": float(output["Feature_v"].norm(dim=-1)[0].cpu().item()),
        }

    def metadata(self) -> Dict[str, object]:
        return {
            "name": "SELF_MM_MediaPipe",
            "weights": str(self.model_path.name),
            "seq_lens": list(SEQ_LENS),
            "feature_dims": list(FEATURE_DIMS),
            "feature_extractor": "server: BERT + LibROSA + MediaPipe",
        }
