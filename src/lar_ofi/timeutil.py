"""Time handling. Everything is stored in UTC (ISO-8601 with 'Z').
Europe/Warsaw is used only for display."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

try:
    from zoneinfo import ZoneInfo
except ImportError:  # pragma: no cover
    ZoneInfo = None  # type: ignore


class TimeError(ValueError):
    pass


def parse_utc(value: str | None) -> datetime | None:
    """Parse an ISO-8601 timestamp. Naive timestamps are rejected because the
    user's local zone (Europe/Warsaw) and UTC differ; guessing would corrupt
    the time ordering that the anti-lookahead checks rely on."""
    if value is None or value == "":
        return None
    if not isinstance(value, str):
        raise TimeError(f"timestamp must be a string, got {type(value).__name__}")
    text = value.strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(text)
    except ValueError as exc:
        raise TimeError(f"invalid ISO-8601 timestamp: {value!r}") from exc
    if dt.tzinfo is None:
        raise TimeError(f"timestamp without timezone offset is not accepted: {value!r}")
    return dt.astimezone(timezone.utc)


def fmt_utc(dt: datetime | None) -> str | None:
    if dt is None:
        return None
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def now_utc() -> datetime:
    return datetime.now(timezone.utc).replace(microsecond=0)


def to_local_str(dt: datetime | None, tz_name: str = "Europe/Warsaw") -> str | None:
    if dt is None:
        return None
    if ZoneInfo is None:
        return fmt_utc(dt) + " (UTC; zoneinfo unavailable)"
    try:
        tz = ZoneInfo(tz_name)
    except Exception:  # missing tz database (e.g. Windows without tzdata)
        return fmt_utc(dt) + " (UTC; timezone data unavailable)"
    return dt.astimezone(tz).strftime("%Y-%m-%d %H:%M:%S %Z")


TIMEFRAME_SECONDS = {"1M": 60, "5M": 300, "30M": 1800, "4H": 14400}


def floor_bar(dt: datetime, timeframe: str) -> datetime:
    """Open time of the bar containing dt, for bars aligned to 00:00 UTC
    (assumption: OpenMarket/Bybit intraday bars are UTC-aligned)."""
    step = TIMEFRAME_SECONDS[timeframe]
    epoch = int(dt.timestamp())
    return datetime.fromtimestamp(epoch - epoch % step, tz=timezone.utc)


def floor_minute(dt: datetime) -> datetime:
    return dt.replace(second=0, microsecond=0)


def ceil_minute(dt: datetime) -> datetime:
    floored = dt.replace(second=0, microsecond=0)
    return floored if floored == dt else floored + timedelta(minutes=1)
