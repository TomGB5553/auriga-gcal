"""Track when the timetable last successfully synced.

Lets run_sync.sh skip a checkpoint that fired while things are already
up to date, and forces a real attempt again soon after any failure.
"""
from __future__ import annotations

import datetime as dt

import config


def is_stale() -> bool:
    if not config.LAST_SUCCESS_FILE.exists():
        return True
    try:
        ts = dt.datetime.fromisoformat(config.LAST_SUCCESS_FILE.read_text().strip())
    except ValueError:
        return True
    age = dt.datetime.now(dt.timezone.utc) - ts
    return age > dt.timedelta(hours=config.REFRESH_STALE_AFTER_HOURS)


def mark_success() -> None:
    config.LAST_SUCCESS_FILE.write_text(dt.datetime.now(dt.timezone.utc).isoformat())


def age_str() -> str:
    if not config.LAST_SUCCESS_FILE.exists():
        return "never synced"
    try:
        ts = dt.datetime.fromisoformat(config.LAST_SUCCESS_FILE.read_text().strip())
    except ValueError:
        return "unknown"
    hours = (dt.datetime.now(dt.timezone.utc) - ts).total_seconds() / 3600
    return f"{hours:.1f}h ago"


if __name__ == "__main__":
    import sys
    # exit 0 = stale (should run), 1 = fresh (should skip) -- for shell use
    print(f"last success: {age_str()}", file=sys.stderr)
    sys.exit(0 if is_stale() else 1)
