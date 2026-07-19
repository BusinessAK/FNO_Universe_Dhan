import pandas as pd
from vanguard.models.states import MarketState, SignalState

class SessionCache:
    """
    In-memory Pre-caching & Normalization Service.
    Saves fully constructed, typed state models to prevent heavy UI-level dict operations or
    repeated expensive Dataframe query filtering.
    """
    def __init__(self):
        self._greeks_filtered = {}
        self._signal_state_cache = {}
        self._greeks_token = None

    def get_filtered_greeks(self, greeks_df: pd.DataFrame, symbol: str, token=None) -> pd.DataFrame:
        """Caches filtered greeks slices by symbol to bypass Pandas indexing overhead.

        `token` should change whenever the underlying greeks data changes
        (e.g. the greeks.csv mtime) so long-lived sessions don't serve stale
        slices after an EOD refresh.
        """
        # Token rollover (EOD refresh): drop all slices cached under the old
        # token so a long-lived session doesn't accumulate stale copies.
        if token != self._greeks_token:
            self._greeks_filtered.clear()
            self._greeks_token = token

        cache_key = f"{symbol.upper()}_{token}"
        if cache_key not in self._greeks_filtered:
            sym_key = symbol.upper()
            if not greeks_df.empty and "SYMBOL" in greeks_df.columns:
                self._greeks_filtered[cache_key] = greeks_df[greeks_df["SYMBOL"] == sym_key].copy()
            else:
                self._greeks_filtered[cache_key] = pd.DataFrame()
        return self._greeks_filtered[cache_key]

    def get_normalized_signal(self, symbol: str, date: str, session_history: dict) -> SignalState:
        """Caches and returns normalized SignalState dataclasses from historical session mappings."""
        sym_key = symbol.upper()
        cache_key = f"{sym_key}_{date}"
        if cache_key not in self._signal_state_cache:
            sym_history = session_history.get(sym_key, {})
            day_data = sym_history.get(date, {})
            if day_data:
                self._signal_state_cache[cache_key] = SignalState.from_dict(sym_key, day_data)
            else:
                self._signal_state_cache[cache_key] = SignalState(symbol=sym_key)
        return self._signal_state_cache[cache_key]
