# Vanguard Institutional EOD Terminal - Quantitative Setup Metadata Registry
# Governs styling, categories, priorities, and default playbook properties.

SETUP_REGISTRY = {
    "GAMMA_SQUEEZE": {
        "title": "Gamma Squeeze Setup",
        "icon": "🔥",
        "color": "#fca5a5",
        "description": "Dealers delta-buying squeeze breakout above Call Wall",
        "category": "expansion",
        "priority_weight": 0.85,
        "default_bias": "Bullish Breakout"
    },
    "VOLATILITY_COIL": {
        "title": "Volatility Compression Coil",
        "icon": "🌀",
        "color": "#a78bfa",
        "description": "Compressed implied volatility preparing for expansion coil",
        "category": "expansion",
        "priority_weight": 0.90,
        "default_bias": "Neutral"
    },
    "FLOOR_BOUNCE": {
        "title": "Institutional Floor Bounce",
        "icon": "🛡️",
        "color": "#6ee7b7",
        "description": "Spot bouncing off high dealer-defense Put Wall support",
        "category": "defense",
        "priority_weight": 0.75,
        "default_bias": "Bullish Bias"
    },
    "DEALER_DEFENSE": {
        "title": "Dealer Magnet Pin Zone",
        "icon": "🧲",
        "color": "#38bdf8",
        "description": "Spot pinned near maximum straddle dealer-interest concentration",
        "category": "defense",
        "priority_weight": 0.70,
        "default_bias": "Neutral"
    },
    "REGIME_SHIFT": {
        "title": "Gamma Flip Regime Crossover",
        "icon": "🔄",
        "color": "#fbbf24",
        "description": "Regime flip transition crossover from Short to Long Gamma",
        "category": "regime",
        "priority_weight": 0.80,
        "default_bias": "Regime Shift"
    },
    "INVENTORY_MIGRATION": {
        "title": "Institutional Inventory Migration",
        "icon": "📊",
        "color": "#f59e0b",
        "description": "Longitudinal shift in key institutional support and resistance levels",
        "category": "regime",
        "priority_weight": 0.95,
        "default_bias": "Range Shift"
    }
}
