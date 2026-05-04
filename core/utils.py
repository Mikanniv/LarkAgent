from datetime import datetime


def clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


def memory_date_from_payload(timestamp: str = "") -> str:
    if timestamp:
        try:
            return datetime.fromisoformat(timestamp.replace("Z", "+00:00")).date().isoformat()
        except ValueError:
            pass
    return datetime.now().date().isoformat()
