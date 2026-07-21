"""Unit tests for vanguard/rules/setup_positions.derive_positions."""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from vanguard.rules.setup_positions import derive_positions


def _day(spot, trigger=None, invalidation=None, setup_type="GAMMA_SQUEEZE",
         bias="Bullish Breakout", setups=None):
    """One day_data entry. Pass trigger/invalidation to simulate a setup
    firing that day; omit both to simulate a screener-silent day (position
    still gets checked against spot_close, just no new-trigger evaluation)."""
    d = {"spot_close": spot}
    if trigger is not None:
        d["setups"] = setups if setups is not None else [setup_type]
        d["primary_setup"] = setup_type
        d["playbook"] = {
            "bias": bias,
            "trigger_strike": trigger,
            "invalidation_strike": invalidation,
        }
    return d


def _history(symbol, **dated_days):
    """dated_days: {"2026-01-01": _day(...), ...} -> session_history shape."""
    return {symbol: dated_days}


class TestBasicLifecycle:
    def test_up_trigger_then_target_hit(self):
        hist = _history(
            "ABC",
            **{
                "2026-01-01": _day(101, trigger=100, invalidation=98),  # triggers, target=100+2*2=104
                "2026-01-02": _day(103),
                "2026-01-03": _day(104.5),  # >= target 104
            },
        )
        rows = derive_positions(hist)
        assert len(rows) == 1
        p = rows[0]
        assert p["symbol"] == "ABC"
        assert p["direction"] == "up"
        assert p["trigger_date"] == "2026-01-01"
        assert p["trigger_price"] == 101
        assert p["sl_price"] == 98
        assert p["target_price"] == 104
        assert p["status"] == "TARGET_HIT"
        assert p["resolved_date"] == "2026-01-03"
        assert p["resolved_price"] == 104.5

    def test_up_trigger_then_sl_hit(self):
        hist = _history(
            "ABC",
            **{
                "2026-01-01": _day(101, trigger=100, invalidation=98),
                "2026-01-02": _day(97.5),  # <= sl 98
            },
        )
        rows = derive_positions(hist)
        assert len(rows) == 1
        assert rows[0]["status"] == "SL_HIT"
        assert rows[0]["resolved_date"] == "2026-01-02"

    def test_down_trigger_then_target_hit(self):
        # down-shaped: trigger < invalidation
        hist = _history(
            "XYZ",
            **{
                "2026-01-01": _day(99, trigger=100, invalidation=102),  # risk=2, target=100-4=96
                "2026-01-02": _day(95.5),
            },
        )
        rows = derive_positions(hist)
        p = rows[0]
        assert p["direction"] == "down"
        assert p["sl_price"] == 102
        assert p["target_price"] == 96
        assert p["status"] == "TARGET_HIT"

    def test_down_trigger_then_sl_hit(self):
        hist = _history(
            "XYZ",
            **{
                "2026-01-01": _day(99, trigger=100, invalidation=102),
                "2026-01-02": _day(102.5),
            },
        )
        rows = derive_positions(hist)
        assert rows[0]["status"] == "SL_HIT"

    def test_position_stays_open_at_end_of_history(self):
        hist = _history(
            "ABC",
            **{
                "2026-01-01": _day(101, trigger=100, invalidation=98),
                "2026-01-02": _day(102),
            },
        )
        rows = derive_positions(hist)
        assert len(rows) == 1
        assert rows[0]["status"] == "OPEN"
        assert rows[0]["resolved_date"] is None
        assert rows[0]["resolved_price"] is None


class TestScreenerSilentDays:
    def test_position_still_checked_when_screener_does_not_fire(self):
        """A day with no new setup (screener silent) must still resolve an
        already-open position against that day's close."""
        hist = _history(
            "ABC",
            **{
                "2026-01-01": _day(101, trigger=100, invalidation=98),
                "2026-01-02": _day(101.5),   # screener silent, position still open
                "2026-01-03": _day(101.8),   # screener silent
                "2026-01-04": _day(104.2),   # screener silent, but hits target
            },
        )
        rows = derive_positions(hist)
        assert len(rows) == 1
        assert rows[0]["status"] == "TARGET_HIT"
        assert rows[0]["resolved_date"] == "2026-01-04"

    def test_missing_spot_close_skipped_not_resolved(self):
        hist = _history(
            "ABC",
            **{
                "2026-01-01": _day(101, trigger=100, invalidation=98),
                "2026-01-02": {"spot_close": None},
                "2026-01-03": _day(104.5),
            },
        )
        rows = derive_positions(hist)
        assert len(rows) == 1
        assert rows[0]["status"] == "TARGET_HIT"
        assert rows[0]["resolved_date"] == "2026-01-03"


class TestRetriggerConflicts:
    def test_same_direction_retrigger_is_noop(self):
        hist = _history(
            "ABC",
            **{
                "2026-01-01": _day(101, trigger=100, invalidation=98),
                "2026-01-02": _day(101.2, trigger=101, invalidation=99),  # same up direction
                "2026-01-03": _day(104.5),  # still resolves the ORIGINAL frozen target (104)
            },
        )
        rows = derive_positions(hist)
        assert len(rows) == 1
        assert rows[0]["trigger_date"] == "2026-01-01"
        assert rows[0]["trigger_price"] == 101
        assert rows[0]["target_price"] == 104

    def test_opposite_direction_retrigger_closes_and_reopens(self):
        hist = _history(
            "ABC",
            **{
                "2026-01-01": _day(101, trigger=100, invalidation=98),  # up, sl=98, target=104
                # close (99) clears the old SL (98) but a down setup triggers here
                "2026-01-02": _day(99, trigger=100, invalidation=102, bias="Bearish Breakdown"),
            },
        )
        rows = derive_positions(hist)
        # 2 rows: the closed-by-reversal old position, plus the new down
        # position, still OPEN (history ends the same day it triggered, so
        # it's flushed unresolved at end-of-loop rather than dropped).
        assert len(rows) == 2
        closed, opened = rows
        assert closed["status"] == "CLOSED_BY_REVERSAL"
        assert closed["resolved_date"] == "2026-01-02"
        assert closed["resolved_price"] == 99
        assert opened["status"] == "OPEN"
        assert opened["direction"] == "down"

    def test_reversal_leaves_new_position_open_and_tracked(self):
        hist = _history(
            "ABC",
            **{
                "2026-01-01": _day(101, trigger=100, invalidation=98),  # up, sl=98
                "2026-01-02": _day(99, trigger=100, invalidation=102, bias="Bearish Breakdown"),  # reversal
                "2026-01-03": _day(93.5),  # resolves the NEW down position: target=100-2*2=96
            },
        )
        rows = derive_positions(hist)
        assert len(rows) == 2
        reversal, new_pos = rows
        assert reversal["status"] == "CLOSED_BY_REVERSAL"
        assert new_pos["direction"] == "down"
        assert new_pos["trigger_date"] == "2026-01-02"
        assert new_pos["target_price"] == 96
        assert new_pos["status"] == "TARGET_HIT"
        assert new_pos["resolved_date"] == "2026-01-03"

    def test_sl_hit_wins_over_reversal_on_same_day(self):
        """If today's close both breaches the open position's SL AND a new
        opposite setup triggers, the resolved row must be labeled SL_HIT, not
        CLOSED_BY_REVERSAL — the SL/target check (step 1) always runs before
        the reversal check (step 2), so a same-day reversal can never
        overwrite an already-resolved SL/target row. The day's fresh
        opposite-direction trigger is still free to open its own new
        position afterward — that's a legitimate independent entry, not a
        continuation of the resolved one."""
        hist = _history(
            "ABC",
            **{
                "2026-01-01": _day(101, trigger=100, invalidation=98),  # up, sl=98
                # close (97.5) both breaches SL (<=98) AND a down setup triggers here
                "2026-01-02": _day(97.5, trigger=98, invalidation=100, bias="Bearish Breakdown"),
            },
        )
        rows = derive_positions(hist)
        assert len(rows) == 2
        closed, opened = rows
        assert closed["status"] == "SL_HIT"
        assert closed["resolved_date"] == "2026-01-02"
        assert opened["status"] == "OPEN"
        assert opened["direction"] == "down"
        assert opened["trigger_date"] == "2026-01-02"


class TestStaleSymbols:
    def test_symbol_that_stops_appearing_goes_stale_not_open(self):
        """ABC's last date is far behind the rest of the dataset (XYZ keeps
        trading up to session 12) — its still-open position must be marked
        STALE, not left looking permanently OPEN."""
        abc_history = {"2026-01-01": _day(101, trigger=100, invalidation=98)}
        xyz_history = {f"2026-01-{d:02d}": _day(50) for d in range(2, 13)}  # 11 more sessions
        hist = {"ABC": abc_history, "XYZ": xyz_history}
        rows = derive_positions(hist, stale_after_sessions=10)
        abc_row = next(r for r in rows if r["symbol"] == "ABC")
        assert abc_row["status"] == "STALE"
        assert abc_row["resolved_date"] == "2026-01-01"
        assert abc_row["resolved_price"] == 101

    def test_symbol_within_recency_window_stays_open(self):
        abc_history = {"2026-01-01": _day(101, trigger=100, invalidation=98)}
        xyz_history = {f"2026-01-{d:02d}": _day(50) for d in range(2, 5)}  # only 3 more sessions
        hist = {"ABC": abc_history, "XYZ": xyz_history}
        rows = derive_positions(hist, stale_after_sessions=10)
        abc_row = next(r for r in rows if r["symbol"] == "ABC")
        assert abc_row["status"] == "OPEN"
        assert abc_row["resolved_date"] is None


class TestMultiplePositionsOverTime:
    def test_trigger_resolve_trigger_again_produces_two_rows(self):
        hist = _history(
            "ABC",
            **{
                "2026-01-01": _day(101, trigger=100, invalidation=98),
                "2026-01-02": _day(104.5),  # target hit, position closes
                "2026-01-05": _day(151, trigger=150, invalidation=147),  # new independent trigger
                "2026-01-06": _day(157.5),  # target = 150+2*3=156
            },
        )
        rows = derive_positions(hist)
        assert len(rows) == 2
        assert rows[0]["trigger_date"] == "2026-01-01"
        assert rows[0]["status"] == "TARGET_HIT"
        assert rows[1]["trigger_date"] == "2026-01-05"
        assert rows[1]["status"] == "TARGET_HIT"


class TestDegenerateAndMissingData:
    def test_degenerate_trigger_equals_invalidation_never_triggers(self):
        hist = _history(
            "ABC",
            **{"2026-01-01": _day(101, trigger=100, invalidation=100)},
        )
        rows = derive_positions(hist)
        assert rows == []

    def test_no_setup_ever_fires_produces_no_positions(self):
        hist = _history(
            "ABC",
            **{"2026-01-01": _day(101), "2026-01-02": _day(102)},
        )
        rows = derive_positions(hist)
        assert rows == []

    def test_missing_playbook_key_on_a_setup_day_is_skipped(self):
        """Older session_history entries compiled before the playbook key
        existed should not crash the derivation."""
        hist = _history(
            "ABC",
            **{"2026-01-01": {"spot_close": 101, "setups": ["GAMMA_SQUEEZE"]}},
        )
        rows = derive_positions(hist)
        assert rows == []

    def test_multiple_symbols_are_independent(self):
        hist = {
            "ABC": {"2026-01-01": _day(101, trigger=100, invalidation=98),
                    "2026-01-02": _day(104.5)},
            "XYZ": {"2026-01-01": _day(50, trigger=49, invalidation=48)},
        }
        rows = derive_positions(hist)
        by_sym = {r["symbol"] for r in rows if r["status"] != "OPEN"}
        assert by_sym == {"ABC"}
        open_syms = {r["symbol"] for r in rows if r["status"] == "OPEN"}
        assert open_syms == {"XYZ"}
