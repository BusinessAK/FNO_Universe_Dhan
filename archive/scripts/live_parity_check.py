#!/usr/bin/env python3
"""
EOD-parity check (M2's trust gate) — compares the live daemon's last-computed
structure (walls/GEX/IV, from data/live/live_snapshot.json's `structure` field)
for covered symbols against the next EOD compile's actual values for the same
symbols and date. Gates, per the PRD: walls >=90% strike-exact, GEX avg delta
<=15%, IV avg delta <=1 vol point.

Run once daily, ideally right around/after 15:30 while the live daemon (and
therefore live_snapshot.json) is still fresh for the session that's ending —
or any time after that day's EOD compile has run, since the compiled DB
doesn't change again until the next day.

A pass writes data/live/parity_YYYYMMDD.json with "passed": true, which
vanguard/live/snapshot.py's is_structure_validated() checks to clear the HUD's
"INDICATIVE" watermark on live structure going forward.

    python3 scripts/live_parity_check.py                # compare vs the latest compiled date
    python3 scripts/live_parity_check.py 2026-07-16     # compare vs a specific date
"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from vanguard.live import config as C  # noqa: E402

WALL_MATCH_TARGET = 0.90
GEX_DELTA_TARGET = 0.15
IV_DELTA_TARGET_PT = 1.0   # vol points (1 pt = 0.01 in fraction terms)
STRIKE_EPS = 0.01          # float-compare tolerance for "same strike"


def load_live_structure() -> dict:
    if not C.SNAPSHOT_JSON.exists():
        raise FileNotFoundError(
            f"no live snapshot at {C.SNAPSHOT_JSON} — was the daemon running today?")
    snap = json.loads(C.SNAPSHOT_JSON.read_text())
    return snap.get("structure", {})


def load_eod_structure(date: str | None = None) -> tuple[str, dict]:
    import duckdb
    db = ROOT / "data" / "compiled" / "vanguard.duckdb"
    con = duckdb.connect(str(db), read_only=True)
    try:
        if date is None:
            date = con.execute("SELECT MAX(date) FROM daily_market_structure").fetchone()[0]
        rows = con.execute(
            "SELECT symbol, call_wall, put_wall, gex, iv FROM daily_market_structure WHERE date=?",
            [date]).fetchall()
    finally:
        con.close()
    return date, {r[0]: {"call_wall": r[1], "put_wall": r[2], "gex": r[3], "iv": r[4]} for r in rows}


def _close(a, b, eps=STRIKE_EPS) -> bool:
    return abs((a or 0.0) - (b or 0.0)) < eps


def run(date: str | None = None) -> dict:
    live = load_live_structure()
    eod_date, eod = load_eod_structure(date)

    common = sorted(set(live) & set(eod))
    if not common:
        report = {"date": eod_date, "passed": False, "reason": "no overlapping covered symbols",
                   "n_compared": 0}
        _write(report)
        return report

    wall_exact = 0
    gex_deltas, iv_deltas = [], []
    per_symbol = {}
    for sym in common:
        lv, ed = live[sym], eod[sym]
        cw_match = _close(lv.get("call_wall"), ed.get("call_wall"))
        pw_match = _close(lv.get("put_wall"), ed.get("put_wall"))
        if cw_match and pw_match:
            wall_exact += 1

        ed_gex = ed.get("gex") or 0.0
        gex_delta_pct = abs((lv.get("gex", 0.0) or 0.0) - ed_gex) / abs(ed_gex) if ed_gex else None
        if gex_delta_pct is not None:
            gex_deltas.append(gex_delta_pct)

        iv_delta = abs((lv.get("iv_avg", 0.0) or 0.0) - (ed.get("iv") or 0.0))
        iv_deltas.append(iv_delta)

        per_symbol[sym] = {"wall_exact": cw_match and pw_match,
                            "gex_delta_pct": gex_delta_pct, "iv_delta_pt": round(iv_delta * 100, 3)}

    wall_match_pct = wall_exact / len(common)
    gex_delta_avg = sum(gex_deltas) / len(gex_deltas) if gex_deltas else None
    iv_delta_avg = sum(iv_deltas) / len(iv_deltas) if iv_deltas else None

    passed = (
        wall_match_pct >= WALL_MATCH_TARGET
        and (gex_delta_avg is None or gex_delta_avg <= GEX_DELTA_TARGET)
        and (iv_delta_avg is None or iv_delta_avg <= IV_DELTA_TARGET_PT / 100.0)
    )

    report = {
        "date": eod_date, "passed": passed, "n_compared": len(common),
        "wall_match_pct": round(wall_match_pct, 4),
        "gex_delta_avg_pct": round(gex_delta_avg, 4) if gex_delta_avg is not None else None,
        "iv_delta_avg_pt": round(iv_delta_avg * 100, 3) if iv_delta_avg is not None else None,
        "gates": {"wall_match_pct": WALL_MATCH_TARGET, "gex_delta_pct": GEX_DELTA_TARGET,
                  "iv_delta_pt": IV_DELTA_TARGET_PT},
        "per_symbol": per_symbol,
    }
    _write(report)
    return report


def _write(report: dict):
    path = C.LIVE_DIR / f"parity_{report['date'].replace('-', '')}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report, indent=2))
    print(f"[parity] wrote {path}")


if __name__ == "__main__":
    date_arg = sys.argv[1] if len(sys.argv) > 1 else None
    r = run(date_arg)
    verdict = "PASS" if r["passed"] else "FAIL"
    print(f"[parity] {r['date']}: {verdict} — {r['n_compared']} symbols compared, "
          f"wall_match={r.get('wall_match_pct')}, gex_delta_avg_pct={r.get('gex_delta_avg_pct')}, "
          f"iv_delta_avg_pt={r.get('iv_delta_avg_pt')}")
