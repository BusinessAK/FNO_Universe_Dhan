"""
Vanguard Institutional Terminal - Centralized Configuration & Styling Settings
"""
from datetime import timezone, timedelta

# Risk-free rate for Greeks calculations
RISK_FREE_RATE = 0.07

# Timezone
IST = timezone(timedelta(hours=5, minutes=30))

# Standard Colors Palette
C = {
    "call": "#58a6ff",
    "put": "#f85149",
    "cmp": "#fbbf24",
    "flip": "#a78bfa",
    "net_pos": "#10b981",
    "net_neg": "#ef4444",
    "bg": "#03030c",
    "bg2": "#080816",
    "grid": "#141435",
    "zero": "#2a3a5a",
    "text": "#c0ccdd"
}

# Standard Plotly Layout parameters
PB = {
    "plot_bgcolor": C["bg2"],
    "paper_bgcolor": C["bg"],
    "font": {
        "color": C["text"],
        "family": "JetBrains Mono",
        "size": 10
    },
    "margin": {
        "l": 15,
        "r": 15,
        "t": 40,
        "b": 15
    }
}

# Threshold limits
BULLISH_THRESHOLD = 60
BEARISH_THRESHOLD = -60

# Narrative templates
NARRATIVE_BULL_PERSISTENCE = "Persistent <b>Put Writing floor support</b> observed for {days} consecutive sessions, signaling heavy institutional accumulation."
NARRATIVE_BEAR_PERSISTENCE = "Aggressive <b>Call Writing reinforcement</b> observed for {days} consecutive sessions, indicating heavy dealer ceiling pressure."
NARRATIVE_MILD_BULL = "Mild bullish Put writing bias observed for {days} session{plural} as dealer support starts to firm up."
NARRATIVE_MILD_BEAR = "Mild bearish Call writing pressure noted for {days} session{plural} as ceiling limits near term rallies."
NARRATIVE_ROTATIONAL = "Active rotational flow and neutral inventory shifts observed, indicating structural compression."

NARRATIVE_ABOVE_CALL_WALL = "Spot accepts <b>above the Call Wall</b> (₹{cw:,.1f}), forcing dealers into short covering (gamma squeeze) buying cascades."
NARRATIVE_NEAR_CALL_WALL = "Spot compresses just below the Call Wall (₹{cw:,.1f}). A breakout above this level could accelerate dealer buying."
NARRATIVE_NEAR_PUT_WALL = "Spot hovers near the major Put Wall support (₹{pw:,.1f}), serving as a strong institutional floor."
NARRATIVE_CHANNEL = "Spot is currently trading in a well-defined channel between dealer walls (Call Wall: ₹{cw:,.0f} | Put Wall: ₹{pw:,.0f})."

NARRATIVE_LONG_GAMMA = "Dealer positioning is in <b>Positive (Long) Gamma</b>. Volatility remains suppressed, favoring mean-reversion buying on dips."
NARRATIVE_SHORT_GAMMA = "Dealer positioning is in <b>Negative (Short) Gamma</b>. Delta-hedging moves accelerate volatility; expect highly expanded price swings."
NARRATIVE_REGIME_FLIP = "Spot sits directly in the <b>Regime Flip Zone</b> (₹{gf:,.0f}), indicating an active regime transition."
