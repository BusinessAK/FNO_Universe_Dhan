from typing import Dict, List, Tuple

# Centralized data-driven Setup Registry containing visual styling and EOD definitions
SETUP_REGISTRY = {
    "GAMMA_SQUEEZE": {
        "title": "Gamma Squeeze Setup",
        "icon": "🔥",
        "color": "#fca5a5",
        "description": "Dealers delta-buying squeeze breakout above Call Wall",
        "category": "expansion"
    },
    "VOLATILITY_COIL": {
        "title": "Volatility Compression Coil",
        "icon": "🌀",
        "color": "#a78bfa",
        "description": "Compressed implied volatility preparing for expansion coil",
        "category": "expansion"
    },
    "FLOOR_BOUNCE": {
        "title": "Institutional Floor Bounce",
        "icon": "🛡️",
        "color": "#6ee7b7",
        "description": "Spot bouncing off high dealer-defense Put Wall support",
        "category": "defense"
    },
    "DEALER_DEFENSE": {
        "title": "Dealer Magnet Pin Zone",
        "icon": "🧲",
        "color": "#38bdf8",
        "description": "Spot pinned near maximum straddle dealer-interest concentration",
        "category": "defense"
    },
    "REGIME_SHIFT": {
        "title": "Gamma Flip Regime Crossover",
        "icon": "🔄",
        "color": "#fbbf24",
        "description": "Regime flip transition crossover from Short to Long Gamma",
        "category": "regime"
    },
    "INVENTORY_MIGRATION": {
        "title": "Dealer Support Floor Migration",
        "icon": "🚀",
        "color": "#f59e0b",
        "description": "Upward migration and reinforcement of institutional support walls",
        "category": "regime"
    }
}

class SetupEngine:
    """
    Decoupled Setup Detection & Orchestration Engine.
    Identifies, registers, and sorts tiered setups dynamically using a config-driven registry.
    """
    def __init__(self, registry: dict = SETUP_REGISTRY):
        self.registry = registry

    def scan_setups(self, session_history: dict, all_symbols: list, latest_date: str) -> Dict[str, List[Tuple[str, dict]]]:
        """
        Scans all symbols EOD records for setup triggers and groups them by their category.
        """
        candidates = {
            "expansion": [],  # Tier 1: Gamma Squeeze, Volatility Coil
            "defense": [],    # Tier 2: Floor Bounce, Dealer Defense
            "regime": []      # Tier 3: Regime Shift, Inventory Migration
        }

        for sym in all_symbols:
            metrics = session_history.get(sym, {}).get(latest_date, {})
            if not metrics:
                continue

            setups = metrics.get("setups", [])
            for s_type in setups:
                if s_type in self.registry:
                    cfg = self.registry[s_type]
                    cat = cfg["category"]
                    candidates[cat].append((sym, s_type, metrics))

        # Deduplicate, sort by absolute IFS score in descending order, and group by active setup type
        categorized_sorted = {
            "GAMMA_SQUEEZE": [],
            "VOLATILITY_COIL": [],
            "FLOOR_BOUNCE": [],
            "DEALER_DEFENSE": [],
            "REGIME_SHIFT": [],
            "INVENTORY_MIGRATION": []
        }

        for cat, items in candidates.items():
            # Sort by absolute IFS score
            sorted_items = sorted(items, key=lambda x: abs(x[2].get("ifs_score", 0.0)), reverse=True)
            for sym, s_type, metrics in sorted_items:
                categorized_sorted[s_type].append((sym, metrics))

        return categorized_sorted
