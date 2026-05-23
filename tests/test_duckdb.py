"""
Tests verifying the integrity, structures, and schemas of the compiled DuckDB database.
"""
import unittest
import os
import duckdb
import pandas as pd

class TestDuckDBEngine(unittest.TestCase):
    def setUp(self):
        self.db_path = "data/compiled/vanguard.duckdb"
        self.assertTrue(os.path.exists(self.db_path), "vanguard.duckdb should exist in data/compiled/")
        self.conn = duckdb.connect(self.db_path)

    def tearDown(self):
        self.conn.close()

    def test_tables_existence(self):
        """Verify that all 5 required institutional tables exist inside vanguard.duckdb."""
        tables_df = self.conn.execute("SHOW TABLES").df()
        self.assertFalse(tables_df.empty, "Database should contain registered tables.")
        
        existing_tables = set(tables_df['name'].tolist())
        required_tables = {
            "daily_market_structure",
            "daily_setups",
            "daily_inventory",
            "daily_market_breadth",
            "daily_changes"
        }
        for table in required_tables:
            self.assertIn(table, existing_tables, f"Required table '{table}' is missing from DuckDB.")

    def test_daily_market_structure_integrity(self):
        """Verify columns and query integrity on the flagship market structure catalog."""
        df = self.conn.execute("SELECT * FROM daily_market_structure LIMIT 5").df()
        self.assertFalse(df.empty, "daily_market_structure table should contain compiled data.")
        
        required_columns = ["symbol", "date", "spot_close", "pcr", "ifs_score", "call_wall", "put_wall", "gamma_flip", "gex", "gamma_regime"]
        for col in required_columns:
            self.assertIn(col, df.columns, f"Column '{col}' is missing in daily_market_structure.")

    def test_daily_setups_integrity(self):
        """Verify the setups and tactical playbook triggers database."""
        df = self.conn.execute("SELECT * FROM daily_setups LIMIT 5").df()
        self.assertFalse(df.empty, "daily_setups table should contain active tactical patterns.")
        
        required_columns = ["symbol", "date", "setup_type", "bias", "trigger_strike", "invalidation_strike", "expected_behavior"]
        for col in required_columns:
            self.assertIn(col, df.columns, f"Column '{col}' is missing in daily_setups.")

    def test_daily_market_breadth_integrity(self):
        """Verify global breadth aggregates database."""
        df = self.conn.execute("SELECT * FROM daily_market_breadth LIMIT 5").df()
        self.assertFalse(df.empty, "daily_market_breadth table should contain historical daily breadth metrics.")
        
        required_columns = ["date", "bullish_pct", "bearish_pct", "compression_pct", "expansion_pct", "total_symbols"]
        for col in required_columns:
            self.assertIn(col, df.columns, f"Column '{col}' is missing in daily_market_breadth.")

if __name__ == '__main__':
    unittest.main()
