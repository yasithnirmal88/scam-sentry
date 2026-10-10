"""
risk/freshness.py
-----------------
Lightweight freshness / liveness signals for job postings.

No browsers, no network — only the stored `posted_at` value and the
posting text. Everything here is total and graceful: unparseable or
missing dates yield None/"unknown", never an exception.

Bands (thresholds live in config, env-overridable):
  age > VERY_STALE_DAYS (90)  -> very_stale (stronger signal)
  age > STALE_DAYS (60)       -> stale (concerning)
  otherwise                   -> fresh
  no usable date              -> unknown
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from typing import Any, Optional

logger = logging.getLogger("scam_sentry.freshness")

STALE_DAYS = 60
VERY_STALE_DAYS = 90

try:
    import config as _config
    STALE_DAYS = int(getattr(_config, "FRESHNESS_STALE_DAYS", STALE_DAYS))
    VERY_STALE_DAYS = int(getattr(_config, "FRESHNESS_VERY_STALE_DAYS", VERY_STALE_DAYS))
except Exception:
    pass

_STRPTIME_FORMATS = (
    "%Y-%m-%d",
    "%Y-%m-%d %H:%M:%S",
    "%Y/%m/%d",
    "%d %b %Y",
    "%d %B %Y",
    "%b %d, %Y",
    "%B %d, %Y",
)


def parse_posted_at(value: Any) -> Optional[datetime]:
    """Parse a posted date in any common shape. None when unusable."""
    if value is None:
        return None
    if isinstance(value, datetime):
        dt = value
    elif isinstance(value, (int, float)):
        dt = _from_epoch(value)
    elif isinstance(value, str):
        s = value.strip()
        if not s:
            return None
        dt = _from_string(s)
    else:
        return None
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _from_epoch(value: float) -> Optional[datetime]:
    try:
        v = float(value)
    except (TypeError, ValueError):
        return None
    if v <= 0:
        return None
    if v > 1e14:  # microseconds
        v /= 1e6
    elif v > 1e11:  # milliseconds
        v /= 1e3
    try:
        return datetime.fromtimestamp(v, tz=timezone.utc)
    except (OSError, OverflowError, ValueError):
        return None


def _from_string(s: str) -> Optional[datetime]:
    # Pure epoch strings ("1791600009").
    if s.replace(".", "", 1).isdigit():
        return _from_epoch(float(s))
    # ISO 8601 (handles trailing Z on modern Python; normalize for older).
    try:
        return datetime.fromisoformat(s.replace("Z", "+00:00"))
    except ValueError:
        pass
    for fmt in _STRPTIME_FORMATS:
        try:
            return datetime.strptime(s, fmt)
        except ValueError:
            continue
    # RFC 2822 ("Mon, 02 Oct 2026 10:00:00 GMT") and friends.
    try:
        return parsedate_to_datetime(s)
    except (TypeError, ValueError):
        return None


def job_age_days(posted_at: Any, now: Optional[datetime] = None) -> Optional[int]:
    """Whole days since posting. None when the date is missing/unusable."""
    dt = parse_posted_at(posted_at)
    if dt is None:
        return None
    ref = now or datetime.now(timezone.utc)
    if ref.tzinfo is None:
        ref = ref.replace(tzinfo=timezone.utc)
    age = (ref - dt).days
    return max(0, age)  # future-dated postings count as fresh, not errors


def freshness_band(age_days: Optional[int]) -> str:
    """One of: very_stale / stale / fresh / unknown."""
    if age_days is None:
        return "unknown"
    if age_days > VERY_STALE_DAYS:
        return "very_stale"
    if age_days > STALE_DAYS:
        return "stale"
    return "fresh"


def freshness_status(posted_at: Any, has_evergreen: bool = False,
                     now: Optional[datetime] = None) -> dict[str, Any]:
    """Small debuggable snapshot for logs, tests, and future UI use."""
    age = job_age_days(posted_at, now=now)
    band = freshness_band(age)
    # Liveness read: a dated, non-evergreen recent posting looks live;
    # undated evergreen wording looks the least live. No browser involved.
    if band in ("stale", "very_stale"):
        liveness = "possibly-stale"
    elif band == "unknown" and has_evergreen:
        liveness = "possibly-stale"
    elif band == "unknown":
        liveness = "unknown"
    else:
        liveness = "likely-active"
    return {"age_days": age, "band": band, "has_date": age is not None,
            "has_evergreen": has_evergreen, "liveness": liveness}
