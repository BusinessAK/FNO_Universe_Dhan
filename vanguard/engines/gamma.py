import pandas as pd
import numpy as np

class GammaAnalyzer:
    def __init__(self, lot_sizes: dict = None):
        # Default lot sizes for some major stocks if not provided
        self.lot_sizes = lot_sizes or {
            'NIFTY': 65,
            'BANKNIFTY': 15,
            'RELIANCE': 250,
            'TCS': 175,
            'HDFCBANK': 550,
            'ICICIBANK': 700,
            'INFY': 400
        }

    def calculate_gex(self, greeks_df: pd.DataFrame, spot_prices: dict) -> pd.DataFrame:
        """
        Calculates GEX for each row and aggregates by Symbol.
        """
        df = greeks_df.copy()
        
        def get_gex(row):
            symbol = row['SYMBOL']
            spot = spot_prices.get(symbol, 0)
            
            # GEX Formula: Gamma * OI (in shares) * Spot (scaled)
            # We use positive for Calls, negative for Puts (Dealer Short Gamma perspective)
            # Standard Dealer GEX = (Call Gamma * Call OI) - (Put Gamma * Put OI)
            multiplier = 1 if row['OPTION_TYP'] == 'CE' else -1
            
            # Scaled by 0.01 for better readability (Gamma per 1% move)
            gex = row['GAMMA'] * row['OPEN_INT'] * spot * 0.01 * multiplier
            return gex

        if df.empty:
            print("[!] Warning: No data to analyze for GEX.")
            return pd.DataFrame(columns=['SYMBOL', 'GEX', 'OPEN_INT', 'CHG_IN_OI', 'IV', 'GEX_INTENSITY'])

        df['GEX'] = df.apply(get_gex, axis=1)
        
        # Aggregate by symbol
        summary = df.groupby('SYMBOL').agg({
            'GEX': 'sum',
            'OPEN_INT': 'sum',
            'CHG_IN_OI': 'sum',
            'IV': 'mean'
        }).reset_index()
        
        summary['GEX_INTENSITY'] = ((summary['GEX'] / summary['OPEN_INT'].replace(0, np.nan)).fillna(0.0) * 1000.0)
        
        return summary

    def advanced_analysis(self, df_options: pd.DataFrame, df_futures: pd.DataFrame):
        """Calculates CoC and OI Concentration"""
        results = []
        symbols = df_options['SYMBOL'].unique()
        
        for symbol in symbols:
            # 1. Cost of Carry (CoC)
            fut_row = df_futures[df_futures['SYMBOL'] == symbol]
            opt_rows = df_options[df_options['SYMBOL'] == symbol]
            
            if fut_row.empty or opt_rows.empty: continue
            
            spot = opt_rows['SPOT_PRICE'].iloc[0]
            fut = fut_row['CLOSE'].iloc[0]
            coc_spread = ((fut - spot) / spot) * 100
            
            # 2. OI Concentration (Strike with Max GEX vs Spot)
            if 'GEX' in opt_rows.columns:
                max_gex_strike = opt_rows.loc[opt_rows['GEX'].abs().idxmax()]['STRIKE_PR']
            else:
                # Fallback to Strike with Max Open Interest (OI Wall)
                max_gex_strike = opt_rows.loc[opt_rows['OPEN_INT'].idxmax()]['STRIKE_PR']
            distance_to_wall = abs(max_gex_strike - spot) / spot * 100
            
            results.append({
                'SYMBOL': symbol,
                'COC_SPREAD': round(coc_spread, 3),
                'DIST_TO_WALL': round(distance_to_wall, 2),
                'GEX_WALL': max_gex_strike
            })
            
        return pd.DataFrame(results)

    def find_best_stocks(self, summary: pd.DataFrame) -> pd.DataFrame:
        """
        Ranks stocks based on:
        1. High Positive GEX (Stability/Support)
        2. High Negative GEX (Potential Volatility/Squeeze)
        3. High OI Change (Institutional Activity)
        """
        # Sort by GEX Absolute value to find most "Gamma Active" stocks
        summary['GEX_ABS'] = summary['GEX'].abs()
        ranked = summary.sort_values(by='GEX_ABS', ascending=False)
        
        return ranked

if __name__ == "__main__":
    # Test logic
    pass
