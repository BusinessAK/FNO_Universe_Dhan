import pandas as pd

from vanguard.research.position_stats import compute_r_multiple, summarize_by_group


def _row(direction, trigger, sl, resolved=None):
    return pd.Series({"direction": direction, "trigger_price": trigger,
                      "sl_price": sl, "resolved_price": resolved})


def test_up_target_hit_is_positive_two_r():
    r = compute_r_multiple(_row("up", trigger=100, sl=90, resolved=120))
    assert r == 2.0


def test_up_sl_hit_is_negative_one_r():
    r = compute_r_multiple(_row("up", trigger=100, sl=90, resolved=90))
    assert r == -1.0


def test_down_target_hit_is_positive():
    r = compute_r_multiple(_row("down", trigger=100, sl=110, resolved=80))
    assert r == 2.0


def test_open_position_has_no_r():
    assert compute_r_multiple(_row("up", trigger=100, sl=90, resolved=None)) is None


def test_zero_risk_has_no_r():
    assert compute_r_multiple(_row("up", trigger=100, sl=100, resolved=110)) is None


def test_summarize_by_group():
    df = pd.DataFrame([
        {"setup_type": "A", "direction": "up", "trigger_price": 100, "sl_price": 90, "resolved_price": 120},
        {"setup_type": "A", "direction": "up", "trigger_price": 100, "sl_price": 90, "resolved_price": 90},
        {"setup_type": "B", "direction": "up", "trigger_price": 50, "sl_price": 45, "resolved_price": None},
    ])
    g = summarize_by_group(df)
    assert g.loc["A", "n"] == 2
    assert g.loc["A", "win_rate"] == 50.0
    assert g.loc["A", "avg_r"] == 0.5
    assert "B" not in g.index   # only OPEN row, no resolved R -> excluded entirely
