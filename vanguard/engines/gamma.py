import pandas as pd
import numpy as np

class GammaAnalyzer:
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

        # IV must be OI-weighted, not a naive per-strike mean — an unweighted
        # mean lets dust (deep ITM/OTM strikes that barely trade, so their
        # last CLOSE is stale and produces an erratic Black-Scholes-implied
        # IV) pull the aggregate as hard as the liquid, near-ATM strikes that
        # actually drive the chain. Same fix already applied on the EOD path
        # (vanguard/engines/intelligence.py's get_detailed_metrics, per its
        # own comment: "NIFTY's unweighted mean IV was 2x its OI-weighted
        # true IV") — this was the one caller (vanguard/live/live_compute.py)
        # still using the naive mean, which is why live IV in the HUD ran
        # systematically ~10-20pt hotter than the EOD figure for the same
        # name: confirmed against a real live chain (ONGC) where deep ITM/OTM
        # strikes showed IV swinging 30-60% strike-to-strike on near-zero
        # premiums, exactly the dust this weighting is meant to suppress.
        df['IV_X_OI'] = df['IV'] * df['OPEN_INT']

        # Aggregate by symbol
        summary = df.groupby('SYMBOL').agg({
            'GEX': 'sum',
            'OPEN_INT': 'sum',
            'CHG_IN_OI': 'sum',
            'IV_X_OI': 'sum',
        }).reset_index()

        summary['IV'] = (summary['IV_X_OI'] / summary['OPEN_INT'].replace(0, np.nan)).fillna(0.0)
        summary = summary.drop(columns=['IV_X_OI'])
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
