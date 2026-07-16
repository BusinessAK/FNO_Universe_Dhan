#!/usr/bin/env python3
"""
Structure-flip variant backtester.

Replays flip detection over the compiled DB (no recompile needed) for the
current logic (V0) and four redesign candidates, then evaluates each by
forward directional return so the redesign is chosen by evidence, not taste.

Variants
--------
V0 baseline    : faithful reimplementation of longitudinal.detect_structure_flip.
                 Must reproduce the stored flips — validates this simulator.
V1 confirm2    : a polarity change becomes a flip only after holding 2
                 consecutive sessions; the event fires on the confirmation day.
V2 ema3        : polarity of IFS-dependent biases resolved on a 3-session EMA
                 of IFS instead of the raw daily value.
V3 ema3+pen    : V2 plus a recency penalty — if the symbol flipped within the
                 prior 3 sessions, confidence -25 and strength recomputed.
V4 confirm2+pen: V1 plus the same recency penalty.

Usage:
    python3 src/research/flip_backtester.py [--db PATH] [--out DIR]
"""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

import duckdb
import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from src.core.longitudinal import LongitudinalEngine  # noqa: E402

BULL_BIASES = LongitudinalEngine._BULLISH_BIASES
BEAR_BIASES = LongitudinalEngine._BEARISH_BIASES

HOLDS = (1, 3, 5)
COST_RT_PCT = 0.40          # 20 bps per side, round trip
RECENCY_WINDOW = 3          # sessions
RECENCY_PENALTY = 25.0      # confidence points
EMA_SPAN = 3
CONFIRM_SESSIONS = 2


# ── Data loading ─────────────────────────────────────────────────────────────

def load_frame(db_path: str) -> pd.DataFrame:
    con = duckdb.connect(db_path, read_only=True)
    try:
        df = con.execute("""
            SELECT s.symbol, s.date, s.spot_close, s.spot_change_pct, s.ifs_score,
                   s.structural_bias, s.gamma_regime,
                   s.structure_flip AS stored_flip, s.flip_confidence AS stored_conf,
                   COALESCE(i.bullish_persistence, 0) AS bull_p,
                   COALESCE(i.bearish_persistence, 0) AS bear_p
            FROM daily_market_structure s
            LEFT JOIN daily_inventory i
              ON i.symbol = s.symbol AND i.date = s.date
            ORDER BY s.symbol, s.date
        """).df()
    finally:
        con.close()
    df["date"] = df["date"].astype(str)
    return df


# ── Shared pieces (mirror longitudinal.py exactly) ───────────────────────────

def polarity(bias: str, ifs: float) -> str:
    if bias in BULL_BIASES:
        return "BULLISH"
    if bias in BEAR_BIASES:
        return "BEARISH"
    if ifs > 10:
        return "BULLISH"
    if ifs < -10:
        return "BEARISH"
    return "NEUTRAL"


def confidence(prev: pd.Series, curr: pd.Series, prev_pol: str, flip_type: str) -> float:
    prev_ifs, curr_ifs = float(prev.ifs_score), float(curr.ifs_score)
    ifs_pts = min(40.0, abs(curr_ifs) / 100.0 * 40.0 + (10.0 if prev_ifs * curr_ifs < 0 else 0.0))
    streak = int(prev.bear_p if prev_pol == "BEARISH" else prev.bull_p)
    persist_pts = 25.0 if streak >= 2 else (12.0 if streak == 1 else 0.0)
    regime_ok = (
        (flip_type == "BEARISH_TO_BULLISH" and curr.gamma_regime == "LONG_GAMMA") or
        (flip_type == "BULLISH_TO_BEARISH" and curr.gamma_regime == "SHORT_GAMMA")
    )
    regime_pts = 20.0 if regime_ok else 0.0
    chg = float(curr.spot_change_pct)
    price_ok = (
        (flip_type == "BEARISH_TO_BULLISH" and chg > 0) or
        (flip_type == "BULLISH_TO_BEARISH" and chg < 0)
    )
    price_pts = min(15.0, abs(chg) / 3.0 * 15.0) if price_ok else 0.0
    return round(max(0.0, min(100.0, ifs_pts + persist_pts + regime_pts + price_pts)), 1)


def strength(conf: float) -> str:
    return "STRONG" if conf >= 60.0 else ("MODERATE" if conf >= 35.0 else "WEAK")


# ── Variant simulators (each returns a list of flip-event dicts) ─────────────

def sim_v0(g: pd.DataFrame) -> list:
    """Day-over-day polarity change on raw IFS (current production logic)."""
    events = []
    rows = list(g.itertuples())
    for i in range(1, len(rows)):
        prev, curr = rows[i - 1], rows[i]
        p_pol = polarity(prev.structural_bias, float(prev.ifs_score))
        c_pol = polarity(curr.structural_bias, float(curr.ifs_score))
        if p_pol == c_pol or "NEUTRAL" in (p_pol, c_pol):
            continue
        ft = "BEARISH_TO_BULLISH" if p_pol == "BEARISH" else "BULLISH_TO_BEARISH"
        events.append({"symbol": curr.symbol, "date": curr.date, "flip": ft,
                       "conf": confidence(prev, curr, p_pol, ft)})
    return events


def sim_smoothed(g: pd.DataFrame) -> list:
    """V2: polarity resolved on EMA(span=3) of IFS; flip = day-over-day change."""
    events = []
    rows = list(g.itertuples())
    ema = pd.Series([r.ifs_score for r in rows]).ewm(span=EMA_SPAN, adjust=False).mean().tolist()
    for i in range(1, len(rows)):
        prev, curr = rows[i - 1], rows[i]
        p_pol = polarity(prev.structural_bias, ema[i - 1])
        c_pol = polarity(curr.structural_bias, ema[i])
        if p_pol == c_pol or "NEUTRAL" in (p_pol, c_pol):
            continue
        ft = "BEARISH_TO_BULLISH" if p_pol == "BEARISH" else "BULLISH_TO_BEARISH"
        events.append({"symbol": curr.symbol, "date": curr.date, "flip": ft,
                       "conf": confidence(prev, curr, p_pol, ft)})
    return events


def sim_confirm(g: pd.DataFrame) -> list:
    """V1: new polarity must hold CONFIRM_SESSIONS consecutive sessions;
    the flip event fires on the confirmation day against the last
    confirmed state."""
    events = []
    rows = list(g.itertuples())
    pols = [polarity(r.structural_bias, float(r.ifs_score)) for r in rows]
    state = None       # last confirmed polarity
    for i, r in enumerate(rows):
        if pols[i] == "NEUTRAL":
            continue
        if state is None:
            # seed with the first polarity that holds the confirmation window
            if i + 1 < len(pols) and all(p == pols[i] for p in pols[i:i + CONFIRM_SESSIONS]):
                state = pols[i]
            continue
        if pols[i] != state:
            held = i - CONFIRM_SESSIONS + 1 >= 0 and all(
                pols[j] == pols[i] for j in range(i - CONFIRM_SESSIONS + 1, i + 1))
            if held:
                ft = "BEARISH_TO_BULLISH" if state == "BEARISH" else "BULLISH_TO_BEARISH"
                events.append({"symbol": r.symbol, "date": r.date, "flip": ft,
                               "conf": confidence(rows[i - 1], r, state, ft)})
                state = pols[i]
    return events


def apply_recency_penalty(events: list, dates_by_symbol: dict) -> list:
    """Subtract RECENCY_PENALTY from confidence when the same symbol has a flip
    event within the prior RECENCY_WINDOW sessions (within this event stream)."""
    out = []
    by_sym: dict = {}
    for e in events:
        by_sym.setdefault(e["symbol"], []).append(e)
    for sym, evs in by_sym.items():
        idx = {d: i for i, d in enumerate(dates_by_symbol[sym])}
        evs.sort(key=lambda e: e["date"])
        for j, e in enumerate(evs):
            pen = 0.0
            for k in range(j - 1, -1, -1):
                if idx[e["date"]] - idx[evs[k]["date"]] <= RECENCY_WINDOW:
                    pen = RECENCY_PENALTY
                    break
                break
            out.append({**e, "conf": round(max(0.0, e["conf"] - pen), 1), "penalized": pen > 0})
    return out


# ── Evaluation ───────────────────────────────────────────────────────────────

def attach_forward(events: pd.DataFrame, frame: pd.DataFrame) -> pd.DataFrame:
    """Entry = next-session close; exits at +1/+3/+5 sessions after entry."""
    px = frame[["symbol", "date", "spot_close"]].sort_values(["symbol", "date"]).copy()
    grouped = px.groupby("symbol", group_keys=False)
    px["entry_close"] = grouped["spot_close"].shift(-1)
    for h in HOLDS:
        px[f"exit_{h}"] = grouped["spot_close"].shift(-(h + 1))
    return events.merge(px.drop(columns=["spot_close"]), on=["symbol", "date"], how="left")


def evaluate(events: list, frame: pd.DataFrame, dates_by_symbol: dict, name: str) -> dict:
    ev = pd.DataFrame(events)
    n_days = frame["date"].nunique()
    if ev.empty:
        return {"name": name, "n": 0}
    ev["strength"] = ev["conf"].map(strength)
    ev["dir"] = np.where(ev["flip"] == "BEARISH_TO_BULLISH", 1.0, -1.0)
    # whipsaw share within the event stream
    whip = 0
    for sym, grp in ev.groupby("symbol"):
        idx = {d: i for i, d in enumerate(dates_by_symbol[sym])}
        pos = sorted(idx[d] for d in grp["date"])
        whip += sum(1 for a, b in zip(pos, pos[1:]) if b - a <= RECENCY_WINDOW)
    ev = attach_forward(ev, frame)
    for h in HOLDS:
        ev[f"fwd{h}"] = ev["dir"] * (ev[f"exit_{h}"] - ev["entry_close"]) / ev["entry_close"] * 100.0
    valid = ev.dropna(subset=["entry_close", f"exit_{max(HOLDS)}"])
    rows = []
    for s in ["STRONG", "MODERATE", "WEAK"]:
        sub = valid[valid["strength"] == s]
        if sub.empty:
            continue
        rows.append({
            "strength": s, "n": len(sub),
            **{f"fwd{h}_pct": round(sub[f"fwd{h}"].mean(), 3) for h in HOLDS},
            "fwd3_net_pct": round(sub["fwd3"].mean() - COST_RT_PCT, 3),
            "hit3_pct": round((sub["fwd3"] > 0).mean() * 100, 1),
        })
    return {
        "name": name, "n": len(ev), "per_day": round(len(ev) / n_days, 1),
        "whipsaw_pct": round(whip / len(ev) * 100, 1),
        "strong_n": int((ev["strength"] == "STRONG").sum()),
        "buckets": pd.DataFrame(rows), "events": ev,
    }


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default=str(ROOT / "data" / "compiled" / "vanguard.duckdb"))
    ap.add_argument("--out", default=str(ROOT / "data" / "research"))
    args = ap.parse_args()

    frame = load_frame(args.db)
    dates_by_symbol = {s: list(g["date"]) for s, g in frame.groupby("symbol")}
    groups = {s: g.reset_index(drop=True) for s, g in frame.groupby("symbol")}

    def run(fn):
        evs = []
        for g in groups.values():
            evs.extend(fn(g))
        return evs

    v0 = run(sim_v0)
    v1 = run(sim_confirm)
    v2 = run(sim_smoothed)
    v3 = apply_recency_penalty(v2, dates_by_symbol)
    v4 = apply_recency_penalty(v1, dates_by_symbol)

    # ── V0 validation against stored flips ──────────────────────────────────
    stored = frame[frame["stored_flip"] != "NONE"][["symbol", "date", "stored_flip", "stored_conf"]]
    sim0 = pd.DataFrame(v0)
    merged = stored.merge(sim0, on=["symbol", "date"], how="outer", indicator=True)
    only_stored = (merged["_merge"] == "left_only").sum()
    only_sim = (merged["_merge"] == "right_only").sum()
    both = merged[merged["_merge"] == "both"]
    conf_mismatch = (abs(both["stored_conf"] - both["conf"]) > 0.15).sum()
    print(f"[V0 validation] stored={len(stored)} simulated={len(sim0)} "
          f"missing={only_stored} extra={only_sim} conf_mismatch={conf_mismatch}")

    results = [
        evaluate(v0, frame, dates_by_symbol, "V0 baseline"),
        evaluate(v1, frame, dates_by_symbol, "V1 confirm2"),
        evaluate(v2, frame, dates_by_symbol, "V2 ema3"),
        evaluate(v3, frame, dates_by_symbol, "V3 ema3+penalty"),
        evaluate(v4, frame, dates_by_symbol, "V4 confirm2+penalty"),
    ]

    # ── Report ───────────────────────────────────────────────────────────────
    os.makedirs(args.out, exist_ok=True)
    lines = ["# Structure-Flip Variant Backtest", "",
             f"Universe: {frame['symbol'].nunique()} symbols · {frame['date'].nunique()} sessions "
             f"({frame['date'].min()} → {frame['date'].max()})",
             f"Entry: next-session close · returns are directional (flip direction) · "
             f"net = gross − {COST_RT_PCT}% round trip", "",
             f"V0 validation vs stored DB flips: {len(stored)} stored / {len(sim0)} simulated, "
             f"{only_stored} missing, {only_sim} extra, {conf_mismatch} confidence mismatches", ""]
    for r in results:
        lines += [f"## {r['name']}", "",
                  f"- events: **{r['n']}** ({r['per_day']}/day) · STRONG: {r['strong_n']} · "
                  f"whipsaw share: **{r['whipsaw_pct']}%**", ""]
        b = r["buckets"]
        lines += ["| strength | n | fwd1 % | fwd3 % | fwd5 % | fwd3 net % | hit3 % |",
                  "|---|---|---|---|---|---|---|"]
        for _, row in b.iterrows():
            lines.append(f"| {row['strength']} | {row['n']} | {row['fwd1_pct']} | {row['fwd3_pct']} "
                         f"| {row['fwd5_pct']} | {row['fwd3_net_pct']} | {row['hit3_pct']} |")
        lines.append("")

    report = Path(args.out) / "flip_backtest_report.md"
    report.write_text("\n".join(lines))
    for r in results:
        if r["n"]:
            r["events"].drop(columns=[c for c in r["events"].columns if c.startswith("exit_")]) \
                .to_csv(Path(args.out) / f"flip_events_{r['name'].split()[0].lower()}.csv", index=False)
    print(f"report → {report}")
    print()
    for r in results:
        print(f"=== {r['name']}: {r['n']} events ({r['per_day']}/day), "
              f"whipsaw {r['whipsaw_pct']}%, strong {r['strong_n']} ===")
        if r["n"]:
            print(r["buckets"].to_string(index=False))
        print()


if __name__ == "__main__":
    main()
