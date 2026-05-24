import pandas as pd
from src.models.states import MarketState, SignalState

class SessionCache:
    """
    In-memory Pre-caching & Normalization Service.
    Saves fully constructed, typed state models to prevent heavy UI-level dict operations or
    repeated expensive Dataframe query filtering.
    """
    def __init__(self):
        self._greeks_filtered = {}
        self._signal_state_cache = {}

    def get_filtered_greeks(self, greeks_df: pd.DataFrame, symbol: str) -> pd.DataFrame:
        """Caches filtered greeks slices by symbol to bypass Pandas indexing overhead."""
        sym_key = symbol.upper()
        if sym_key not in self._greeks_filtered:
            if not greeks_df.empty and "SYMBOL" in greeks_df.columns:
                self._greeks_filtered[sym_key] = greeks_df[greeks_df["SYMBOL"] == sym_key].copy()
            else:
                self._greeks_filtered[sym_key] = pd.DataFrame()
        return self._greeks_filtered[sym_key]

    def get_normalized_signal(self, symbol: str, date: str, session_history: dict) -> SignalState:
        """Caches and returns normalized SignalState dataclasses from historical session mappings."""
        cache_key = f"{symbol.upper()}_{date}"
        if cache_key not in self._signal_state_cache:
            sym_history = session_history.get(symbol, {})
            day_data = sym_history.get(date, {})
            if day_data:
                self._signal_state_cache[cache_key] = SignalState.from_dict(symbol, day_data)
            else:
                self._signal_state_cache[cache_key] = SignalState(symbol=symbol)
        return self._signal_state_cache[cache_key]
