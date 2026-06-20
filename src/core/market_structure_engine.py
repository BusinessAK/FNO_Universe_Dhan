import pandas as pd
import numpy as np
from src.models.states import MarketState

class MarketStructureEngine:
    """
    Decoupled Option Chain Quantitative Analytics Engine.
    Processes options chains, aggregates dealer exposure, maps Call/Put walls,
    and returns fully structured MarketState dataclass states.
    """
    def __init__(self):
        pass

    def compute_structure(self, symbol: str, active_date: str, greeks_slice: pd.DataFrame, latest_metrics: dict) -> MarketState:
        """
        Computes EOD options parameters (walls, GEX, PCR, flip pivots)
        using normalized datasets, returning a clean, type-safe MarketState structure.
        """
        # Fallback values from pre-compiled compiler history
        spot_close = latest_metrics.get("spot_close", 0.0)
        call_wall = latest_metrics.get("call_wall", 0.0)
        put_wall = latest_metrics.get("put_wall", 0.0)
        gamma_flip = latest_metrics.get("gamma_flip", 0.0)
        gex_total = latest_metrics.get("gex", 0.0)
        pcr_index = latest_metrics.get("pcr", 0.0)
        ifs_score = latest_metrics.get("ifs_score", 0.0)
        gex_intensity = latest_metrics.get("gex_intensity", 0.0)
        gamma_regime = latest_metrics.get("gamma_regime", "ROTATION")

        # If options chain data exists for latest session, calculate dynamically!
        if not greeks_slice.empty:
            try:
                g_slice = greeks_slice.copy()

                # ── Spot Price Priority ──────────────────────────────────────
                # Authoritative source: session_history.spot_close (compiled from
                # the official NSE EOD settlement price in the raw bhav file).
                # greeks.csv SPOT is only used as a fallback when the compiled
                # value is missing or zero — it may reflect an intraday snapshot
                # or a different pipeline pass and should never override EOD truth.
                if spot_close == 0.0 or pd.isna(spot_close):
                    if "SPOT" in g_slice.columns and not pd.isna(g_slice["SPOT"].iloc[0]):
                        spot_close = float(g_slice["SPOT"].iloc[0])
                # ────────────────────────────────────────────────────────────
                
                g_slice["GEX"] = pd.to_numeric(g_slice["GEX"], errors="coerce").fillna(0.0)
                g_slice["STRIKE_PR"] = pd.to_numeric(g_slice["STRIKE_PR"], errors="coerce").fillna(0.0)
                g_slice["OPEN_INT"] = pd.to_numeric(g_slice["OPEN_INT"], errors="coerce").fillna(0.0)
                
                ce_gex = g_slice[g_slice['OPTION_TYP'] == 'CE'].groupby('STRIKE_PR')['GEX'].sum()
                pe_gex = g_slice[g_slice['OPTION_TYP'] == 'PE'].groupby('STRIKE_PR')['GEX'].sum().abs()
                
                # Initialize walls to 0.0 before dynamic calculation so we don't bleed all-expiry values
                call_wall = 0.0
                put_wall = 0.0

                # Call Wall = Strike of maximum positive Call GEX
                # Filter > 0 to avoid garbage idxmax() on zero-GEX series (BUG-3 fix)
                ce_gex_pos = ce_gex[ce_gex > 0]
                if not ce_gex_pos.empty:
                    call_wall = float(ce_gex_pos.idxmax())
                
                # Put Wall = Strike of maximum absolute Put GEX
                pe_gex_pos = pe_gex[pe_gex > 0]
                if not pe_gex_pos.empty:
                    put_wall = float(pe_gex_pos.idxmax())
                
                # ── Gamma Flip: ALWAYS use compiled ALL-EXPIRY value from latest_metrics ──
                # Gamma Flip is a full-chain structural pivot (where aggregate dealer net gamma
                # crosses zero). Filtering to a single expiry distorts this — near-expiry gamma
                # is exponentially amplified, anchoring the flip to a different strike.
                # The compiled value (from intelligence.py, full chain) is the canonical one.
                # gamma_flip is intentionally NOT overridden here.
                
                # Combined Net GEX Exposure
                gex_total = float(g_slice['GEX'].sum())
                
                # PCR Index
                ce_oi = g_slice[g_slice['OPTION_TYP'] == 'CE']['OPEN_INT'].sum()
                pe_oi = g_slice[g_slice['OPTION_TYP'] == 'PE']['OPEN_INT'].sum()
                pcr_index = float(pe_oi / ce_oi) if ce_oi > 0 else pcr_index
                
                # Regime Mapping based on true mathematical Flip zone boundary
                if gamma_flip > 0:
                    if abs(spot_close - gamma_flip) / spot_close <= 0.008:
                        gamma_regime = "TRANSITION_REGIME"
                    elif spot_close > gamma_flip:
                        gamma_regime = "LONG_GAMMA"
                    else:
                        gamma_regime = "SHORT_GAMMA"
                else:
                    gamma_regime = "TRANSITION_REGIME"
                    if gex_total > 200000:
                        gamma_regime = "LONG_GAMMA"
                    elif gex_total < -10000:
                        gamma_regime = "SHORT_GAMMA"
                    
            except Exception:
                # Silently fall back to pre-compiled values if any dynamic math parsing fails
                pass

        return MarketState(
            symbol=symbol,
            spot=spot_close,
            call_wall=call_wall,
            put_wall=put_wall,
            gamma_flip=gamma_flip,
            gex=gex_total,
            pcr=pcr_index,
            ifs_score=ifs_score,
            gamma_regime=gamma_regime,
            gex_intensity=gex_intensity
        )
