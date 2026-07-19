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

    def implied_vol_vectorized(self, price, S, K, T, is_call,
                               max_iter: int = 12, iv_tol: float = 1e-6):
        """
        Newton-Raphson IV solve over numpy arrays, seeded with the
        Brenner-Subrahmanyam approximation. Returns (iv, converged) — rows that
        fail to converge get iv=NaN and converged=False, and the caller decides
        the fallback (process_dataframe falls back to the scalar brentq path so
        pathological rows keep byte-identical historical behavior).

        Domain clamped to [0.001, 5.0] to mirror calculate_iv's brentq bracket.
        """
        price = np.asarray(price, dtype=float)
        S = np.asarray(S, dtype=float)
        K = np.asarray(K, dtype=float)
        T = np.asarray(T, dtype=float)
        is_call = np.asarray(is_call, dtype=bool)

        iv = np.full(price.shape, np.nan)
        converged = np.zeros(price.shape, dtype=bool)
        valid = (price > 0) & (S > 0) & (K > 0) & (T > 0)
        if not valid.any():
            # mirror calculate_iv: invalid inputs -> 0.0, "converged" by definition
            iv[~valid] = 0.0
            converged[~valid] = True
            return iv, converged

        p, s, k, t, c = price[valid], S[valid], K[valid], T[valid], is_call[valid]
        sqt = np.sqrt(t)
        # Brenner-Subrahmanyam seed (ATM approx), clamped to the solve domain
        sig = np.clip(np.sqrt(2.0 * np.pi / t) * p / s, 0.05, 3.0)
        done = np.zeros(sig.shape, dtype=bool)

        with np.errstate(divide="ignore", invalid="ignore", over="ignore"):
            for _ in range(max_iter):
                d1 = (np.log(s / k) + (self.r + 0.5 * sig ** 2) * t) / (sig * sqt)
                d2 = d1 - sig * sqt
                model = np.where(
                    c,
                    s * norm.cdf(d1) - k * np.exp(-self.r * t) * norm.cdf(d2),
                    k * np.exp(-self.r * t) * norm.cdf(-d2) - s * norm.cdf(-d1),
                )
                diff = model - p
                vega = s * norm.pdf(d1) * sqt
                # Convergence is judged in IV units (|diff|/vega ~ IV error),
                # not price units — an absolute price tol under-converges cheap
                # contracts and over-demands precision on expensive ones.
                done |= np.abs(diff) < np.maximum(vega * iv_tol, 1e-10)
                if done.all():
                    break
                step = np.clip(diff / np.maximum(vega, 1e-10), -0.5, 0.5)
                sig = np.where(done, sig, np.clip(sig - step, 0.001, 5.0))

        out_iv = np.where(done, sig, np.nan)
        iv[valid] = out_iv
        converged[valid] = done
        iv[~valid] = 0.0
        converged[~valid] = True
        return iv, converged

    def greeks_vectorized(self, S, K, T, sigma, is_call) -> dict:
        """
        all_greeks() over numpy arrays — same formulas, same per-day / per-1%
        scalings. Rows failing all_greeks' validity guard (T<=0, sigma<=0,
        S<=0, K<=0) get all-zero greeks, exactly like the scalar path.
        """
        S = np.asarray(S, dtype=float)
        K = np.asarray(K, dtype=float)
        T = np.asarray(T, dtype=float)
        sigma = np.asarray(sigma, dtype=float)
        is_call = np.asarray(is_call, dtype=bool)

        ok = (T > 0) & (sigma > 0) & (S > 0) & (K > 0)
        z = np.zeros(S.shape)
        res = {g: z.copy() for g in
               ('DELTA', 'GAMMA', 'VEGA', 'THETA', 'RHO', 'VANNA', 'CHARM', 'VOMMA')}
        if not ok.any():
            return res

        s, k, t, sig, c = S[ok], K[ok], T[ok], sigma[ok], is_call[ok]
        sqt = np.sqrt(t)
        d1 = (np.log(s / k) + (self.r + 0.5 * sig ** 2) * t) / (sig * sqt)
        d2 = d1 - sig * sqt
        pdf1, cdf1, cdf2 = norm.pdf(d1), norm.cdf(d1), norm.cdf(d2)
        disc = np.exp(-self.r * t)

        res['DELTA'][ok] = np.where(c, cdf1, cdf1 - 1.0)
        res['GAMMA'][ok] = pdf1 / (s * sig * sqt)
        vega = s * pdf1 * sqt / 100.0
        res['VEGA'][ok] = vega
        theta = np.where(
            c,
            -(s * pdf1 * sig) / (2.0 * sqt) - self.r * k * disc * cdf2,
            -(s * pdf1 * sig) / (2.0 * sqt) + self.r * k * disc * norm.cdf(-d2),
        )
        res['THETA'][ok] = theta / 365.0
        rho = np.where(c, k * t * disc * cdf2, -k * t * disc * norm.cdf(-d2))
        res['RHO'][ok] = rho / 100.0
        res['VANNA'][ok] = -pdf1 * d2 / sig
        res['CHARM'][ok] = -pdf1 * (self.r / (sig * sqt) - d2 / (2.0 * t)) / 365.0
        res['VOMMA'][ok] = vega * d1 * d2 / sig
        return res

    def process_dataframe(self, df: pd.DataFrame, spot_prices: dict, wall_candidates: int = 5,
                          iv_method: str = "vectorized") -> pd.DataFrame:
        """
        IV + Greeks for a normalized option chain frame.

        iv_method:
          "vectorized" (default) — Newton-Raphson over the whole frame
              (~1000x faster; F0-parity-gated vs brentq at |dIV| <= 1e-4);
              rows that fail to converge fall back to the scalar path below,
              so pathological rows keep historical brentq-or-0.2 behavior.
          "scalar" — the original per-row brentq loop, kept as the parity
              referee and as the fallback implementation.

        wall_candidates: per (symbol, option type), this many of the largest-OI
        strikes are always computed regardless of distance from spot (see the
        15%-filter comment below for why).
        """
        # Filter for options only (UDiFF codes: STO, IDO)
        options_df = df[df['INSTRUMENT'].isin(['STO', 'IDO'])].copy()

        # Calculate Time to Expiry (T) in years
        options_df['T'] = (options_df['EXPIRY_DT'] - options_df['TIMESTAMP']).dt.days / 365.0

        # We only care about liquid-ish options or those with OI
        options_df = options_df[options_df['OPEN_INT'] > 0]

        # The 15%-distance skip below exists purely to avoid slow, low-information
        # Black-Scholes solves on deep-OTM dust — but callers (intelligence.py's
        # wall/gamma-flip detection) only ever see strikes that make it out of this
        # function. Skipping on distance alone can silently exclude a strike that
        # carries real, large OI just because it happens to sit >15% out (common on
        # low-priced names where one strike step is already a double-digit % move).
        # Guarantee the top-N OI strikes per side are always computed, so a genuine
        # wall is never invisible to what's built from this output.
        top_oi_idx = (
            options_df.groupby(['SYMBOL', 'OPTION_TYP'])['OPEN_INT']
            .nlargest(wall_candidates)
            .index.get_level_values(-1)
        )
        must_keep = set(top_oi_idx)

        # Shared row selection (both methods must see identical rows):
        # drop symbols without a positive spot; apply the 15%-distance filter
        # below, except for must_keep wall candidates.
        options_df['SPOT_LK'] = options_df['SYMBOL'].map(spot_prices)
        options_df = options_df[options_df['SPOT_LK'].fillna(0) > 0]

        # OPTIMIZATION: Filter out strikes that are more than 15% away from spot,
        # unless the strike is large enough OI to be a wall candidate (must_keep).
        # These far OTM/ITM strikes have essentially 0 Gamma, but their IV calculation
        # takes a huge amount of time because the root solve struggles.
        near = (options_df['STRIKE_PR'] - options_df['SPOT_LK']).abs() / options_df['SPOT_LK'] <= 0.15
        keep = near | options_df.index.isin(must_keep)
        options_df = options_df[keep]

        if options_df.empty:
            return pd.DataFrame()

        if iv_method == "vectorized":
            iv = self._iv_block_vectorized(options_df)
        else:
            iv = self._iv_block_scalar(options_df)

        is_call = (options_df['OPTION_TYP'] == 'CE').to_numpy()
        greeks = self.greeks_vectorized(
            options_df['SPOT_LK'].to_numpy(), options_df['STRIKE_PR'].to_numpy(),
            options_df['T'].to_numpy(), iv, is_call)

        out = pd.DataFrame({
            'SYMBOL': options_df['SYMBOL'].to_numpy(),
            'STRIKE_PR': options_df['STRIKE_PR'].to_numpy(),
            'OPTION_TYP': options_df['OPTION_TYP'].to_numpy(),
            'EXPIRY_DT': options_df['EXPIRY_DT'].to_numpy(),
            'IV': iv,
            'DELTA': greeks['DELTA'],
            'GAMMA': greeks['GAMMA'],
            'VEGA': greeks['VEGA'],
            'THETA': greeks['THETA'],
            'VANNA': greeks['VANNA'],
            'CHARM': greeks['CHARM'],
            'OPEN_INT': options_df['OPEN_INT'].to_numpy(),
            'CHG_IN_OI': options_df['CHG_IN_OI'].to_numpy(),
            'VOLUME': (options_df['VOLUME'] if 'VOLUME' in options_df else
                       pd.Series(0, index=options_df.index)).to_numpy(),
            'CLOSE': options_df['CLOSE'].to_numpy(),
        })
        return out.reset_index(drop=True)

    # ── IV blocks (row selection already done by process_dataframe) ─────────

    def _iv_block_scalar(self, odf: pd.DataFrame) -> np.ndarray:
        """Original behavior: dust (<0.05) pinned at 20% IV, else brentq
        (with its internal brentq-failure -> 0.2 fallback)."""
        ivs = np.empty(len(odf))
        for i, row in enumerate(odf.itertuples()):
            if row.CLOSE < 0.05:
                ivs[i] = 0.20
            else:
                ivs[i] = self.calculate_iv(row.CLOSE, row.SPOT_LK, row.STRIKE_PR,
                                           row.T, row.OPTION_TYP)
        return ivs

    def _iv_block_vectorized(self, odf: pd.DataFrame) -> np.ndarray:
        """Newton over the whole block; dust pinned at 20% exactly like the
        scalar path; non-converged rows fall back to scalar brentq so the
        pathological tail keeps byte-identical historical behavior."""
        price = odf['CLOSE'].to_numpy(dtype=float)
        S = odf['SPOT_LK'].to_numpy(dtype=float)
        K = odf['STRIKE_PR'].to_numpy(dtype=float)
        T = odf['T'].to_numpy(dtype=float)
        is_call = (odf['OPTION_TYP'] == 'CE').to_numpy()

        dust = price < 0.05
        iv, converged = self.implied_vol_vectorized(price, S, K, T, is_call)
        iv[dust] = 0.20

        fallback = ~converged & ~dust
        if fallback.any():
            sub = odf[fallback]
            iv[fallback] = [self.calculate_iv(r.CLOSE, r.SPOT_LK, r.STRIKE_PR,
                                              r.T, r.OPTION_TYP)
                            for r in sub.itertuples()]
        return iv
