from __future__ import annotations

import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from storage import r2_store


def main() -> int:
    if not r2_store.is_enabled():
        print("R2 is not configured. Check R2_ENABLED, R2_BUCKET, R2_ENDPOINT, R2_ACCESS_KEY_ID, R2_SECRET_ACCESS_KEY.")
        return 1

    suffix = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    key = r2_store.object_key("_healthcheck", f"r2-test-{suffix}.txt")
    content = f"yunque r2 healthcheck {suffix}\n"

    try:
        r2_store.put_text(key, content)
        downloaded = r2_store.get_text(key)
        if downloaded != content:
            print("R2 readback mismatch.")
            return 2
        deleted = r2_store.delete_keys([key])
    except Exception as exc:
        print(f"R2 test failed: {exc.__class__.__name__}: {exc}")
        print("Check that R2_ACCESS_KEY_ID and R2_SECRET_ACCESS_KEY are the S3 API credentials, not the account ID or a normal API token.")
        return 3
    print(f"R2 OK: wrote, read, and deleted {key}; deleted={deleted}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
