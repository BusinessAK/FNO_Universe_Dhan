import pandas as pd
import numpy as np
import os
from datetime import datetime
from src.intelligence import InstitutionalIntelligence

class SignalGenerator:
    def __init__(self):
        self.intel = InstitutionalIntelligence()

    def generate_signals(self, file_curr, file_prio):
        # 1. Get Base Structural Shifts
        results = self.intel.analyze_market_structure(file_curr, file_prio)
        
        # We don't need strikes anymore, just the raw differences
        # Grab exactly the columns we need for scoring and display
        columns_to_keep = ['SYMBOL', 'SPOT_T', 'SPOT_CHG_PCT', 'GEX_SHIFT', 'CHG_IN_OI_CE_T', 'CHG_IN_OI_PE_T', 'IV_SHIFT', 'CALL_WALL_T', 'PUT_WALL_T', 'GAMMA_FLIP_T']
        
        # Ensure columns exist, if not, fill 0
        for col in columns_to_keep:
            if col not in results.columns:
                results[col] = 0
                
        df_final = results[columns_to_keep].copy().fillna(0)
        
        # Calculate Net Imbalances
        df_final['NET_INV_SHIFT'] = df_final['CHG_IN_OI_PE_T'] - df_final['CHG_IN_OI_CE_T']
        
        # 2. Vanguard Kinetic Score Engine (0-100)
        # We normalize the massive numbers to create a proportional 0-100 score
        # Since ranges change wildly between stocks, we rank them relative to themselves 
        # or cap the extreme outliers.
        
        def calculate_score(row):
            # 1. GEX Shift Score (Max 40)
            # 50 Lakh gamma shift is now massive
            gex_points = min(40, (abs(row['GEX_SHIFT']) / 5e6) * 40)
            
            # 2. Net Inventory Score (Max 30)
            # 50 Lakh (5M) net difference is massive.
            inv_points = min(30, (abs(row['NET_INV_SHIFT']) / 5e6) * 30)
            
            # 3. IV Shift Score (Max 15)
            # IV_SHIFT is in decimal vol units: 0.05 = 5 IV points, a massive
            # day-over-day panic/greed move.
            iv_points = min(15, (abs(row['IV_SHIFT']) / 0.05) * 15)
            
            # 4. Spot Price Shift (Max 15)
            # 4% move confirms a massive breakout.
            spot_points = min(15, (abs(row['SPOT_CHG_PCT']) / 4.0) * 15)
            
            total_score = gex_points + inv_points + iv_points + spot_points
            return round(total_score, 1)

        df_final['SCORE'] = df_final.apply(calculate_score, axis=1)
        
        # Sort Highest to Lowest
        df_final = df_final.sort_values(by='SCORE', ascending=False).reset_index(drop=True)
        df_final['RANK'] = df_final.index + 1
        
        # 3. Formatting for Clean Terminal Display
        df_final['CMP'] = df_final['SPOT_T'].round(2)
        df_final['Δ SPOT %'] = df_final['SPOT_CHG_PCT'].round(2).astype(str) + "%"
        df_final['Δ GEX (Lakhs)'] = (df_final['GEX_SHIFT'] / 1e5).round(2)
        df_final['Δ CALL OI'] = (df_final['CHG_IN_OI_CE_T'] / 100000).round(1).astype(str) + "L"
        df_final['Δ PUT OI'] = (df_final['CHG_IN_OI_PE_T'] / 100000).round(1).astype(str) + "L"
        df_final['Δ IV %'] = (df_final['IV_SHIFT'] * 100).round(2).astype(str) + "%"
        df_final['CALL_WALL'] = df_final['CALL_WALL_T']
        df_final['PUT_WALL'] = df_final['PUT_WALL_T']
        df_final['GAMMA_FLIP'] = df_final['GAMMA_FLIP_T']
        
        final_cols = ['RANK', 'SYMBOL', 'CMP', 'Δ SPOT %', 'Δ GEX (Lakhs)', 'Δ CALL OI', 'Δ PUT OI', 'CALL_WALL', 'PUT_WALL', 'GAMMA_FLIP', 'SCORE']
        
        return df_final[final_cols]

if __name__ == "__main__":
    gen = SignalGenerator()
    file_curr = "data/raw/BhavCopy_NSE_FO_0_0_0_20260515_F_0000.csv"
    file_prio = "data/raw/BhavCopy_NSE_FO_0_0_0_20260514_F_0000.csv"
    
    signals_df = gen.generate_signals(file_curr, file_prio)
    
    print("\n" + "!"*80)
    print("VANGUARD QUANTITATIVE TERMINAL (RANKED BY INSTITUTIONAL SHIFT)")
    print("!"*80)
    
    from tabulate import tabulate
    print(tabulate(signals_df.head(25), headers='keys', tablefmt='psql', showindex=False))
    
    os.makedirs("data/processed", exist_ok=True)
    signals_df.to_csv("data/processed/signals.csv", index=False)

