import pandas as pd
import numpy as np
import os
from src.processor import DataProcessor
from src.greeks_engine import GreeksEngine
from src.analyzer import GammaAnalyzer

class InstitutionalIntelligence:
    def __init__(self):
        self.processor = DataProcessor()
        self.engine = GreeksEngine()

    def analyze_market_structure(self, file_t, file_t_minus_1):
        print(f"[*] Deep Dive Analysis: {os.path.basename(file_t)} vs {os.path.basename(file_t_minus_1)}")
        
        # 1. Get Base Data
        df_t, df_fut_t = self.processor.normalize(file_t)
        df_tm1, df_fut_tm1 = self.processor.normalize(file_t_minus_1)
        
        spots_t = self.processor.get_spot_prices(df_t)
        spots_tm1 = self.processor.get_spot_prices(df_tm1)
        lots = self.processor.get_lot_sizes(df_t)

        # 2. Process ALL Symbols (Remove artificial top 50 cap)
        top_symbols = df_t.groupby('SYMBOL')['OPEN_INT'].sum().sort_values(ascending=False).index
        
        # 3. Process Greeks for both days
        greeks_t = self.engine.process_dataframe(df_t[df_t['SYMBOL'].isin(top_symbols)], spots_t)
        greeks_tm1 = self.engine.process_dataframe(df_tm1[df_tm1['SYMBOL'].isin(top_symbols)], spots_tm1)

        # 4. Detailed Interpretation (Call/Put breakdown)
        def get_detailed_metrics(df_greeks, spots):
            summary = df_greeks.groupby(['SYMBOL', 'OPTION_TYP']).agg({
                'OPEN_INT': 'sum',
                'CHG_IN_OI': 'sum',
                'VOLUME': 'sum',
                'IV': 'mean',
                'GAMMA': 'sum',
                'CLOSE': 'mean' # Avg option price
            }).unstack()
            # Flatten columns: ('OPEN_INT', 'CE'), ('OPEN_INT', 'PE')
            summary.columns = [f"{c[0]}_{c[1]}" for c in summary.columns]
            return summary

        metrics_t = get_detailed_metrics(greeks_t, spots_t)
        metrics_tm1 = get_detailed_metrics(greeks_tm1, spots_tm1)
        
        # 4b. Find Structural Walls and Gamma Flip
        structural_data = []
        for symbol, group in df_t.groupby('SYMBOL'):
            ce_group = group[group['OPTION_TYP'] == 'CE']
            pe_group = group[group['OPTION_TYP'] == 'PE']
            
            max_ce = ce_group.loc[ce_group['OPEN_INT'].idxmax()]['STRIKE_PR'] if not ce_group.empty else 0
            max_pe = pe_group.loc[pe_group['OPEN_INT'].idxmax()]['STRIKE_PR'] if not pe_group.empty else 0
            
            # True Gamma Flip Proxy (The Straddle Pin / Battleground)
            # This is the strike that maximizes min(Call OI, Put OI). 
            # It finds the exact strike where BOTH bulls and bears have the largest simultaneous conviction,
            # which forces dealers to actively delta-hedge both sides (the true Gamma pivot).
            # The old OI-based Gamma Flip calculation has been removed.
            # Gamma Flip is now calculated at the end of the pipeline using actual GEX (Dealer Risk).
            structural_data.append({
                'SYMBOL': symbol,
                'CALL_WALL_T': max_ce,
                'PUT_WALL_T': max_pe
            })
            
        df_walls = pd.DataFrame(structural_data)
        metrics_t = pd.merge(metrics_t.reset_index(), df_walls, on='SYMBOL').set_index('SYMBOL')



        # 5. Merge and Compare
        final = pd.merge(metrics_t, metrics_tm1, on='SYMBOL', suffixes=('_T', '_TM1'))
        
        # Add Spot Price Info
        final['SPOT_T'] = final.index.map(spots_t)
        final['SPOT_TM1'] = final.index.map(spots_tm1)
        final['SPOT_CHG_PCT'] = ((final['SPOT_T'] - final['SPOT_TM1']) / final['SPOT_TM1']) * 100

        # --- INVENTORY IMBALANCE METRICS ---
        # 1. PCR Calculation (Put OI / Call OI)
        final['PCR_T'] = final['OPEN_INT_PE_T'] / final['OPEN_INT_CE_T'].replace(0, 1)
        final['PCR_TM1'] = final['OPEN_INT_PE_TM1'] / final['OPEN_INT_CE_TM1'].replace(0, 1)
        final['PCR_SHIFT'] = final['PCR_T'] - final['PCR_TM1']
        
        # 2. Net Bullish Inventory Addition (Put OI added - Call OI added)
        final['NET_BULL_INV_SHIFT'] = final['CHG_IN_OI_PE_T'] - final['CHG_IN_OI_CE_T']

        # 6. Interpretation Logic
        def interpret(row):
            price_chg = row['SPOT_CHG_PCT']
            
            # CE Interpretation
            ce_oi_chg = row['OPEN_INT_CE_T'] - row['OPEN_INT_CE_TM1']
            if price_chg > 0.5 and ce_oi_chg > 0: ce_interp = "Call Buying (Long Build-up)"
            elif price_chg < -0.5 and ce_oi_chg > 0: ce_interp = "Call Writing (Short Build-up)"
            elif price_chg > 0.5 and ce_oi_chg < 0: ce_interp = "Short Covering"
            else: ce_interp = "Neutral / Unwinding"

            # PE Interpretation
            pe_oi_chg = row['OPEN_INT_PE_T'] - row['OPEN_INT_PE_TM1']
            if price_chg < -0.5 and pe_oi_chg > 0: pe_interp = "Put Buying (Long Build-up)"
            elif price_chg > 0.5 and pe_oi_chg > 0: pe_interp = "Put Writing (Short Build-up)"
            elif price_chg < -0.5 and pe_oi_chg < 0: pe_interp = "Short Covering"
            else: pe_interp = "Neutral / Unwinding"

            return ce_interp, pe_interp

        final[['CE_INTERP', 'PE_INTERP']] = final.apply(lambda r: pd.Series(interpret(r)), axis=1)

        # 7. Gamma Structure Change
        analyzer = GammaAnalyzer(lot_sizes=lots)
        gex_t = analyzer.calculate_gex(greeks_t, spots_t)
        gex_tm1 = analyzer.calculate_gex(greeks_tm1, spots_tm1)
        
        final = pd.merge(final, gex_t[['SYMBOL', 'GEX', 'GEX_INTENSITY']], left_index=True, right_on='SYMBOL')
        final = pd.merge(final, gex_tm1[['SYMBOL', 'GEX']], on='SYMBOL', suffixes=('_T', '_TM1'))
        final['GEX_SHIFT'] = final['GEX_T'] - final['GEX_TM1']
        
        # Calculate IV Shift
        final['IV_T'] = final[['IV_CE_T', 'IV_PE_T']].mean(axis=1)
        final['IV_TM1'] = final[['IV_CE_TM1', 'IV_PE_TM1']].mean(axis=1)
        final['IV_SHIFT'] = final['IV_T'] - final['IV_TM1']

        # 8. Strategy Suggestion Logic
        def suggest_strategy(row):
            # Iron Condor: High GEX Intensity (Pinned), Neutral OI
            if abs(row['GEX_INTENSITY']) > 100 and abs(row['SPOT_CHG_PCT']) < 0.5:
                return "Iron Condor / Short Straddle (Range Bound)"
            
            # Long Options: High Negative GEX shift + High OI Surge
            if row['GEX_SHIFT'] < -1e8 and abs(row['SPOT_CHG_PCT']) > 1.0:
                return "Option Buying (Momentum / Squeeze)"
            
            # Bull Put Spread: Price Up + Put Writing
            if row['SPOT_CHG_PCT'] > 0.5 and "Put Writing" in row['PE_INTERP']:
                return "Bull Put Spread (Credit)"
                
            # Bear Call Spread: Price Down + Call Writing
            if row['SPOT_CHG_PCT'] < -0.5 and "Call Writing" in row['CE_INTERP']:
                return "Bear Call Spread (Credit)"

            return "Wait for Setup"

        final['SUGGESTED_STRATEGY'] = final.apply(suggest_strategy, axis=1)

        # --- EXPORT RAW GREEKS FOR DASHBOARD ---
        os.makedirs("data/processed", exist_ok=True)
        # We also need the lot sizes and spots inside the greeks file so Streamlit can calculate GEX
        greeks_t['LOT_SIZE'] = greeks_t['SYMBOL'].map(lambda x: lots.get(x, 1))
        greeks_t['SPOT'] = greeks_t['SYMBOL'].map(spots_t)
        
        # Pre-calculate GEX for the dashboard (saves streamlit from having to do it)
        greeks_t['MULTIPLIER'] = greeks_t['OPTION_TYP'].apply(lambda x: 1 if x == 'CE' else -1)
        greeks_t['GEX'] = greeks_t['GAMMA'] * greeks_t['OPEN_INT'] * greeks_t['SPOT'] * 0.01 * greeks_t['MULTIPLIER']
        
        greeks_t.to_csv("data/processed/greeks.csv", index=False)
        
        # --- OVERRIDE WALLS WITH GEX WALLS ---
        # Instead of pure OI (which includes dead deep OTM strikes), 
        # we calculate the walls based on where the highest Dealer Gamma Risk is concentrated.
        for symbol, group in greeks_t.groupby('SYMBOL'):
            ce_gex = group[group['OPTION_TYP'] == 'CE'].groupby('STRIKE_PR')['GEX'].sum()
            pe_gex = group[group['OPTION_TYP'] == 'PE'].groupby('STRIKE_PR')['GEX'].sum().abs()
            
            # Max Positive GEX for Calls, Max Negative GEX for Puts
            call_wall = ce_gex.idxmax() if not ce_gex.empty else 0
            put_wall = pe_gex.idxmax() if not pe_gex.empty else 0
            
            # Gamma Flip: The strike with the highest overlapping Dealer Gamma Risk
            overlap = pd.concat([ce_gex, pe_gex], axis=1).min(axis=1)
            gamma_flip = overlap.idxmax() if not overlap.empty and not overlap.isna().all() else 0
            
            final.loc[final['SYMBOL'] == symbol, 'CALL_WALL_T'] = call_wall
            final.loc[final['SYMBOL'] == symbol, 'PUT_WALL_T'] = put_wall
            final.loc[final['SYMBOL'] == symbol, 'GAMMA_FLIP_T'] = gamma_flip

        return final

if __name__ == "__main__":
    intel = InstitutionalIntelligence()
    results = intel.analyze_market_structure(
        "data/raw/BhavCopy_NSE_FO_0_0_0_20260515_F_0000.csv",
        "data/raw/BhavCopy_NSE_FO_0_0_0_20260514_F_0000.csv"
    )
    
    print("\n" + "="*80)
    print("INSTITUTIONAL TRADE INTELLIGENCE REPORT")
    print("="*80)
    print(results[['SYMBOL', 'SPOT_CHG_PCT', 'CE_INTERP', 'PE_INTERP', 'GEX_INTENSITY', 'SUGGESTED_STRATEGY']].head(20))
    
    results.to_csv("data/processed/trade_intelligence.csv", index=False)
