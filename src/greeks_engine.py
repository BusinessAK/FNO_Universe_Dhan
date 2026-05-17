import numpy as np
import pandas as pd
from scipy.stats import norm
from scipy.optimize import brentq
from typing import Tuple

class GreeksEngine:
    def __init__(self, risk_free_rate: float = 0.07):
        self.r = risk_free_rate

    def black_scholes_greeks(self, S: float, K: float, T: float, sigma: float, option_type: str) -> Tuple[float, float]:
        """
        Calculates Delta and Gamma.
        T is in years.
        """
        if T <= 0 or sigma <= 0:
            return 0.0, 0.0

        d1 = (np.log(S / K) + (self.r + 0.5 * sigma**2) * T) / (sigma * np.sqrt(T))
        
        if option_type == 'CE':
            delta = norm.cdf(d1)
        else: # PE
            delta = norm.cdf(d1) - 1
            
        gamma = norm.pdf(d1) / (S * sigma * np.sqrt(T))
        
        return delta, gamma

    def calculate_iv(self, market_price: float, S: float, K: float, T: float, option_type: str) -> float:
        """
        Backs out Implied Volatility using Brent's method.
        """
        if T <= 0 or market_price <= 0:
            return 0.0

        def objective(sigma):
            d1 = (np.log(S / K) + (self.r + 0.5 * sigma**2) * T) / (sigma * np.sqrt(T))
            d2 = d1 - sigma * np.sqrt(T)
            if option_type == 'CE':
                price = S * norm.cdf(d1) - K * np.exp(-self.r * T) * norm.cdf(d2)
            else:
                price = K * np.exp(-self.r * T) * norm.cdf(-d2) - S * norm.cdf(-d1)
            return price - market_price

        try:
            # Search for IV between 0.1% and 500%
            return brentq(objective, 0.001, 5.0)
        except (ValueError, RuntimeError):
            return 0.2  # Default fallback volatility 20%

    def process_dataframe(self, df: pd.DataFrame, spot_prices: dict) -> pd.DataFrame:
        """
        Vectorized or efficient calculation for a dataframe.
        """
        results = []
        
        # Filter for options only (UDiFF codes: STO, IXO)
        options_df = df[df['INSTRUMENT'].isin(['STO', 'IXO'])].copy()
        
        # Calculate Time to Expiry (T) in years
        options_df['T'] = (options_df['EXPIRY_DT'] - options_df['TIMESTAMP']).dt.days / 365.0
        
        # We only care about liquid-ish options or those with OI
        options_df = options_df[options_df['OPEN_INT'] > 0]

        for idx, row in options_df.iterrows():
            S = spot_prices.get(row['SYMBOL'])
            if not S or S <= 0:
                continue
            
            K = row['STRIKE_PR']
            T = row['T']
            price = row['CLOSE']
            opt_type = row['OPTION_TYP']
            
            iv = self.calculate_iv(price, S, K, T, opt_type)
            delta, gamma = self.black_scholes_greeks(S, K, T, iv, opt_type)
            
            results.append({
                'SYMBOL': row['SYMBOL'],
                'STRIKE_PR': K,
                'OPTION_TYP': opt_type,
                'EXPIRY_DT': row['EXPIRY_DT'],
                'IV': iv,
                'DELTA': delta,
                'GAMMA': gamma,
                'OPEN_INT': row['OPEN_INT'],
                'CHG_IN_OI': row['CHG_IN_OI'],
                'CLOSE': row['CLOSE']
            })
            
        return pd.DataFrame(results)
