#!/usr/bin/env python3
"""
HUD parity referee. Loads the deck in headless Chromium, reads the raw
pre-format numbers every draw function records in window.__VG_CHECK__, and
compares them against an INDEPENDENT recomputation from DuckDB. A UI test that
checks the DOM against the payload JSON is circular — this one re-derives the
answers from the store, so it catches bugs in the export layer and the JS
render layer alike (same referee pattern as live-vs-EOD parity).

Also exercises the machinery the screenshots never covered: time travel two
sessions back, the positioning fut/opt toggle, sector 1w/1m horizons, and a
dossier open.

    python3 scripts/verify_hud.py                    # bridge at :8787, latest session
    python3 scripts/verify_hud.py --url file://$PWD/hud/vanguard_hud.html
    python3 scripts/verify_hud.py --headed           # watch it run

Exit 0 = all green. Exit 1 = mismatch (nightly chain should alert).
Nightly slot: poll_eod -> daily_compiler -> build_hud -> verify_hud.
"""
import argparse
import math
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import duckdb                                        # noqa: E402
import pandas as pd                                  # noqa: E402

from vanguard.config.paths import DB                 # noqa: E402
from vanguard.config.sectors import get_sector       # noqa: E402
from vanguard.store.export_service import FLIP_REPEAT_LOOKBACK  # noqa: E402

PARTS = ["FII", "DII", "PRO", "CLIENT"]
jround = lambda x: math.floor(x + 0.5)               # JS Math.round, not banker's


class Oracle:
    """Recomputes every panel's numbers straight from DuckDB."""

    def __init__(self, con, n_sessions=30):
        self.con = con
        rows = con.execute(
            "SELECT DISTINCT date FROM daily_market_structure "
            "ORDER BY date DESC LIMIT ?", [n_sessions]).fetchall()
        self.sessions = sorted(str(r[0])[:10] for r in rows)
        # full export-window MS frame once; per-session slices come from it
        self.ms = con.execute(
            "SELECT date, symbol, sector, gamma_regime, structural_bias, "
            "COALESCE(pcr,0) AS pcr, COALESCE(spot_change_pct,0) AS chg, "
            "structure_flip, flip_strength "
            "FROM daily_market_structure WHERE date >= ? ORDER BY date",
            [self.sessions[0]]).df()
        self.ms["date"] = self.ms["date"].astype(str).str[:10]
        # export_service.clean() rounds every float to 6dp before it reaches
        # the payload (payload size, not precision loss by intent). Folding
        # 5-21 already-rounded numbers vs full-precision DB values drifts
        # past our 1e-6 tolerance by session 21 — replicate the rounding so
        # the oracle compounds exactly what the browser compounds.
        self.ms["chg"] = self.ms["chg"].round(6)
        # export-time sector remap: mapping wins unless it says "Other"
        self.ms["sec"] = [
            m if (m := get_sector(sym)) != "Other" else (raw or "UNMAPPED")
            for sym, raw in zip(self.ms.symbol, self.ms.sector)]

    def _one(self, sql, params):
        r = self.con.execute(sql, params).fetchone()
        return r if r else None

    def track_record_n(self) -> int:
        """Not time-travel dependent (aggregates over ALL resolved history,
        same as vanguard/research/position_stats.summarize_by_group), so
        checked once, outside the per-session loop. Independently re-derived
        via COUNT(DISTINCT setup_type) rather than importing summarize_by_
        group itself — catches a bug in that shared function too, not just
        in the export/render layers."""
        tables = {r[0] for r in self.con.execute("SHOW TABLES").fetchall()}
        total = 0
        for tbl in ("daily_setup_positions", "daily_equity_setup_positions"):
            if tbl not in tables:
                continue
            total += self._one(
                f"SELECT COUNT(DISTINCT setup_type) FROM {tbl} "
                "WHERE resolved_price IS NOT NULL", [])[0]
        return total

    def expected(self, sdate: str) -> dict:
        con, S = self.con, self.sessions
        cur = self.ms[self.ms.date == sdate]
        exp = {"session": sdate}

        exp["cmdbar"] = {
            "universe": len(cur),
            "pcr_mu": float(cur.pcr.mean()) if len(cur) else 0.0,
            "gamma": cur.gamma_regime.value_counts().to_dict(),
        }
        gm = cur.gamma_regime.value_counts()
        exp["regime"] = {
            "long_gamma": int(gm.get("LONG_GAMMA", 0)),
            "transition": int(gm.get("TRANSITION_REGIME", 0)),
            "short_gamma": int(gm.get("SHORT_GAMMA", 0)),
            "bias": cur.structural_bias.value_counts().to_dict(),
        }

        # VIX: last-252 window (matches export LIMIT 252), percentile over ALL
        # 252 closes, value at the latest row at-or-before the session
        vix = con.execute(
            "SELECT date, close, chg_pct FROM ("
            "  SELECT date, close, chg_pct FROM daily_index_close "
            "  WHERE upper(index_name)='INDIA VIX' ORDER BY date DESC LIMIT 252"
            ") ORDER BY date").df()
        vix["date"] = vix["date"].astype(str).str[:10]
        vv = vix[vix.date <= sdate]
        if len(vv):
            v = vv.iloc[-1]
            exp["vix"] = {
                "date": v.date, "close": float(v.close),
                "chg_pct": None if pd.isna(v.chg_pct) else float(v.chg_pct),
                "pctile": jround((vix.close <= v.close).sum() * 100 / len(vix)),
            }

        b = self._one(
            "SELECT COALESCE(bullish_pct,0)-COALESCE(bearish_pct,0), "
            "COALESCE(compression_pct,0) FROM daily_market_breadth WHERE date=?",
            [sdate])
        if b:
            exp["breadth"] = {"date": sdate, "net": b[0], "coil": b[1]}

        cm = self._one(
            "SELECT date, cm_ad_ratio, cm_net_advances, cm_pct_above_50dma, "
            "cm_pct_above_200dma, COALESCE(cm_new_highs,0), COALESCE(cm_new_lows,0), "
            "cm_mcclellan_osc FROM daily_cm_breadth WHERE date<=? "
            "ORDER BY date DESC LIMIT 1", [sdate])
        cash = con.execute(
            "SELECT category, net_cr, date FROM daily_fii_dii "
            "WHERE date=(SELECT MAX(date) FROM daily_fii_dii WHERE date<=?)",
            [sdate]).fetchall()
        cashd = {c: n for c, n, _ in cash}
        if cm:
            exp["internals"] = {
                "date": str(cm[0])[:10], "ad_ratio": cm[1], "net_advances": cm[2],
                "p50": cm[3], "p200": cm[4], "nh": cm[5], "nl": cm[6],
                "mcclellan": cm[7],
                "cash_date": str(cash[0][2])[:10] if cash else None,
                "fii_cash": cashd.get("FII"), "dii_cash": cashd.get("DII"),
            }

        pos = con.execute(
            "SELECT participant, fut_idx_long-fut_idx_short, "
            "opt_idx_call_long-opt_idx_call_short, opt_idx_put_long-opt_idx_put_short "
            "FROM daily_participant_oi "
            "WHERE date=(SELECT MAX(date) FROM daily_participant_oi WHERE date<=?)",
            [sdate]).fetchall()
        pdate = self._one(
            "SELECT MAX(date) FROM daily_participant_oi WHERE date<=?", [sdate])
        if pos:
            by = {p: (f, c, q) for p, f, c, q in pos}
            exp["positioning"] = {
                "date": str(pdate[0])[:10],
                "fut": {p: by[p][0] for p in PARTS},
                "calls": {p: by[p][1] for p in PARTS},
                "puts": {p: by[p][2] for p in PARTS},
                "fii_tilt": by["FII"][1] - by["FII"][2],
            }

        exp["sectors"] = {h: self.sectors(sdate, h) for h in ("1D", "1W", "1M")}

        flips = cur[cur.structure_flip.notna() & (cur.structure_flip != "NONE")]
        exp["flips"] = {
            "n": len(flips),
            "strong": int((flips.flip_strength == "STRONG").sum()),
            "repeat": self._flip_repeats(flips, sdate),
        }

        by_type = {t: int(n) for t, n in con.execute(
            "SELECT type, COUNT(*) FROM daily_changes WHERE date=? GROUP BY type",
            [sdate]).fetchall()}
        si = S.index(sdate) if sdate in S else -1
        if si > 0:
            bans = lambda d: {r[0] for r in con.execute(
                "SELECT symbol FROM daily_ban WHERE date=?", [d]).fetchall()}
            p, c = bans(S[si - 1]), bans(sdate)
            if c - p:
                by_type["ban_enter"] = len(c - p)
            if p - c:
                by_type["ban_exit"] = len(p - c)
        exp["signals"] = {"n": sum(by_type.values()), "by_type": by_type}

        # Setup Queue now tracks position lifecycle (vanguard/rules/
        # setup_positions.py), not raw daily_setups rows: "active" means
        # triggered and not yet resolved as of sdate, tracked from its
        # original trigger date. Mirrors the point-in-time filter
        # drawSetups() applies client-side in hud/template.html.
        exp["setups"] = {"n": self._one(
            "SELECT COUNT(*) FROM daily_setup_positions "
            "WHERE trigger_date <= ? AND (resolved_date IS NULL OR resolved_date >= ?)",
            [sdate, sdate])[0]}
        exp["scan"] = self.scan(sdate, "1D")
        return exp

    HZ_SESSIONS = {"1D": 1, "1W": 5, "1M": 21}

    def _per_symbol_return(self, sdate, horizon):
        """Compound each symbol's daily spot_change_pct over the trailing
        window ending at sdate — mirrors hud/template.html's symbolReturn(),
        the one function both the Sector Flow Grid and the Scanner Δ%
        toggle call, so this single oracle method covers both panels."""
        hn = self.HZ_SESSIONS[horizon]
        S = self.sessions
        si = S.index(sdate)
        win = S[max(0, si - hn + 1): si + 1]
        cur = self.ms[self.ms.date == sdate]
        if hn == 1:
            per_sym = cur.set_index("symbol").chg
        else:
            # Sequential fold in date-ascending order — must match JS's
            # forEach compounding bit-for-bit. numpy's .prod() reduces in a
            # different internal order and drifts past our 1e-6 tolerance
            # after ~20 chained multiplications: real float non-associativity,
            # not a data bug, so the fix is matching order, not loosening tol.
            hist = self.ms[self.ms.date.isin(win) & self.ms.symbol.isin(cur.symbol)]
            def fold(c):
                g = 1.0
                for v in c:
                    g *= 1 + v / 100
                return (g - 1) * 100
            per_sym = hist.groupby("symbol", sort=False).chg.apply(fold)
        return per_sym, win, cur

    def sectors(self, sdate, horizon):
        per_sym, win, cur = self._per_symbol_return(sdate, horizon)
        df = cur[["symbol", "sec"]].merge(
            per_sym.rename("ret"), left_on="symbol", right_index=True)
        g = df.groupby("sec").ret
        return {"horizon": horizon, "win": len(win),
                "avg": g.mean().to_dict(), "n": g.size().astype(int).to_dict()}

    def scan(self, sdate, horizon):
        per_sym, win, cur = self._per_symbol_return(sdate, horizon)
        return {"shown": len(cur), "total": len(cur), "horizon": horizon,
                "win": len(win), "chg": per_sym.reindex(cur.symbol).to_dict()}

    def _flip_repeats(self, flips, sdate) -> int:
        """Mirror export_service.add_flip_repeat exactly: lookback window is
        anchored at the LATEST exported session, indices over distinct dates."""
        latest = self.sessions[-1]
        window = sorted(str(r[0])[:10] for r in self.con.execute(
            "SELECT DISTINCT date FROM daily_market_structure WHERE date<=? "
            "ORDER BY date DESC LIMIT ?",
            [latest, len(self.sessions) + FLIP_REPEAT_LOOKBACK]).fetchall())
        order = {d: i for i, d in enumerate(window)}
        flipped = {(sym, order[str(d)[:10]]) for sym, d in self.con.execute(
            "SELECT symbol, date FROM daily_market_structure "
            "WHERE structure_flip IS NOT NULL AND structure_flip!='NONE' AND date<=?",
            [latest]).fetchall() if str(d)[:10] in order}
        i = order.get(sdate)
        if i is None:
            return 0
        return sum(
            1 for sym in flips.symbol
            if any((sym, i - k) in flipped for k in range(1, FLIP_REPEAT_LOOKBACK + 1)))


# ── comparison ──────────────────────────────────────────────────────────────

def close(e, g, tol=1e-6):
    if e is None or g is None:
        return e is None and g is None
    if isinstance(e, bool) or isinstance(g, bool):
        return e == g
    if isinstance(e, (int, float)) and isinstance(g, (int, float)):
        return math.isclose(float(e), float(g), rel_tol=1e-9, abs_tol=tol)
    return e == g


def diff(path, e, g, out):
    """Walk expected; every expected leaf must match. Extra keys in got are
    fine (mode, cosmetics) — missing ones are failures."""
    if isinstance(e, dict):
        if not isinstance(g, dict):
            out.append((path, e, g, False))
            return
        for k in sorted(e):
            diff(f"{path}.{k}", e[k], g.get(k), out)
    else:
        out.append((path, e, g, close(e, g)))


def check(label, exp, got, failures):
    out = []
    diff(label, exp, got, out)
    bad = [(p, e, g) for p, e, g, ok in out if not ok]
    failures.extend(bad)
    print(f"  {'PASS' if not bad else 'FAIL'}  {label}  ({len(out)} values)")
    for p, e, g in bad:
        print(f"        {p}: expected {e!r}  got {g!r}")


# ── driver ──────────────────────────────────────────────────────────────────

def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", default="http://127.0.0.1:8787/")
    ap.add_argument("--headed", action="store_true")
    args = ap.parse_args()

    from playwright.sync_api import sync_playwright

    con = duckdb.connect(str(DB), read_only=True)
    ref = Oracle(con)
    latest = ref.sessions[-1]
    failures = []

    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=not args.headed)
        page = browser.new_page(viewport={"width": 1720, "height": 1100})
        page.goto(args.url)
        page.wait_for_function("window.__VG_CHECK__ && window.__VG_CHECK__.session")

        # session list on the deck must equal the oracle's derivation
        opts = page.eval_on_selector_all("#d-sel option", "els=>els.map(e=>e.value)")
        check("meta.sessions", ref.sessions, sorted(opts), failures)

        def registry():
            return page.evaluate("window.__VG_CHECK__")

        def assert_session(sdate, label):
            print(f"[{label}] session {sdate}")
            chk, exp = registry(), ref.expected(sdate)
            for panel in ("session", "cmdbar", "regime", "vix", "breadth",
                          "internals", "positioning", "flips", "signals",
                          "setups", "scan"):
                if panel in exp:
                    check(panel, exp[panel], chk.get(panel), failures)
            check("sectors", exp["sectors"][chk["sectors"]["horizon"]],
                  chk["sectors"], failures)

        # 1) latest session, default state
        assert_session(latest, "latest")

        # Track Record panel — default "both" track filter, not session-
        # dependent (aggregates over all resolved history).
        check("trackRecord", {"n": ref.track_record_n(), "track": "both"},
              registry().get("trackRecord"), failures)

        # DOM sanity: the numbers made it to screen
        exp = ref.expected(latest)
        cb = page.inner_text("#cb-count")
        if not cb.startswith(str(exp["cmdbar"]["universe"])):
            failures.append(("dom.#cb-count", exp["cmdbar"]["universe"], cb))
        cm = page.inner_text("#cm-tiles")
        if f"{exp['internals']['ad_ratio']:.2f}" not in cm:
            failures.append(("dom.#cm-tiles A/D", f"{exp['internals']['ad_ratio']:.2f}", cm[:80]))
        ntiles = page.locator("#pos-tiles .tile").count()
        nopt = page.locator("#pos-opt-tiles .tile").count()
        if (ntiles, nopt) != (4, 4):
            failures.append(("dom.positioning tiles", (4, 4), (ntiles, nopt)))
        nsec = page.locator(".sec-tile").count()
        if nsec != len(exp["sectors"]["1D"]["avg"]):
            failures.append(("dom.sector tiles", len(exp["sectors"]["1D"]["avg"]), nsec))
        print(f"  DOM sanity: cmdbar/internals/positioning/sectors "
              f"{'PASS' if not any(str(f[0]).startswith('dom.') for f in failures) else 'FAIL'}")

        # 2) sector horizons at the latest session
        for hz in ("1W", "1M", "1D"):
            page.click(f'#sec-chips .chip[data-hz="{hz}"]')
            page.wait_for_function(
                "h => window.__VG_CHECK__.sectors.horizon===h", arg=hz)
            check(f"sectors[{hz}]", ref.sectors(latest, hz),
                  registry()["sectors"], failures)

        # 2b) scanner Δ% horizon toggle — same win/compounding math as
        # sectors, applied per-symbol; also exercises the sort comparator
        # since default sortKey is priority_score, not Δ%
        for hz in ("1W", "1M", "1D"):
            page.click(f'#scan-hz-chips .chip[data-hz="{hz}"]')
            page.wait_for_function(
                "h => window.__VG_CHECK__.scan.horizon===h", arg=hz)
            check(f"scan[{hz}]", ref.scan(latest, hz), registry()["scan"], failures)
            hdr, want = page.inner_text("#scan thead"), (f"Δ% {hz}" if hz != "1D" else "Δ%")
            if want not in hdr:
                failures.append((f"dom.#scan thead[{hz}]", want, hdr[:120]))

        # 3) positioning fut/opt toggle
        page.click('#pos-chips .chip[data-pm="OPT"]')
        page.wait_for_function("window.__VG_CHECK__.positioning.mode==='OPT'")
        if "tilt" not in page.inner_text("#pos-cap"):
            failures.append(("dom.#pos-cap", "…tilt…", page.inner_text("#pos-cap")))
        print("  PASS  positioning opt-tilt toggle")
        page.click('#pos-chips .chip[data-pm="FUT"]')

        # 4) dossier: first scanner card opens with the right symbol + date
        sym = page.get_attribute("#scan tbody tr", "data-sym")
        page.click("#scan tbody tr")
        page.wait_for_function(
            "s => document.querySelector('#dss-sym').textContent===s", arg=sym)
        badge = page.inner_text("#dss-date").lower()
        d = pd.Timestamp(latest)
        if f"{d.day:02d} {d.strftime('%b').lower()}" not in badge:
            failures.append(("dom.#dss-date", latest, badge))
        print(f"  PASS  dossier open ({sym})")
        page.keyboard.press("Escape")

        # 5) time travel: two sessions back, full re-assert
        back = ref.sessions[-3]
        page.select_option("#d-sel", back)
        page.wait_for_function(
            "d => window.__VG_CHECK__.session===d", arg=back)
        assert_session(back, "time-travel")

        browser.close()
    con.close()

    print()
    if failures:
        print(f"✗ {len(failures)} mismatch(es) — the deck does NOT match the store")
        return 1
    print("✓ every rendered number re-derived independently from DuckDB — deck is faithful")
    return 0


if __name__ == "__main__":
    sys.exit(main())
