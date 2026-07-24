"""
Live layer configuration — one place for cadences, universe scoping, paths, and
the feed constants. Kept separate from vanguard/core/config.py (EOD) so the
realtime layer is self-contained.
"""
from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]

# ── Feed constants ────────────────────────────────────────────────────────
# SEG_*/MODE_* are a holdover from the Dhan integration (dhanhq.marketfeed
# segment/mode codes) — nothing in the Fyers path reads them (feed_handler._key
# always uses seg=0), kept only because subscription_mgr's manifest tuples
# still carry a mode slot for shape-compatibility with the old caller sites.
SEG_IDX, SEG_NSE_EQ, SEG_NSE_FNO = 0, 1, 2
MODE_TICKER, MODE_QUOTE, MODE_FULL = 15, 17, 21
# WS_MAX_PER_CONN mirrors Fyers' OWN enforced cap (SDK-verified: fyers_apiv3's
# FyersDataSocket.subscribe() rejects a subscription once
# len(symbol_token)+len(new_symbols) > 5000) — not a leftover Dhan number, it
# just happens to match Dhan's old cap too. Only ONE connection is actually
# opened today (scripts/run_live.py passes the whole tape to one FeedHandler);
# WS_MAX_CONN / pack_connections() describe a multi-connection mode that isn't
# wired up yet, so the live tape's real ceiling right now is WS_MAX_PER_CONN,
# full stop — see the MANIFEST_MAX guard in scripts/run_live.py.
WS_MAX_PER_CONN = 5000
WS_MAX_CONN = 5                 # unused until multi-connection packing is wired up
WS_MAX_PER_MSG = 100            # unused: FyersDataSocket.subscribe() does its own 1500-sized batching internally

# ── Cadences (seconds) ───────────────────────────────────────────────────────
COMPUTE_CADENCE = 30            # live_compute pass (walls/GEX/IV) — OI ~3-min floored anyway
FLOW_CADENCE = 60              # session-flow display metrics
SNAPSHOT_CADENCE = 5           # bridge JSON refresh (HUD polls at this rate)
CHAIN_SWEEP_INTERVAL = 3.0     # Option-Chain REST: 1 request / 3 s (token bucket)
TICK_FLUSH_SECS = 5            # tick journal flush interval

# ── Universe scoping (T-Live) ────────────────────────────────────────────────
STRIKE_WINDOW = 12             # ±strikes around ATM (front expiry) for live options
STRIKE_WINDOW_INDEX = 20       # wider for dense weekly index chains
RECENTER_DRIFT = 0.5           # re-center window when spot drifts > this * window width
# Live options coverage is scoped to Nifty50 constituents (vanguard.live.
# universe.get_nifty50_constituents(), NSE-fetched + cached daily) + every
# index, via live_compute.select_covered_names() — not an OI-ranked cutoff
# anymore. Measured at ~2,978 instruments at full strike depth, comfortably
# inside the single-connection WS_MAX_PER_CONN=5000 ceiling (see run_live.py's
# check_ws_budget), with no need to narrow STRIKE_WINDOW or cap by OI.
# Growing coverage past Nifty50 (e.g. to the full 215-name F&O universe,
# measured at ~11,000 instruments full-depth) would blow that budget and
# needs either narrower strike windows or multi-connection packing — don't
# assume today's headroom still holds without re-measuring.

# ── Full-map manifest (TRD_fullmap_live_v1 §2) ───────────────────────────────
OI_COVERAGE = 0.995            # strikes covering this share of prior-day total OI
OI_COVERAGE_FALLBACK = 0.99    # one retry at this coverage if the manifest overflows
ATM_BUFFER = 5                 # ±zero-OI strikes around prior close per name
ARMED_WINDOW = 12              # ±strikes for armed-setup names (NOT full chain —
                               # 186/215 names arm daily, "armed" is not a hot list)
MANIFEST_MIN = 8000            # below this the map is suspiciously small (N11)
MANIFEST_MAX = 15000           # above this we won't fit 3 conns comfortably

INDEX_SYMBOLS = ["NIFTY", "BANKNIFTY", "FINNIFTY", "MIDCPNIFTY", "NIFTYNXT50"]

# ── Market hours (IST) ───────────────────────────────────────────────────────
SESSION_OPEN = (9, 15)         # 09:15
SESSION_CLOSE = (15, 30)       # 15:30
DAEMON_START = (9, 10)         # warm up before open
DAEMON_STOP = (15, 35)         # parity handoff after close
HEARTBEAT_TIMEOUT = 40         # inherited from the Dhan integration — not re-verified against Fyers' actual idle-close behavior
STALE_TICK_ALERT = 60          # alert if no tick in market hours for > this
# "Is this LIVE badge honest" threshold — 3 missed snapshot writes at
# SNAPSHOT_CADENCE. Mirrored by hand as LIVE_STALE_SECS in hud/template.html
# (a baked static file, can't import this module) — keep both at 15 if you
# change this.
LIVE_STALE_SECS = 15

# ── Paths ────────────────────────────────────────────────────────────────────
LIVE_DIR = ROOT / "data" / "live"
INSTRUMENT_MASTER = LIVE_DIR / "instrument_master.parquet"
SNAPSHOT_JSON = LIVE_DIR / "live_snapshot.json"
BRIDGE_HOST, BRIDGE_PORT = "127.0.0.1", 8787

# C3 ban-arming gate: "exclude" (never arm banned symbols) | "annotate"
BAN_ARMING = "exclude"
