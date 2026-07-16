import duckdb
import os
import sys
import pandas as pd

def _clean_dataframe(df: pd.DataFrame, fill_numeric: bool = True) -> pd.DataFrame:
    """
    Cleans a pandas DataFrame fetched from DuckDB:
    - Fills numeric column NaNs/None with appropriate defaults (0 for int, 0.0 for float),
      unless fill_numeric is False — pass False when NaN carries meaning ("no data yet",
      e.g. DMA participation before the rolling window fills) so the UI can render "—"
      instead of a misleading 0.
    - Converts Timestamp/Datetime columns to YYYY-MM-DD string formats.
    - Replaces NaNs in object columns with None.
    """
    if df.empty:
        return df

    df = df.copy()
    for col in df.columns:
        dtype = df[col].dtype
        if pd.api.types.is_datetime64_any_dtype(dtype):
            df[col] = df[col].dt.strftime("%Y-%m-%d")
        elif pd.api.types.is_integer_dtype(dtype):
            if fill_numeric:
                df[col] = df[col].fillna(0)
        elif pd.api.types.is_float_dtype(dtype):
            if fill_numeric:
                df[col] = df[col].fillna(0.0)
        else:
            df[col] = df[col].where(df[col].notna(), None)

    return df

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
        self.conn = duckdb.connect(self.db_path, read_only=True)
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        if self.conn:
            self.conn.close()
            self.conn = None

    def _query(
        self,
        sql: str,
        params: list = None,
        require_table: str = None,
        require_column: tuple = None,
        fill_numeric: bool = True,
    ) -> pd.DataFrame:
        """
        Shared read path: exists-check → connect → optional schema guards →
        execute → clean. Errors are logged (not swallowed silently) and an
        empty DataFrame is returned so the UI degrades gracefully.

        require_table:  table name that must exist (older compiled DBs).
        require_column: (table, column) that must exist.
        """
        if not os.path.exists(self.db_path):
            return pd.DataFrame()
        try:
            with self as db:
                if require_table:
                    tables = db.conn.execute("SHOW TABLES").df()["name"].tolist()
                    if require_table not in tables:
                        return pd.DataFrame()
                if require_column:
                    tbl, col = require_column
                    cols = db.conn.execute(
                        "SELECT column_name FROM information_schema.columns "
                        "WHERE table_name = ?", [tbl]
                    ).df()["column_name"].tolist()
                    if col not in cols:
                        return pd.DataFrame()
                df = db.conn.execute(sql, params or []).df()
                return _clean_dataframe(df, fill_numeric=fill_numeric)
        except Exception as e:
            print(f"[DatabaseService] query failed: {e}", file=sys.stderr)
            return pd.DataFrame()

    def get_market_breadth(self, date: str) -> dict:
        """Loads daily F&O breadth aggregates from compiler table."""
        df = self._query("SELECT * FROM daily_market_breadth WHERE date = ?", [date])
        return df.iloc[0].to_dict() if not df.empty else {}

    def get_cm_breadth(self, date: str) -> dict:
        """Loads daily cash market price breadth from daily_cm_breadth table.

        NaN is preserved: several CM columns are legitimately "no data yet"
        (e.g. %>200-DMA before the window fills) and the panel renders them
        as "—" rather than 0.
        """
        df = self._query(
            "SELECT * FROM daily_cm_breadth WHERE date = ?", [date],
            require_table="daily_cm_breadth", fill_numeric=False,
        )
        return df.iloc[0].to_dict() if not df.empty else {}

    def get_cm_first_date(self) -> str:
        """Returns the first date in daily_cm_breadth (the A/D line anchor date), or ''."""
        df = self._query(
            "SELECT MIN(date) AS date FROM daily_cm_breadth",
            require_table="daily_cm_breadth",
        )
        if df.empty:
            return ""
        return df.iloc[0]["date"] or ""

    def get_daily_changes(self, date: str) -> list:
        """Loads EOD structural change alerts ledger direct from database."""
        df = self._query("SELECT * FROM daily_changes WHERE date = ?", [date])
        return df.to_dict(orient="records") if not df.empty else []

    def get_setups(self, date: str) -> pd.DataFrame:
        """Loads and filters EOD registered setups for a session date."""
        return self._query(
            "SELECT * FROM daily_setups WHERE date = ? AND setup_type != 'NONE'", [date]
        )

    def get_matrix_data(self, search_query: str = "", start_date: str = None) -> pd.DataFrame:
        """Fetches joined market structure and persistence columns for main dashboard matrix."""
        query = """
            SELECT s.*, i.bullish_persistence, i.bearish_persistence
            FROM daily_market_structure s
            LEFT JOIN daily_inventory i
            ON s.symbol = i.symbol AND s.date = i.date
        """
        params = []
        where_clauses = []
        if start_date:
            where_clauses.append("s.date >= ?")
            params.append(start_date)
        if search_query:
            where_clauses.append("UPPER(s.symbol) LIKE ?")
            params.append(f"%{search_query.upper()}%")

        if where_clauses:
            query += " WHERE " + " AND ".join(where_clauses)

        return self._query(query, params)

    def get_structure_flips(self, date: str, min_confidence: float = 0.0) -> pd.DataFrame:
        """
        Returns all confirmed structure flip events for a given session date.
        Filters out NONE flips; results ordered by flip_confidence DESC.

        Columns returned:
            symbol, sector, date, structure_flip, prev_structural_bias,
            structural_bias, flip_confidence, flip_strength,
            spot_close, spot_change_pct, ifs_score, gamma_regime
        """
        return self._query(
            """
            SELECT symbol, sector, date,
                   structure_flip, prev_structural_bias, structural_bias,
                   flip_confidence, flip_strength,
                   spot_close, spot_change_pct, ifs_score, gamma_regime
            FROM daily_market_structure
            WHERE date = ?
              AND structure_flip != 'NONE'
              AND flip_confidence >= ?
            ORDER BY flip_confidence DESC
            """,
            [date, min_confidence],
            require_table="daily_market_structure",
            require_column=("daily_market_structure", "structure_flip"),
        )

    def get_sector_flow(self, date: str) -> pd.DataFrame:
        """Aggregates institutional flow metrics by sector for a specific date."""
        return self._query(
            """
            SELECT
                sector,
                COUNT(symbol) as symbol_count,
                AVG(ifs_score) as avg_ifs,
                SUM(net_inv_shift) as total_net_inv_shift,
                SUM(gex_shift) as total_gex_shift
            FROM daily_market_structure
            WHERE date = ? AND sector IS NOT NULL AND sector != 'Other' AND sector != 'Index'
            GROUP BY sector
            ORDER BY avg_ifs DESC
            """,
            [date],
        )
