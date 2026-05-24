import duckdb
import os
import pandas as pd

class DatabaseService:
    """
    Centralized EOD Research Database Service.
    Implements a custom context manager block to manage DuckDB read/write connections cleanly
    and prevent memory and file descriptor locks inside the Streamlit runtime.
    """
    def __init__(self, db_path="data/compiled/vanguard.duckdb"):
        self.db_path = db_path
        self.conn = None

    def __enter__(self):
        self.conn = duckdb.connect(self.db_path)
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        if self.conn:
            self.conn.close()
            self.conn = None

    def get_market_breadth(self, date: str) -> dict:
        """Loads daily breadth aggregates from compiler table."""
        if not os.path.exists(self.db_path):
            return {}
        try:
            with self as db:
                res = db.conn.execute("SELECT * FROM daily_market_breadth WHERE date = ?", [date]).df()
                if not res.empty:
                    return res.iloc[0].to_dict()
        except Exception:
            pass
        return {}

    def get_daily_changes(self, date: str) -> list:
        """Loads EOD structural change alerts ledger direct from database."""
        if not os.path.exists(self.db_path):
            return []
        try:
            with self as db:
                res = db.conn.execute("SELECT * FROM daily_changes WHERE date = ?", [date]).df()
                if not res.empty:
                    return res.to_dict(orient="records")
        except Exception:
            pass
        return []

    def get_setups(self, date: str) -> pd.DataFrame:
        """Loads and filters EOD registered setups for a session date."""
        if not os.path.exists(self.db_path):
            return pd.DataFrame()
        try:
            with self as db:
                return db.conn.execute("SELECT * FROM daily_setups WHERE date = ? AND setup_type != 'NONE'", [date]).df()
        except Exception:
            pass
        return pd.DataFrame()

    def get_matrix_data(self, search_query: str = "") -> pd.DataFrame:
        """Fetches joined market structure and persistence columns for main dashboard matrix."""
        if not os.path.exists(self.db_path):
            return pd.DataFrame()
        try:
            with self as db:
                query = """
                    SELECT s.*, i.bullish_persistence, i.bearish_persistence 
                    FROM daily_market_structure s
                    LEFT JOIN daily_inventory i 
                    ON s.symbol = i.symbol AND s.date = i.date
                """
                if search_query:
                    return db.conn.execute(query + " WHERE UPPER(s.symbol) LIKE ?", [f"%{search_query}%"]).df()
                else:
                    return db.conn.execute(query).df()
        except Exception:
            pass
        return pd.DataFrame()
