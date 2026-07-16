# Shared constants for Vanguard System

INDEX_SYMBOLS = ["NIFTY", "BANKNIFTY", "FINNIFTY", "MIDCPNIFTY", "NIFTYNXT50"]

# Shared lookback for all trend/time-series displays (~3 months of sessions):
# HUD breadth waveform, HUD cash internals (McClellan, A/D line), and the
# deep-dive chronology charts. The HUD template mirrors this as a JS constant
# (TREND_WINDOW in hud/template.html) — keep the two in sync.
TREND_WINDOW_SESSIONS = 60

# Single source of truth for setup precedence. When multiple setups fire on
# one symbol/day, this order picks the primary type AND the playbook built for
# it — the two must never diverge (they did historically: daily_setups rows
# could pair a FLOOR_BOUNCE label with an INVENTORY_MIGRATION playbook).
SETUP_PRIORITY = [
    "GAMMA_SQUEEZE", "FLOOR_BOUNCE", "DEALER_DEFENSE", "PINCH_ZONE",
    "VOLATILITY_COIL", "INVENTORY_MIGRATION", "REGIME_SHIFT",
    "IV_SPIKE", "IV_CRUSH", "IV_SKEW_ACCUMULATION",
]

# Minimum day-over-day wall shift (max of |Δput_wall%|, |Δcall_wall%|) for
# INVENTORY_MIGRATION to fire. Walls jump in whole strike intervals, so any-change
# triggering fired on 32% of all symbol-days; 2.0% sits near the 25th percentile
# of observed shift magnitudes (2.44 / 3.7 / 5.45 / 7.5 at p25/50/75/90) and
# trims the weakest ~16% of signals. Tune with src/research/swing_backtester.py.
MIN_WALL_MIGRATION_PCT = 2.0

# |gex_intensity| needed to call a dealer pin zone (DEALER_DEFENSE setup and the
# classifier's "Dealer Controlled" branch). The legacy value of 75 was unreachable
# (95th percentile of qualifying rows is ~29) — it fired once in 258 sessions.
# 25 ≈ 90th percentile of LONG_GAMMA near-flip rows.
GEX_INTENSITY_PIN_THRESHOLD = 25.0
