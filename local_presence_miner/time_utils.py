from __future__ import annotations

from datetime import UTC, datetime


def utc_now() -> datetime:
    """Return a timezone-aware UTC timestamp."""
    return datetime.now(UTC)


def utc_now_iso() -> str:
    return utc_now().isoformat(timespec="seconds")
