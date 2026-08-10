#!/usr/bin/env python3
"""
Cross-sectional ranking validation — can we rank the F&O universe daily so the
top names outperform the bottom names over the next few sessions?

Proposed for a "Ranked Leaders" HUD section alongside the Symbol Scanner. This
script is the decision gate: it answers whether ANY of the available price /
volume / returns / derivatives fields carry cross-sectional forward-return
signal before a ranking UI is built on top of them.

METHOD
  - Score every factor as a cross-sectional z-score WITHIN each session
    (winsorized +-3). Ranking within the day strips market-wide drift, so we
    measure stock selection rather than accidentally measuring beta.
  - Primary metric is the per-session Spearman rank IC between factor and
    forward return: it uses all ~213 names rather than just the tails.
    Single-session IC has SE ~ 1/sqrt(210) ~ 0.069, far larger than any real
    factor's IC (~0.02-0.05), which is exactly why this runs over all 274
    sessions instead of a handful of days.
  - Every factor tested is reported, including the failures — the point is to
    make cherry-picking visible rather than to surface a winner.

DELIBERATE DEVIATION FROM flip_backtester.attach_forward
  attach_forward reads daily_market_structure.spot_close, which is NOT
  split-adjusted: 17 symbol-days in this DB carry corporate-action gaps as
  large as -50% (ASHOKLEY 2025-07-16, HDFCAMC 2025-11-26, TATAMOTORS
  2025-10-14, ...). Those would enter the study as genuine -50% forward
  returns and dominate every bucket mean. This script uses
  daily_equity_technicals.adj_close instead. Entry/exit timing is otherwise
  identical to the house convention (entry = NEXT session's close, so a signal
  seen at T's close is never traded at T's close).

Otherwise mirrors this repo's existing validation precedent: HOLDS/COST_RT_PCT
from flip_backtester, the 2026-04-01 temporal cutoff and MIN_N=30 per fold
from setup_temporal_holdout.py, and its CONSISTENT / OVERFIT RISK /
INCONCLUSIVE verdict scheme.

Read-only: touches nothing in data/compiled/.

Usage:
    python3 vanguard/research/cross_sectional_rank_backtest.py [--db PATH] [--out DIR]
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import duckdb
import numpy as np
import pandas as pd
from scipy import stats

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

# House conventions (flip_backtester.py)
HOLDS = (1, 3, 5)
PRIMARY_HOLD = 3
COST_RT_PCT = 0.40          # 20 bps per side, round trip

# House conventions (setup_temporal_holdout.py)
CUTOFF = "2026-04-01"       # real regime boundary, not a fitted split point
MIN_N = 30

N_BUCKETS = 10              # deciles
WINSOR = 3.0

# factor -> (family, human label). Sign is NOT pre-imposed; signed IC is
# reported so the direction each factor actually points is visible.
FACTORS: dict[str, tuple[str, str]] = {
    # ── returns ──
    "roc_5d":                   ("Returns", "5d rate of change"),
    "roc_20d":                  ("Returns", "20d rate of change"),
    "roc_63d":                  ("Returns", "63d rate of change"),
    "spot_change_pct":          ("Returns", "1d change %"),
    # ── price ──
    "pct_from_52w_high":        ("Price", "% from 52w high"),
    "pct_from_52w_low":         ("Price", "% from 52w low"),
    "rsi14":                    ("Price", "RSI(14)"),
    "dma20_gap":                ("Price", "close vs 20DMA %"),
    "dma50_gap":                ("Price", "close vs 50DMA %"),
    "natr14":                   ("Price", "normalized ATR(14)"),
    # ── volume ──
    "volume_ratio_20d":         ("Volume", "volume vs 20d avg"),
    "delivery_pct":             ("Volume", "delivery %"),
    "delivery_pct_ratio_20d":   ("Volume", "delivery % vs 20d"),
    "deliverable_vol_ratio_20d":("Volume", "deliverable vol vs 20d"),
    "money_flow_20d":           ("Volume", "20d money flow"),
    # ── derivatives ──
    "futures_oi_chg_pct":       ("Derivatives", "futures OI change %"),
    "pcr":                      ("Derivatives", "put/call ratio"),
    "net_inv_shift":            ("Derivatives", "net inventory shift"),
    "ifs_score":                ("Derivatives", "IFS score"),
    "gex_shift":                ("Derivatives", "GEX shift"),
    "gex_intensity":            ("Derivatives", "GEX intensity"),
    "iv":                       ("Derivatives", "implied vol"),
    "iv_shift":                 ("Derivatives", "IV shift"),
    "iv_rank":                  ("Derivatives", "IV rank"),
    "skew_slope":               ("Derivatives", "skew slope"),
    "conviction_score":         ("Derivatives", "conviction score"),
    "priority_score":           ("Derivatives", "priority score"),
}


def load_frame(db: str) -> pd.DataFrame:
    """Joined market-structure + equity-technicals panel, with split-adjusted
    forward returns attached."""
    con = duckdb.connect(db, read_only=True)
    try:
        df = con.execute("""
            SELECT
                m.symbol, CAST(m.date AS DATE) AS date, m.sector,
                m.spot_close, m.spot_change_pct, m.futures_oi, m.futures_oi_chg,
                m.pcr, m.net_inv_shift, m.ifs_score, m.gex_shift, m.gex_intensity,
                m.iv, m.iv_shift, m.iv_rank, m.skew_slope,
                m.conviction_score, m.priority_score,
                t.adj_close, t.rsi14, t.dma20, t.dma50, t.natr14,
                t.pct_from_52w_high, t.pct_from_52w_low,
                t.volume_ratio_20d, t.money_flow_20d, t.delivery_pct,
                t.delivery_pct_ratio_20d, t.deliverable_vol_ratio_20d,
                t.roc_5d, t.roc_20d, t.roc_63d
            FROM daily_market_structure m
            JOIN daily_equity_technicals t
              ON t.symbol = m.symbol AND CAST(t.date AS DATE) = CAST(m.date AS DATE)
            ORDER BY m.symbol, m.date
        """).df()
    finally:
        con.close()

    # ── derived factors ────────────────────────────────────────────────────
    # raw futures_oi_chg is a contract count; normalize by the symbol's own OI
    # so a large-OI name isn't mechanically ranked above a small-OI one.
    prev_oi = df["futures_oi"] - df["futures_oi_chg"]
    df["futures_oi_chg_pct"] = np.where(
        prev_oi.abs() > 1000, df["futures_oi_chg"] / prev_oi * 100.0, np.nan)
    df["dma20_gap"] = np.where(
        df["dma20"] > 0, (df["adj_close"] - df["dma20"]) / df["dma20"] * 100.0, np.nan)
    df["dma50_gap"] = np.where(
        df["dma50"] > 0, (df["adj_close"] - df["dma50"]) / df["dma50"] * 100.0, np.nan)

    # ── forward returns (split-adjusted; entry = NEXT session close) ────────
    g = df.groupby("symbol", group_keys=False)
    df["entry_close"] = g["adj_close"].shift(-1)
    for h in HOLDS:
        df[f"exit_{h}"] = g["adj_close"].shift(-(h + 1))
        df[f"fwd{h}"] = (df[f"exit_{h}"] - df["entry_close"]) / df["entry_close"] * 100.0
    return df


def zscore_by_session(df: pd.DataFrame, col: str) -> pd.Series:
    """Cross-sectional z-score within each session, winsorized."""
    g = df.groupby("date")[col]
    z = (df[col] - g.transform("mean")) / g.transform("std")
    return z.clip(-WINSOR, WINSOR)


def factor_ic(df: pd.DataFrame, col: str, ret: str) -> dict:
    """Per-session Spearman rank IC between factor and forward return."""
    ics, ns = [], []
    for _, grp in df.groupby("date"):
        sub = grp[[col, ret]].dropna()
        if len(sub) < MIN_N or sub[col].nunique() < 5:
            continue
        ic, _ = stats.spearmanr(sub[col], sub[ret])
        if np.isfinite(ic):
            ics.append(ic)
            ns.append(len(sub))
    if len(ics) < 20:
        return {"n_sessions": len(ics)}
    ics = np.array(ics)
    se = ics.std(ddof=1) / np.sqrt(len(ics))
    return {
        "n_sessions": len(ics),
        "avg_names": int(np.mean(ns)),
        "mean_ic": ics.mean(),
        "t_stat": ics.mean() / se if se > 0 else np.nan,
        "ic_pos_pct": (ics > 0).mean() * 100.0,
    }


def decile_table(df: pd.DataFrame, col: str, ret: str) -> pd.DataFrame:
    """Bucket by within-session decile of the factor; mean forward return each."""
    d = df[[col, ret, "date"]].dropna().copy()
    if d.empty:
        return pd.DataFrame()
    d["bucket"] = d.groupby("date")[col].transform(
        lambda s: pd.qcut(s.rank(method="first"), N_BUCKETS, labels=False, duplicates="drop")
        if s.notna().sum() >= N_BUCKETS * 3 else np.nan)
    d = d.dropna(subset=["bucket"])
    if d.empty:
        return pd.DataFrame()
    out = d.groupby("bucket")[ret].agg(["count", "mean"]).reset_index()
    out.columns = ["bucket", "n", "fwd_pct"]
    return out


def spread_stats(df: pd.DataFrame, col: str, ret: str) -> dict:
    """Long-short decile spread, computed per session then averaged, so the
    t-stat reflects session-to-session variability rather than treating every
    symbol-day as independent."""
    d = df[[col, ret, "date"]].dropna().copy()
    per = []
    for _, grp in d.groupby("date"):
        if len(grp) < N_BUCKETS * 3:
            continue
        r = grp[col].rank(method="first")
        b = pd.qcut(r, N_BUCKETS, labels=False, duplicates="drop")
        top = grp[ret][b == b.max()].mean()
        bot = grp[ret][b == 0].mean()
        if np.isfinite(top) and np.isfinite(bot):
            per.append((top, bot, top - bot))
    if len(per) < 20:
        return {}
    arr = np.array(per)
    sp = arr[:, 2]
    se = sp.std(ddof=1) / np.sqrt(len(sp))
    return {
        "n_sessions": len(sp),
        "top_pct": arr[:, 0].mean(),
        "bot_pct": arr[:, 1].mean(),
        "spread_pct": sp.mean(),
        "spread_t": sp.mean() / se if se > 0 else np.nan,
        "spread_net_pct": sp.mean() - COST_RT_PCT,
    }


def verdict(full: dict, early: dict, late: dict) -> str:
    """CONSISTENT / OVERFIT RISK / INCONCLUSIVE, per setup_temporal_holdout."""
    if not full or not early or not late:
        return "INCONCLUSIVE (n too thin in a fold)"
    if early.get("n_sessions", 0) < MIN_N or late.get("n_sessions", 0) < MIN_N:
        return "INCONCLUSIVE (n too thin in a fold)"
    se, sl = np.sign(early["mean_ic"]), np.sign(late["mean_ic"])
    strong = abs(full.get("t_stat", 0)) >= 2.0
    if se != sl:
        return "**OVERFIT RISK — sign flips between folds**"
    if not strong:
        return "no signal (|t| < 2)"
    return "**CONSISTENT — same sign both folds, |t| >= 2**"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default=str(ROOT / "data" / "compiled" / "vanguard.duckdb"))
    ap.add_argument("--out", default=str(ROOT / "data" / "research"))
    args = ap.parse_args()

    print("[*] loading panel ...")
    df = load_frame(args.db)
    ret = f"fwd{PRIMARY_HOLD}"
    print(f"[*] {len(df):,} symbol-days | {df.date.nunique()} sessions "
          f"| {df.symbol.nunique()} symbols")

    # sanity: adjusted returns should not carry corporate-action cliffs
    extreme = df[df[ret].abs() > 40][ret].count()
    print(f"[*] |fwd{PRIMARY_HOLD}| > 40% rows after adjustment: {extreme}")

    df["_fold"] = np.where(df["date"].astype(str) < CUTOFF, "early", "late")

    rows = []
    for col, (family, label) in FACTORS.items():
        if col not in df.columns:
            print(f"[!] missing column {col} — skipped")
            continue
        z = zscore_by_session(df, col)
        work = df.assign(_z=z)
        full = factor_ic(work, "_z", ret)
        if full.get("mean_ic") is None:
            rows.append({"factor": col, "family": family, "label": label,
                         "verdict": "INCONCLUSIVE (n too thin in a fold)"})
            continue
        early = factor_ic(work[work._fold == "early"], "_z", ret)
        late = factor_ic(work[work._fold == "late"], "_z", ret)
        sp = spread_stats(work, "_z", ret)
        rows.append({
            "factor": col, "family": family, "label": label,
            **{f"full_{k}": v for k, v in full.items()},
            "early_ic": early.get("mean_ic"), "late_ic": late.get("mean_ic"),
            "early_n": early.get("n_sessions"), "late_n": late.get("n_sessions"),
            **{f"sp_{k}": v for k, v in sp.items()},
            "verdict": verdict(full, early, late),
        })
        print(f"    {col:<26} IC={full.get('mean_ic', float('nan')):+.4f} "
              f"t={full.get('t_stat', float('nan')):+.2f}")

    res = pd.DataFrame(rows).sort_values("full_t_stat", key=abs, ascending=False)

    # ── report ─────────────────────────────────────────────────────────────
    out = Path(args.out); out.mkdir(parents=True, exist_ok=True)
    L: list[str] = []
    L.append("# Cross-Sectional Ranking Validation — Can We Rank the F&O Universe?\n")
    L.append(f"Panel: {len(df):,} symbol-days · {df.date.nunique()} sessions "
             f"({df.date.min()} → {df.date.max()}) · {df.symbol.nunique()} symbols  ")
    L.append(f"Scoring: cross-sectional z-score within each session (winsorized ±{WINSOR}) · "
             f"metric: per-session Spearman rank IC vs **fwd{PRIMARY_HOLD}**  ")
    L.append(f"Returns: split-adjusted `adj_close`, entry = NEXT session close · "
             f"holdout cutoff {CUTOFF} · MIN_N={MIN_N} · cost {COST_RT_PCT}% round trip\n")
    L.append("Every factor tested is listed, including failures — this table is the "
             "record of what was tried, so a winner cannot be cherry-picked out of it.\n")

    L.append("## Single-factor IC vs forward 3-day return\n")
    L.append("| Factor | Family | Mean IC | t | IC>0 % | Early IC | Late IC | L/S spread % | net % | Verdict |")
    L.append("|---|---|---:|---:|---:|---:|---:|---:|---:|---|")
    for _, r in res.iterrows():
        if pd.isna(r.get("full_mean_ic")):
            L.append(f"| `{r.factor}` | {r.family} | — | — | — | — | — | — | — | {r.verdict} |")
            continue
        L.append(
            f"| `{r.factor}` | {r.family} | {r.full_mean_ic:+.4f} | {r.full_t_stat:+.2f} | "
            f"{r.full_ic_pos_pct:.0f}% | {r.early_ic:+.4f} | {r.late_ic:+.4f} | "
            f"{r.get('sp_spread_pct', float('nan')):+.3f} | "
            f"{r.get('sp_spread_net_pct', float('nan')):+.3f} | {r.verdict} |")
    L.append("")

    strong = res[(res.full_t_stat.abs() >= 2.0) & (~res.verdict.str.contains("OVERFIT", na=False))]
    L.append("## Factors surviving both gates (|t| ≥ 2 and no sign flip)\n")
    if strong.empty:
        L.append("**None.** No single factor produced a cross-sectionally stable "
                 "forward-3-day signal that held its sign across the "
                 f"{CUTOFF} regime boundary.\n")
    else:
        for _, r in strong.iterrows():
            L.append(f"- `{r.factor}` ({r.label}) — IC {r.full_mean_ic:+.4f}, "
                     f"t {r.full_t_stat:+.2f}, L/S spread {r.get('sp_spread_pct', float('nan')):+.3f}% "
                     f"({r.get('sp_spread_net_pct', float('nan')):+.3f}% net of cost)")
        L.append("")

    # decile monotonicity for the strongest few
    L.append(f"## Decile forward-{PRIMARY_HOLD}d return — strongest factors by |t|\n")
    for _, r in res.head(5).iterrows():
        if pd.isna(r.get("full_mean_ic")):
            continue
        z = zscore_by_session(df, r.factor)
        tbl = decile_table(df.assign(_z=z), "_z", ret)
        if tbl.empty:
            continue
        L.append(f"**`{r.factor}`** ({r.label}) — decile 0 = lowest score, "
                 f"{N_BUCKETS - 1} = highest\n")
        L.append("| decile | " + " | ".join(str(int(b)) for b in tbl.bucket) + " |")
        L.append("|---|" + "---:|" * len(tbl))
        L.append(f"| fwd{PRIMARY_HOLD} % | " + " | ".join(f"{v:+.3f}" for v in tbl.fwd_pct) + " |")
        L.append("")

    L.append("## Reading this table\n")
    L.append(f"- **Mean IC** — average per-session Spearman correlation between the factor "
             f"and the next-3-session return. Single-session IC has SE ≈ 0.069, so only the "
             f"average over {df.date.nunique()} sessions is interpretable; a few days would "
             f"be pure noise.")
    L.append("- **t** — mean IC divided by its standard error across sessions. |t| ≥ 2 is the "
             "minimum bar; it is not proof, and with ~27 factors tested roughly one would "
             "clear |t| ≥ 2 by chance alone.")
    L.append("- **L/S spread** — mean forward return of the top decile minus the bottom "
             "decile, computed per session then averaged. **net** subtracts "
             f"{COST_RT_PCT}% round-trip cost.")
    L.append("- **OVERFIT RISK** — mean IC changes sign between the pre/post-"
             f"{CUTOFF} folds: fitted to one part of the sample, not a stable effect.")
    L.append("")
    L.append(f"Single-regime caveat, same as every prior study here: the whole panel sits "
             f"inside one ~13-month window with one correction and one recovery. Surviving "
             f"both folds is not the same as robust across a full market cycle.")

    path = out / "cross_sectional_rank_backtest.md"
    path.write_text("\n".join(L), encoding="utf-8")
    print(f"\n[*] wrote {path}")

    res.to_csv(out / "cross_sectional_rank_backtest.csv", index=False)
    return 0


if __name__ == "__main__":
    sys.exit(main())
