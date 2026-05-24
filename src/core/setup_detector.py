from typing import Dict, List, Tuple
from src.config.setup_registry import SETUP_REGISTRY

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
