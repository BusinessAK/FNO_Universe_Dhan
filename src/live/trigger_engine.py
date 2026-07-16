"""
Trigger engine — watches each morning's armed setups (daily_setups: trigger_strike /
invalidation_strike) against live spot on 1-minute bar closes, and fires
WAITING -> TRIGGERED / INVALIDATED transitions as events.

Direction is inferred from the trigger/invalidation pair itself (no per-setup-type
special-casing): whichever level sits above the other defines the breakout/breakdown
shape. Uses the same 1%/0.99% buffer src/core/classifier.py already uses for
"broken", so live triggering means the same thing here as it does everywhere else on
the platform.

Purely in-memory: never writes back to daily_setups. DuckDB/EOD stays the system of
record; this state is ephemeral for the session (folds into the live_events journal,
not the compiled DB).
"""
from __future__ import annotations

import time
from collections import deque

TRIGGER_BUFFER = 1.01      # matches src/core/classifier.py:37 (call-side breakout)
INVALIDATE_BUFFER = 0.99   # matches src/core/classifier.py:38 (put-side breakdown)


def load_armed_book(con, date=None) -> dict[str, list[dict]]:
    """Read one day's daily_setups into {symbol: [setup, ...]}, each setup starting
    WAITING. Defaults to the latest date in the table (today's compiled setups)."""
    if date is None:
        date = con.execute("SELECT MAX(date) FROM daily_setups").fetchone()[0]
    rows = con.execute(
        "SELECT symbol, setup_type, bias, trigger_strike, invalidation_strike "
        "FROM daily_setups WHERE date = ?", [date]
    ).fetchall()
    book: dict[str, list[dict]] = {}
    for symbol, setup_type, bias, trig, inval in rows:
        if trig is None or inval is None:
            continue
        book.setdefault(symbol, []).append({
            "setup_type": setup_type,
            "bias": bias,
            "trigger_strike": float(trig),
            "invalidation_strike": float(inval),
            "status": "WAITING",
        })
    return book


def _direction(trig: float, inval: float) -> str | None:
    """'up' = bullish/breakout shape (trigger above invalidation), 'down' = bearish/
    breakdown shape. None for the degenerate case (no inferable direction) — skip
    rather than guess; playbook.py's own construction should prevent this in
    practice (see playbook.py:259-265), but the engine must fail safe if it recurs."""
    if trig > inval:
        return "up"
    if trig < inval:
        return "down"
    return None


class TriggerEngine:
    def __init__(self, armed_book: dict[str, list[dict]],
                 key_symbol: dict[tuple[int, int], str], log_max: int = 500):
        self.armed_book = armed_book
        self.key_symbol = key_symbol
        self.events: deque[dict] = deque(maxlen=log_max)

    def armed_count(self) -> int:
        return sum(len(v) for v in self.armed_book.values())

    def on_bar_close(self, key: tuple[int, int], bar: dict) -> list[dict]:
        """bar = {'t': epoch_minute, 'o','h','l','c': float}. Returns newly-fired
        events (usually empty — only non-empty on an actual transition)."""
        symbol = self.key_symbol.get(key)
        if symbol is None:
            return []
        setups = self.armed_book.get(symbol)
        if not setups:
            return []

        spot = bar.get("c")
        if spot is None:
            return []

        fired: list[dict] = []
        for setup in setups:
            if setup["status"] != "WAITING":
                continue
            trig, inval = setup["trigger_strike"], setup["invalidation_strike"]
            direction = _direction(trig, inval)
            if direction is None:
                continue

            new_status = None
            level = None
            if direction == "up":
                if spot > trig * TRIGGER_BUFFER:
                    new_status, level = "TRIGGERED", trig
                elif spot < inval * INVALIDATE_BUFFER:
                    new_status, level = "INVALIDATED", inval
            else:
                if spot < trig * INVALIDATE_BUFFER:
                    new_status, level = "TRIGGERED", trig
                elif spot > inval * TRIGGER_BUFFER:
                    new_status, level = "INVALIDATED", inval

            if new_status is None:
                continue

            setup["status"] = new_status
            event = {
                "ts": time.time(),
                "symbol": symbol,
                "setup_type": setup["setup_type"],
                "bias": setup["bias"],
                "from": "WAITING",
                "to": new_status,
                "level": level,
                "spot": spot,
            }
            self.events.appendleft(event)
            fired.append(event)
        return fired
