import math
from dataclasses import dataclass
from typing import Dict, List

from core.utils import clamp


@dataclass
class FineGrainedEmotion:
    label: str
    valence: float
    arousal: float
    confidence: float


def sigmoid(value: float) -> float:
    return 1.0 / (1.0 + math.exp(-value))


def derive_architecture_emotion(
    raw_scores: Dict[str, float],
    video: Dict[str, float],
    modalities: Dict[str, bool],
) -> FineGrainedEmotion:
    fusion_raw = raw_scores["fusion"]
    text_raw = raw_scores["text"]
    audio_raw = raw_scores["audio"]
    video_raw = raw_scores["video"]
    valence = math.tanh((0.55 * fusion_raw + 0.25 * text_raw + 0.15 * video_raw + 0.05 * audio_raw) / 1.8)
    valence = clamp(
        valence
        + 0.18 * float(video.get("smile", 0.0))
        + 0.08 * float(video.get("cheekRaise", 0.0))
        - 0.18 * float(video.get("frown", 0.0))
        - 0.06 * float(video.get("squint", 0.0)),
        -1.0,
        1.0,
    )
    expression_arousal = clamp(
        0.25 * float(video.get("mouthOpen", 0.0))
        + 0.30 * float(video.get("jawOpen", 0.0))
        + 0.18 * float(video.get("eyeWiden", 0.0))
        + 0.14 * float(video.get("browRaise", 0.0))
        + 0.13 * float(video.get("squint", 0.0))
        + 0.10 * float(video.get("blink", 0.0)),
        0.0,
        1.0,
    )
    arousal = clamp(
        0.45 * sigmoid(abs(text_raw))
        + 0.20 * sigmoid(abs(audio_raw))
        + 0.10 * sigmoid(abs(video_raw))
        + 0.25 * expression_arousal,
        0.0,
        1.0,
    )
    availability = clamp(
        0.50 * float(modalities.get("text", False))
        + 0.35 * float(modalities.get("audio", False))
        + 0.15 * float(modalities.get("video", False)),
        0.0,
        1.0,
    )
    agreement = clamp(
        1.0
        - 0.40 * abs(fusion_raw - text_raw)
        - 0.30 * abs(fusion_raw - audio_raw)
        - 0.30 * abs(fusion_raw - video_raw),
        0.0,
        1.0,
    )
    strength = clamp(0.55 * abs(valence) + 0.45 * arousal, 0.0, 1.0)
    confidence = clamp(0.4 * availability + 0.3 * agreement + 0.3 * strength, 0.0, 1.0)
    if valence >= 0.75 and arousal >= 0.50:
        label = "兴奋"
    elif valence >= 0.50:
        label = "高兴"
    elif valence <= -0.75:
        label = "愤怒"
    elif valence <= -0.50:
        label = "紧张"
    elif valence >= 0.20 and arousal < 0.50:
        label = "平静"
    elif valence <= -0.20:
        label = "低落"
    else:
        label = "中性"

    return FineGrainedEmotion(
        label=label,
        valence=round(valence, 4),
        arousal=round(arousal, 4),
        confidence=round(confidence, 4),
    )


def make_emotion_bars(emotion: FineGrainedEmotion) -> List[Dict[str, float]]:
    return [
        {"name": "Valence", "value": emotion.valence},
        {"name": "唤醒度", "value": emotion.arousal},
        {"name": "置信度", "value": emotion.confidence},
    ]
