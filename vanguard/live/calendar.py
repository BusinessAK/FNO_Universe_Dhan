"""
NSE market calendar — trading-day + session-window checks in IST.

The daemon runs only on trading days within the session window. Holidays are a
static list (update yearly); weekends are computed. Kept dependency-free
(datetime only) so it's trivially testable and has no runtime surprises.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from vanguard.live import config as C

IST = timezone(timedelta(hours=5, minutes=30))

# NSE trading holidays. Extend yearly — a missing holiday only means the daemon
# starts on a closed day and simply sees no ticks (harmless, watchdog logs it).
NSE_HOLIDAYS_2026 = {
    "2026-01-26", "2026-02-16", "2026-03-06", "2026-03-25", "2026-04-01",
    "2026-04-03", "2026-04-14", "2026-05-01", "2026-06-26", "2026-08-15",
    "2026-08-26", "2026-10-02", "2026-10-21", "2026-11-09", "2026-11-24",
    "2026-12-25",
}


def now_ist() -> datetime:
    return datetime.now(IST)


def is_trading_day(dt: datetime | None = None) -> bool:
    dt = dt or now_ist()
    if dt.weekday() >= 5:                       # Sat/Sun
        return False
    return dt.strftime("%Y-%m-%d") not in NSE_HOLIDAYS_2026


def _at(dt: datetime, hm: tuple[int, int]) -> datetime:
    return dt.replace(hour=hm[0], minute=hm[1], second=0, microsecond=0)


def is_market_open(dt: datetime | None = None) -> bool:
    dt = dt or now_ist()
    return is_trading_day(dt) and _at(dt, C.SESSION_OPEN) <= dt <= _at(dt, C.SESSION_CLOSE)


def is_daemon_window(dt: datetime | None = None) -> bool:
    """Whether the daemon should be running (warm-up before open → parity after close)."""
    dt = dt or now_ist()
    return is_trading_day(dt) and _at(dt, C.DAEMON_START) <= dt <= _at(dt, C.DAEMON_STOP)


def seconds_until_daemon_start(dt: datetime | None = None) -> float:
    """Seconds to the next daemon-start; 0 if already in-window. Used to sleep off-hours."""
    dt = dt or now_ist()
    if is_daemon_window(dt):
        return 0.0
    probe = dt
    for _ in range(10):                         # scan forward up to ~10 days
        start = _at(probe, C.DAEMON_START)
        if start > dt and is_trading_day(probe):
            return (start - dt).total_seconds()
        probe = _at(probe + timedelta(days=1), (0, 0))
    return 3600.0                               # fallback: retry in an hour
