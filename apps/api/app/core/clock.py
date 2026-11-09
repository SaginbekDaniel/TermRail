"""Single source of "now" for time-dependent workflow logic (job scheduling, debounce windows, TTLs).

Tests replace it with a controlled clock instead of sleeping (e.g. the 120-second Telegram debounce).
Production code must call utcnow() rather than datetime.now() wherever a test needs to move time.
"""

from __future__ import annotations

from datetime import UTC, datetime

_override: datetime | None = None


def utcnow() -> datetime:
    return _override if _override is not None else datetime.now(UTC)


def set_clock_override(value: datetime | None) -> None:
    """Freeze "now" at `value` (timezone-aware) or restore the real clock with None. Tests only."""
    global _override
    if value is not None and value.tzinfo is None:
        raise ValueError("clock override must be timezone-aware")
    _override = value
