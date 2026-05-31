import math
from dataclasses import dataclass
from typing import Dict, List

from core.utils import clamp


VALENCE_WEIGHTS = {
    "text": 0.3,
    "audio": 0.3,
    "video": 0.4,
}


@dataclass
class FineGrainedEmotion:
    label: str
    valence: float
    arousal: float
    confidence: float

def derive_architecture_emotion(
    raw_scores: Dict[str, float],
    video: Dict[str, float],
    modalities: Dict[str, bool],
) -> FineGrainedEmotion:
    fusion_raw = raw_scores["fusion"]
    text_raw = raw_scores["text"]
    audio_raw = raw_scores["audio"]
    video_raw = raw_scores["video"]
    valence_denominator = sum(
        VALENCE_WEIGHTS[name] * float(modalities.get(name, False))
        for name in VALENCE_WEIGHTS
    )
    if valence_denominator > 0:
        valence_fusion = (
            VALENCE_WEIGHTS["text"] * float(modalities.get("text", False)) * text_raw
            + VALENCE_WEIGHTS["audio"] * float(modalities.get("audio", False)) * audio_raw
            + VALENCE_WEIGHTS["video"] * float(modalities.get("video", False)) * video_raw
        ) / valence_denominator
    else:
        valence_fusion = 0.0
    valence = math.tanh(valence_fusion)
    valence = clamp(
        valence
        + 0.22 * float(video.get("smile", 0.0))
        + 0.10 * float(video.get("cheekRaise", 0.0))
        - 0.22 * float(video.get("frown", 0.0))
        - 0.08 * float(video.get("squint", 0.0)),
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
    arousal_base = (
        0.45 * math.tanh(abs(text_raw))
        + 0.20 * math.tanh(abs(audio_raw))
        + 0.10 * math.tanh(abs(video_raw))
        + 0.25 * expression_arousal
    )
    arousal = clamp(0.1 + arousal_base + expression_arousal, 0.0, 1.0)
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
    if valence >= 0.60 and arousal >= 0.50:
        label = "兴奋"
    elif valence >= 0.35:
        label = "高兴"
    elif valence <= -0.60:
        label = "愤怒"
    elif valence <= -0.35:
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
