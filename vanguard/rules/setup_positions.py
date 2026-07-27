"""
setup_positions.py — Derives a persistent position lifecycle (trigger -> SL/
target resolution) from session_history, the same frozen per-date records
daily_setups is built from.

Pure function of session_history: same input always produces the same output.
This mirrors how daily_setups itself is a full re-derivation from
session_history on every compile run — daily_compiler.py deletes and rebuilds
the entire duckdb file from scratch each run, so nothing can persist state
independently across runs. Re-deriving the whole position history every time
is the only correct approach here, not a stylistic choice.

Direction (up/down) is inferred from trigger vs invalidation ordering via
_direction below — the canonical home for that rule since the live layer (which
previously owned it, in vanguard.live.trigger_engine) was archived.
"""
from __future__ import annotations


def _direction(trig: float, inval: float) -> str | None:
    """'up' = bullish/breakout shape (trigger above invalidation), 'down' =
    bearish/breakdown shape. None for the degenerate case (no inferable
    direction) — skip rather than guess; playbook.py's own construction should
    prevent this in practice, but callers must fail safe if it recurs."""
    if trig > inval:
        return "up"
    if trig < inval:
        return "down"
    return None

# target = spot +/- RISK_MULTIPLE * abs(spot - invalidation): a 1:2 R:R based on
# the ACTUAL entry price (spot), not the nominal trigger, to preserve the math
# even if the entry occurs far past the trigger level.
RISK_MULTIPLE = 2.0


def _setup_snapshot(day_data: dict) -> dict | None:
    """Extract (setup_type, bias, trigger, invalidation) for one day, or None
    if no setup fired or playbook data is missing (older session_history
    entries compiled before the playbook key existed)."""
    setups = day_data.get("setups") or []
    playbook = day_data.get("playbook") or {}
    if not setups or not playbook:
        return None
    trig = playbook.get("trigger_strike", 0.0)
    inval = playbook.get("invalidation_strike", 0.0)
    if not trig or not inval:
        return None
    primary = day_data.get("primary_setup") or setups[0]
    return {
        "setup_type": primary,
        "bias": playbook.get("bias", "Neutral"),
        "trigger": float(trig),
        "invalidation": float(inval),
    }


def derive_positions(session_history: dict, stale_after_sessions: int = 10) -> list[dict]:
    """Walk each symbol's full chronological history and derive the open/
    resolved position lifecycle.

    Per day, per symbol:
      1. If a position is open, check today's close against its FROZEN
         sl_price/target_price (set once, at trigger time — never
         recomputed from later days' recalculated trigger/invalidation
         levels). Resolve if breached. This runs on every trading day the
         position is open, not just days a new setup happens to also fire —
         a position is not tied to whether the screener keeps flagging the
         symbol.
      2. Then check today's setup (if any) for a new trigger:
         - No position open + triggered -> open a new position.
         - Position open, same direction, triggered again -> no-op
           (reinforcement, not a new entry).
         - Position open, OPPOSITE direction, triggered -> close the old
           position (status CLOSED_BY_REVERSAL) at today's price, then open
           the new one. If the day's close ALSO independently hit the old
           position's SL/target (step 1), that resolution wins — a
           SL_HIT/TARGET_HIT is never overwritten by a same-day reversal.

    A symbol that stops appearing in session_history altogether (delisted,
    dropped from F&O eligibility, a corporate-action ticker change) leaves
    any open position with no more data to ever resolve it against — left
    alone it would sit "OPEN" forever. If a symbol's last-seen date isn't
    among the `stale_after_sessions` most recent sessions in the WHOLE
    dataset (not just that symbol), any position still open at that point is
    marked STALE instead, with resolved_date/resolved_price set to the last
    date/price actually observed — so point-in-time (HUD time-travel)
    queries for any earlier date still correctly show it as open, while
    "currently active" views correctly stop counting it.

    Returns a flat list of dicts, one row per position (both open and
    resolved) — NOT one row per symbol. A symbol accumulates a new row each
    time it triggers, resolves, and (eventually) triggers again.
    """
    positions: list[dict] = []
    all_dates = sorted({d for history in session_history.values() for d in history})
    recent_dates = set(all_dates[-stale_after_sessions:]) if all_dates else set()

    for symbol, history in session_history.items():
        dates = sorted(history.keys())
        open_pos: dict | None = None

        for d in dates:
            day_data = history[d]
            spot = day_data.get("spot_close")
            if spot is None:
                continue  # no price data this day — carry position forward untouched
            spot = float(spot)

            # 1) Resolve an already-open position using today's close.
            if open_pos is not None:
                up = open_pos["direction"] == "up"
                if up:
                    if spot >= open_pos["target_price"]:
                        open_pos["status"] = "TARGET_HIT"
                    elif spot <= open_pos["sl_price"]:
                        open_pos["status"] = "SL_HIT"
                else:
                    if spot <= open_pos["target_price"]:
                        open_pos["status"] = "TARGET_HIT"
                    elif spot >= open_pos["sl_price"]:
                        open_pos["status"] = "SL_HIT"
                if open_pos["status"] != "OPEN":
                    open_pos["resolved_date"] = d
                    open_pos["resolved_price"] = spot
                    positions.append(open_pos)
                    open_pos = None

            # 2) Check today's setup for a new trigger or a reversal close.
            snap = _setup_snapshot(day_data)
            if snap is None:
                continue
            direction = _direction(snap["trigger"], snap["invalidation"])
            if direction is None:
                continue  # degenerate trig == invalidation — no directional read
            new_up = direction == "up"
            triggered = (spot >= snap["trigger"]) if new_up else (spot <= snap["trigger"])
            if not triggered:
                continue

            if open_pos is not None and (open_pos["direction"] == "up") != new_up:
                # Opposite-direction reversal: close old, then fall through to open new.
                open_pos["status"] = "CLOSED_BY_REVERSAL"
                open_pos["resolved_date"] = d
                open_pos["resolved_price"] = spot
                positions.append(open_pos)
                open_pos = None

            if open_pos is None:
                risk = abs(spot - snap["invalidation"])
                target = (spot + RISK_MULTIPLE * risk if new_up
                          else spot - RISK_MULTIPLE * risk)
                open_pos = {
                    "symbol": symbol,
                    "setup_type": snap["setup_type"],
                    "bias": snap["bias"],
                    "direction": "up" if new_up else "down",
                    "trigger_date": d,
                    "trigger_price": spot,
                    "sl_price": float(snap["invalidation"]),
                    "target_price": float(target),
                    "status": "OPEN",
                    "resolved_date": None,
                    "resolved_price": None,
                }
            # else: same-direction re-trigger while already open — no-op.

        if open_pos is not None:
            if dates and dates[-1] not in recent_dates:
                open_pos["status"] = "STALE"
                open_pos["resolved_date"] = dates[-1]
                open_pos["resolved_price"] = float(
                    history[dates[-1]].get("spot_close") or open_pos["trigger_price"])
            positions.append(open_pos)

    return positions
