import pandas as pd
import os
from src.processor import DataProcessor
from src.greeks_engine import GreeksEngine
from src.analyzer import GammaAnalyzer

def compare_days(file_current, file_prior):
    print(f"[*] Comparing {os.path.basename(file_current)} vs {os.path.basename(file_prior)}")
    
    processor = DataProcessor()
    engine = GreeksEngine()
    
    # Process both days
    def get_summary(file_path):
        df, _ = processor.normalize(file_path)
        spots = processor.get_spot_prices(df)
        lots = processor.get_lot_sizes(df)
        
        # Limit to top 100 for comparison speed
        top_symbols = df.groupby('SYMBOL')['OPEN_INT'].sum().sort_values(ascending=False).head(100).index
        df_filtered = df[df['SYMBOL'].isin(top_symbols)]
        
        greeks = engine.process_dataframe(df_filtered, spots)
        analyzer = GammaAnalyzer(lot_sizes=lots)
        summary = analyzer.calculate_gex(greeks, spots)
        return summary, spots

    sum_curr, spots_curr = get_summary(file_current)
    sum_prio, spots_prio = get_summary(file_prior)
    
    # Merge for comparison
    merged = pd.merge(sum_curr, sum_prio, on='SYMBOL', suffixes=('_T', '_T-1'))
    
    # Calculate Deltas
    merged['OI_CHANGE_ABS'] = merged['OPEN_INT_T'] - merged['OPEN_INT_T-1']
    merged['OI_CHANGE_PCT'] = (merged['OI_CHANGE_ABS'] / merged['OPEN_INT_T-1']) * 100
    merged['GEX_SHIFT'] = merged['GEX_T'] - merged['GEX_T-1']
    
    # Spot Price Change
    merged['PRICE_T'] = merged['SYMBOL'].map(spots_curr)
    merged['PRICE_T-1'] = merged['SYMBOL'].map(spots_prio)
    merged['PRICE_CHG_PCT'] = ((merged['PRICE_T'] - merged['PRICE_T-1']) / merged['PRICE_T-1']) * 100
    
    # Ranking by OI Accumulation and GEX Shift
    # "Inventory Building" = High OI Change + High GEX Shift
    merged = merged.sort_values(by='OI_CHANGE_ABS', ascending=False)
    
    return merged

if __name__ == "__main__":
    file_curr = "data/raw/BhavCopy_NSE_FO_0_0_0_20260515_F_0000.csv"
    file_prio = "data/raw/BhavCopy_NSE_FO_0_0_0_20260514_F_0000.csv"
    
    comparison = compare_days(file_curr, file_prio)
    
    print("\n=== INVENTORY SHIFT ANALYSIS (T vs T-1) ===")
    print(comparison[['SYMBOL', 'PRICE_CHG_PCT', 'OI_CHANGE_PCT', 'GEX_SHIFT']].head(20))
    
    # Save comparison
    os.makedirs("data/processed", exist_ok=True)
    comparison.to_csv("data/processed/inventory_comparison.csv", index=False)
