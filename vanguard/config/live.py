"""
Live layer configuration — one place for cadences, universe scoping, paths, and
the Dhan feed constants. Kept separate from vanguard/core/config.py (EOD) so the
realtime layer is self-contained.
"""
from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]

# ── Dhan feed constants (mirror dhanhq.marketfeed) ───────────────────────────
SEG_IDX, SEG_NSE_EQ, SEG_NSE_FNO = 0, 1, 2
MODE_TICKER, MODE_QUOTE, MODE_FULL = 15, 17, 21
WS_MAX_PER_CONN = 5000          # Dhan hard cap per WebSocket connection
WS_MAX_CONN = 5                 # Dhan hard cap on connections per user
WS_MAX_PER_MSG = 100            # instruments per subscribe message

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
TOP_N_LIVE_OPTIONS = 60        # cap live-options names to top-N by OI + indices + armed setups

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
HEARTBEAT_TIMEOUT = 40         # Dhan closes at 40 s silence
STALE_TICK_ALERT = 60          # alert if no tick in market hours for > this

# ── Paths ────────────────────────────────────────────────────────────────────
LIVE_DIR = ROOT / "data" / "live"
INSTRUMENT_MASTER = LIVE_DIR / "instrument_master.parquet"
SNAPSHOT_JSON = LIVE_DIR / "live_snapshot.json"
BRIDGE_HOST, BRIDGE_PORT = "127.0.0.1", 8787
