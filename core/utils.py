from datetime import datetime
from zoneinfo import ZoneInfo


CHINA_TZ = ZoneInfo("Asia/Shanghai")


def clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


def now_china() -> datetime:
    return datetime.now(CHINA_TZ)


def normalize_timestamp_to_china(timestamp: str = "") -> str:
    if timestamp:
        try:
            parsed = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
            if parsed.tzinfo is None:
                parsed = parsed.replace(tzinfo=CHINA_TZ)
            return parsed.astimezone(CHINA_TZ).isoformat(timespec="seconds")
        except ValueError:
            pass
    return now_china().isoformat(timespec="seconds")


def memory_date_from_payload(timestamp: str = "") -> str:
    return normalize_timestamp_to_china(timestamp)[:10]
