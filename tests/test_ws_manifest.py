"""
Manifest builder unit tests (TRD_fullmap_live_v1 §2, PRD C1/C2/N6/N10/N11):
coverage math, ATM buffer, armed-chain inclusion, rollover eve, schema-change
abort, unmapped-drift abort, size bounds, and mode assignment (V6: F&O = FULL).
"""
import unittest
from datetime import date

import pandas as pd

from src.live import config as C
from src.live.manifest import build_manifest, ManifestError, select_oi_strikes


class FakeIM:
    """Instrument-master stand-in over a synthetic universe."""

    def __init__(self, df):
        self.df = df

    def expiries(self, underlying):
        m = self.df[(self.df.kind == "OPT") & (self.df.underlying == underlying)]
        return sorted(m.expiry.dropna().unique())

    def option_chain(self, underlying, expiry=None):
        m = self.df[(self.df.kind == "OPT") & (self.df.underlying == underlying)]
        if expiry:
            m = m[m.expiry == expiry]
        return m

    def near_atm(self, underlying, spot, n_strikes=5, expiry=None):
        chain = self.option_chain(underlying, expiry or self.expiries(underlying)[0])
        if chain.empty or spot <= 0:
            return chain
        strikes = sorted(chain.strike.unique())
        atm = min(strikes, key=lambda s: abs(s - spot))
        ai = strikes.index(atm)
        keep = set(strikes[max(0, ai - n_strikes): ai + n_strikes + 1])
        return chain[chain.strike.isin(keep)]

    def spot(self, symbol):
        m = self.df[(self.df.kind.isin(["EQ", "INDEX"])) & (self.df.underlying == symbol)]
        return m.iloc[0].to_dict() if not m.empty else None

    def futures(self, underlying):
        return self.df[(self.df.kind == "FUT") & (self.df.underlying == underlying)]


def make_master(symbols, strikes, expiries=("2026-08-27",)):
    rows = []
    sid = 1000
    for sym in symbols:
        rows.append(dict(security_id=sid, feed_segment=1, kind="EQ", underlying=sym,
                         expiry=None, strike=0.0, option_type=""))
        sid += 1
        rows.append(dict(security_id=sid, feed_segment=2, kind="FUT", underlying=sym,
                         expiry=expiries[0], strike=0.0, option_type=""))
        sid += 1
        for exp in expiries:
            for k in strikes:
                for ot in ("CE", "PE"):
                    rows.append(dict(security_id=sid, feed_segment=2, kind="OPT",
                                     underlying=sym, expiry=exp, strike=float(k),
                                     option_type=ot))
                    sid += 1
    return pd.DataFrame(rows)


def make_bhav(symbols, strikes, oi_fn, expiry="2026-08-27"):
    rows = []
    for sym in symbols:
        for k in strikes:
            for ot in ("CE", "PE"):
                rows.append(dict(TckrSymb=sym, XpryDt=expiry, StrkPric=float(k),
                                 OptnTp=ot, OpnIntrst=oi_fn(sym, k, ot),
                                 ClsPric=5.0, FinInstrmTp="STO"))
    return pd.DataFrame(rows)


# The builder's size bounds are production-scale; shrink them for fixtures.
class BoundsPatch:
    def __enter__(self):
        self.mn, self.mx = C.MANIFEST_MIN, C.MANIFEST_MAX
        C.MANIFEST_MIN, C.MANIFEST_MAX = 1, 10_000
        return self

    def __exit__(self, *a):
        C.MANIFEST_MIN, C.MANIFEST_MAX = self.mn, self.mx


class TestManifestBuilder(unittest.TestCase):
    def setUp(self):
        self.symbols = ["AAA", "BBB"]
        self.strikes = list(range(900, 1101, 25))       # 9 strikes
        self.master = make_master(self.symbols, self.strikes)
        self.im = FakeIM(self.master)
        self.closes = {"AAA": 1000.0, "BBB": 1000.0}
        self.today = date(2026, 7, 16)

    def _bhav(self, oi_fn=None):
        return make_bhav(self.symbols, self.strikes,
                         oi_fn or (lambda s, k, ot: 10000 if abs(k - 1000) <= 50 else 0))

    def test_oi_coverage_selection(self):
        bhav = self._bhav(lambda s, k, ot: {900: 1_000_000, 925: 100}.get(k, 0))
        sel = select_oi_strikes(bhav, set(self.symbols), coverage=0.995)
        # the 900s dominate; the tiny 925s fall outside 99.5%
        self.assertTrue((sel.StrkPric == 900).all())

    def test_buffer_and_modes_and_baseline(self):
        with BoundsPatch():
            mf, report = build_manifest(self._bhav(), self.im, set(self.symbols),
                                        self.closes, set(), self.today)
        # every OI>0 strike mapped, plus zero-OI buffer rows around 1000
        opt = mf[mf.kind == "OPT"]
        self.assertTrue((opt["mode"] == C.MODE_FULL).all(), "options must be FULL (V6)")
        self.assertTrue((mf[mf.kind == "FUT"]["mode"] == C.MODE_FULL).all(),
                        "futures must be FULL (V6)")
        self.assertTrue((mf[mf.kind == "SPOT"]["mode"] == C.MODE_QUOTE).all())
        # buffer picked up the zero-OI wings around ATM with a 0 baseline
        # (a buffer row CAN carry OI if its strike just missed the coverage
        # cutoff — the baseline is always the bhav truth, whatever the reason)
        buf = opt[opt.reason == "atm_buffer"]
        self.assertGreater(len(buf), 0)
        wings = buf[buf.strike.isin([900.0, 1100.0])]
        self.assertGreater(len(wings), 0)
        self.assertTrue((wings.oi_baseline == 0).all())
        # oi_set rows carry the bhav baseline
        oi_set = opt[opt.reason == "oi_set"]
        self.assertTrue((oi_set.oi_baseline > 0).all())
        # spot+fut present for both names
        self.assertEqual(len(mf[mf.kind == "SPOT"]), 2)
        self.assertEqual(len(mf[mf.kind == "FUT"]), 2)
        # no duplicate (seg,sid)
        self.assertEqual(len(mf), mf.groupby(["seg", "sid"]).ngroups)

    def test_armed_symbol_gets_wider_window(self):
        # armed names get +-ARMED_WINDOW strikes (not the full chain: 186/215
        # names arm daily, so full-chain would blow the size bounds). Needs a
        # chain wider than the ATM buffer so the armed window adds NEW strikes.
        strikes = list(range(700, 1301, 25))            # 25 strikes
        master = make_master(self.symbols, strikes)
        im = FakeIM(master)
        bhav = make_bhav(self.symbols, strikes,
                         lambda s, k, ot: 10000 if abs(k - 1000) <= 50 else 0)
        with BoundsPatch():
            mf, _ = build_manifest(bhav, im, set(self.symbols),
                                   self.closes, {"BBB"}, self.today)
        bbb = mf[(mf.symbol == "BBB") & (mf.kind == "OPT")]
        aaa = mf[(mf.symbol == "AAA") & (mf.kind == "OPT")]
        self.assertIn("armed", set(bbb.reason))
        self.assertNotIn("armed", set(aaa.reason))
        self.assertGreater(len(bbb), len(aaa))          # wider window = more strikes

    def test_rollover_eve_adds_next_expiry(self):
        master = make_master(self.symbols, self.strikes,
                             expiries=("2026-07-17", "2026-08-27"))
        im = FakeIM(master)
        bhav = make_bhav(self.symbols, self.strikes,
                         lambda s, k, ot: 1000, expiry="2026-07-17")
        with BoundsPatch():
            mf, _ = build_manifest(bhav, im, set(self.symbols), self.closes,
                                   set(), today=date(2026, 7, 16))
        self.assertIn("rollover", set(mf.reason))
        self.assertIn("2026-08-27", set(mf[mf.kind == "OPT"].expiry))

    def test_schema_change_aborts(self):
        bad = self._bhav().rename(columns={"OpnIntrst": "OpenInterestNew"})
        with BoundsPatch(), self.assertRaises(ManifestError):
            build_manifest(bad, self.im, set(self.symbols), self.closes,
                           set(), self.today)

    def test_unmapped_drift_aborts(self):
        # bhav strikes that don't exist in the master (corporate-action shift)
        bhav = make_bhav(self.symbols, [901, 926, 951, 976],
                         lambda s, k, ot: 10000)
        with BoundsPatch(), self.assertRaises(ManifestError):
            build_manifest(bhav, self.im, set(self.symbols), self.closes,
                           set(), self.today)

    def test_size_bounds_abort(self):
        # production bounds active: a 2-symbol manifest is far below MANIFEST_MIN
        with self.assertRaises(ManifestError):
            build_manifest(self._bhav(), self.im, set(self.symbols),
                           self.closes, set(), self.today)


if __name__ == "__main__":
    unittest.main()
