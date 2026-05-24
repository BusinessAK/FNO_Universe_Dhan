import numpy as np
import pandas as pd
from scipy.stats import norm
from scipy.optimize import brentq
from typing import Tuple

class GreeksEngine:
    def __init__(self, risk_free_rate: float = 0.07):
        self.r = risk_free_rate

    def bs_price(self, S: float, K: float, T: float, sigma: float, option_type: str) -> float:
        """
        Standard Black-Scholes option pricing.
        """
        if T <= 0 or sigma <= 0:
            return max(0.0, S - K) if option_type == 'CE' else max(0.0, K - S)

        d1 = (np.log(S / K) + (self.r + 0.5 * sigma**2) * T) / (sigma * np.sqrt(T))
        d2 = d1 - sigma * np.sqrt(T)

        if option_type == 'CE':
            return S * norm.cdf(d1) - K * np.exp(-self.r * T) * norm.cdf(d2)
        else:
            return K * np.exp(-self.r * T) * norm.cdf(-d2) - S * norm.cdf(-d1)

    def all_greeks(self, S: float, K: float, T: float, sigma: float, option_type: str) -> dict:
        """
        Calculates all Greeks: Delta, Gamma, Vega, Theta, Rho, Vanna, Charm, Vomma.
        T is in years.
        """
        res = {
            'DELTA': 0.0, 'GAMMA': 0.0, 'VEGA': 0.0, 'THETA': 0.0,
            'RHO': 0.0, 'VANNA': 0.0, 'CHARM': 0.0, 'VOMMA': 0.0
        }
        if T <= 0 or sigma <= 0 or S <= 0 or K <= 0:
            return res

        d1 = (np.log(S / K) + (self.r + 0.5 * sigma**2) * T) / (sigma * np.sqrt(T))
        d2 = d1 - sigma * np.sqrt(T)
        pdf1 = norm.pdf(d1)
        cdf1 = norm.cdf(d1)
        cdf2 = norm.cdf(d2)

        # Delta & Gamma
        if option_type == 'CE':
            res['DELTA'] = cdf1
        else:
            res['DELTA'] = cdf1 - 1
        res['GAMMA'] = pdf1 / (S * sigma * np.sqrt(T))

        # Vega (per 1% IV change, i.e. / 100)
        res['VEGA'] = S * pdf1 * np.sqrt(T) / 100.0

        # Theta (per day, i.e. / 365)
        if option_type == 'CE':
            theta = - (S * pdf1 * sigma) / (2.0 * np.sqrt(T)) - self.r * K * np.exp(-self.r * T) * cdf2
        else:
            theta = - (S * pdf1 * sigma) / (2.0 * np.sqrt(T)) + self.r * K * np.exp(-self.r * T) * norm.cdf(-d2)
        res['THETA'] = theta / 365.0

        # Rho (per 1% interest rate change, i.e. / 100)
        if option_type == 'CE':
            rho = K * T * np.exp(-self.r * T) * cdf2
        else:
            rho = - K * T * np.exp(-self.r * T) * norm.cdf(-d2)
        res['RHO'] = rho / 100.0

        # Vanna (change in delta per 100% IV change / raw derivative)
        res['VANNA'] = - pdf1 * d2 / sigma

        # Charm (delta decay per day)
        charm = - pdf1 * (self.r / (sigma * np.sqrt(T)) - d2 / (2.0 * T))
        res['CHARM'] = charm / 365.0

        # Vomma (Volga)
        res['VOMMA'] = res['VEGA'] * d1 * d2 / sigma

        return res

    def pnl_heatmap(self, S_spot: float, K: float, T: float, sigma_init: float, option_type: str,
                    S_range: float = 0.05, sigma_range: float = 0.40, n_S: int = 25, n_sig: int = 20) -> Tuple[np.ndarray, np.ndarray, np.ndarray]:
        """
        Generates grid parameters and resulting P&L matrix for scenario analysis.
        """
        S_g = np.linspace(S_spot * (1.0 - S_range), S_spot * (1.0 + S_range), n_S)
        sig_g = np.linspace(max(0.01, sigma_init * (1.0 - sigma_range)), sigma_init * (1.0 + sigma_range), n_sig)

        price_init = self.bs_price(S_spot, K, T, sigma_init, option_type)
        pnl = np.zeros((n_sig, n_S))

        for i, sig in enumerate(sig_g):
            for j, S in enumerate(S_g):
                pnl[i, j] = self.bs_price(S, K, T, sig, option_type) - price_init

        return S_g, sig_g, pnl

    def black_scholes_greeks(self, S: float, K: float, T: float, sigma: float, option_type: str) -> Tuple[float, float]:
        """
        Calculates Delta and Gamma.
        T is in years.
        """
        if T <= 0 or sigma <= 0 or S <= 0 or K <= 0:
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
        if T <= 0 or market_price <= 0 or S <= 0 or K <= 0:
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
        Vectorized or efficient calculation for a dataframe with aggressive performance optimization.
        """
        results = []
        
        # Filter for options only (UDiFF codes: STO, IDO)
        options_df = df[df['INSTRUMENT'].isin(['STO', 'IDO'])].copy()
        
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
            
            # OPTIMIZATION: Filter out strikes that are more than 15% away from spot.
            # These far OTM/ITM strikes have essentially 0 Gamma, but their IV calculation
            # takes a huge amount of time because Brent fails to find roots.
            if abs(K - S) / S > 0.15:
                continue
                
            # OPTIMIZATION: Skip very cheap options as they are dead dust
            if price < 0.05:
                iv = 0.20
            else:
                iv = self.calculate_iv(price, S, K, T, opt_type)
                
            greeks = self.all_greeks(S, K, T, iv, opt_type)
            
            results.append({
                'SYMBOL': row['SYMBOL'],
                'STRIKE_PR': K,
                'OPTION_TYP': opt_type,
                'EXPIRY_DT': row['EXPIRY_DT'],
                'IV': iv,
                'DELTA': greeks['DELTA'],
                'GAMMA': greeks['GAMMA'],
                'VEGA': greeks['VEGA'],
                'THETA': greeks['THETA'],
                'VANNA': greeks['VANNA'],
                'CHARM': greeks['CHARM'],
                'OPEN_INT': row['OPEN_INT'],
                'CHG_IN_OI': row['CHG_IN_OI'],
                'VOLUME': row.get('VOLUME', 0),
                'CLOSE': row['CLOSE']
            })
            
        return pd.DataFrame(results)
