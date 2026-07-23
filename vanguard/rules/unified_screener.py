import os
import duckdb

def run_confluence_filter(db_path: str = "data/compiled/vanguard.duckdb"):
    """
    Applies the strict confluence filter to merge Cash and F&O rules.
    Requires alignment across momentum, breadth, and GEX.
    Outputs to daily_confluence_setups table.
    """
    con = duckdb.connect(db_path)
    try:
        tables = {r[0] for r in con.execute("SHOW TABLES").fetchall()}
        
        # Check prerequisites
        required = {'daily_setups', 'daily_equity_setups', 'daily_market_structure', 'daily_equity_technicals'}
        missing = required - tables
        if missing:
            print(f"[!] Cannot run confluence filter. Missing tables: {missing}")
            return
            
        has_breadth = 'daily_cm_breadth' in tables

        breadth_join = "LEFT JOIN daily_cm_breadth b ON COALESCE(fno.date, eq.date) = b.date" if has_breadth else ""
        breadth_filter = "(b.cm_pct_above_50dma > 0.40 OR b.cm_pct_above_50dma IS NULL)" if has_breadth else "1=1"

        query = f"""
            CREATE OR REPLACE TABLE daily_confluence_setups AS 
            SELECT 
                COALESCE(fno.symbol, eq.symbol) as symbol,
                COALESCE(fno.date, eq.date) as date,
                fno.setup_type as fno_setup,
                eq.setup_type as equity_setup,
                ms.gamma_regime,
                et.roc_5d,
                {"b.cm_pct_above_50dma" if has_breadth else "NULL as cm_pct_above_50dma"},
                ms.spot_change_pct,
                COALESCE(fno.bias, eq.bias) as bias,
                COALESCE(fno.trigger_strike, eq.trigger_strike) as trigger_strike,
                COALESCE(fno.invalidation_strike, eq.invalidation_strike) as invalidation_strike,
                COALESCE(fno.expected_behavior, eq.expected_behavior) as expected_behavior
            FROM daily_setups fno
            FULL OUTER JOIN daily_equity_setups eq 
                ON fno.symbol = eq.symbol AND fno.date = eq.date
            LEFT JOIN daily_market_structure ms 
                ON COALESCE(fno.symbol, eq.symbol) = ms.symbol AND COALESCE(fno.date, eq.date) = ms.date
            LEFT JOIN daily_equity_technicals et 
                ON COALESCE(fno.symbol, eq.symbol) = et.symbol AND COALESCE(fno.date, eq.date) = et.date
            {breadth_join}
            WHERE 
                -- 1. Momentum Confluence (Cash ROC 5d > 0 or FNO Spot Change > 1%)
                (et.roc_5d > 0 OR ms.spot_change_pct > 1.0)
                AND 
                -- 2. Breadth Confluence (More than 40% of cash market above 50DMA)
                {breadth_filter}
                AND 
                -- 3. GEX Alignment 
                (
                    (fno.setup_type IN ('GAMMA_SQUEEZE', 'MOMENTUM_BUILDUP', 'INVENTORY_MIGRATION') AND ms.gamma_regime = 'SHORT_GAMMA') OR
                    (fno.setup_type IN ('FLOOR_BOUNCE', 'DEALER_DEFENSE', 'RSI_EXTREME_REBOUND') AND ms.gamma_regime = 'LONG_GAMMA') OR
                    (fno.setup_type IS NULL AND eq.setup_type IS NOT NULL)
                )
        """
        
        con.execute(query)
        count = con.execute("SELECT count(*) FROM daily_confluence_setups").fetchone()[0]
        print(f"[SUCCESS] Confluence Filter applied. {count} high-conviction setups generated in daily_confluence_setups.")
        
    except Exception as e:
        print(f"[!] Error running confluence filter: {e}")
    finally:
        con.close()

if __name__ == "__main__":
    run_confluence_filter()
