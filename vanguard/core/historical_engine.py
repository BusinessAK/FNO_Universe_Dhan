class HistoricalSessionResolver:
    """
    Decoupled Historical Time-Travel Session & Compatibility Resolver.
    Determines is_historical modes, Greeks ledger fallback flags, and chart rendering warnings.
    """
    def __init__(self, latest_trading_date: str):
        self.latest_trading_date = latest_trading_date

    def is_historical(self, active_date: str) -> bool:
        """Determines if the session date is a historical, time-travel date."""
        return active_date != self.latest_trading_date

    def can_render_chain_charts(self, active_date: str) -> bool:
        """Only the latest active EOD session has dynamic Greeks Profile, Concentration, and Skew charts."""
        return not self.is_historical(active_date)

    def can_render_greeks_ledger(self, active_date: str) -> bool:
        """Only the latest session has dynamic Greeks Ledgers, others display historical EOD metrics panels."""
        return not self.is_historical(active_date)

    def get_session_warning(self, active_date: str) -> str:
        """Returns visual warnings if viewing an offline historical session."""
        if self.is_historical(active_date):
            return "⚠️ Option chain GEX profile, OI concentration, and Greeks skew charts are only available for the latest active trading session. Chronological metrics, wall migrations, and historical setups are fully accessible for this date."
        return ""
