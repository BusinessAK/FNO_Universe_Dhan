import pandas as pd
import numpy as np
import os
from vanguard.processor import DataProcessor
from vanguard.greeks_engine import GreeksEngine
from vanguard.analyzer import GammaAnalyzer

# Flow classification thresholds
FLOW_QUIET_OI_FRAC = 0.02   # gross OI churn this small means the chain barely traded
FLOW_NET_VS_GROSS = 0.20    # net must be this share of gross to claim a direction
FLOW_VOTE_MAJORITY = 0.60   # winning premium direction must carry this share of the OI


class InstitutionalIntelligence:
    def __init__(self):
        self.processor = DataProcessor()
        self.engine = GreeksEngine()

    @staticmethod
    def classify_oi_flow(df_opt: pd.DataFrame) -> pd.DataFrame:
        """
        Classify per-symbol CE/PE flow from the option's OWN premium change.

        Whether new OI is buying or writing is only decidable from the price of the
        contract being traded, so this applies the standard OI matrix to the option
        itself rather than inferring it from the underlying's move:

            OI up   + premium up   -> Long Build-up  (buying)
            OI up   + premium down -> Short Build-up (writing)
            OI down + premium down -> Long Unwinding
            OI down + premium up   -> Short Covering

        Reading it off the spot instead only holds while IV is flat: on a down day
        with collapsing IV, put premiums fall while spot falls, which is writing
        being mislabelled as buying.

        Direction is an OI-weighted vote on the SIGN of each strike's premium change.
        Voting on signs rather than averaging the changes keeps one illiquid strike
        with a stale previous close from outvoting the liquid body of the chain.
        """
        need = {'SYMBOL', 'OPTION_TYP', 'CLOSE', 'PREV_CLOSE', 'OPEN_INT', 'CHG_IN_OI', 'VOLUME'}
        missing = need - set(df_opt.columns)
        if missing:
            raise KeyError(f"classify_oi_flow requires columns {sorted(missing)}")

        def classify_side(g: pd.DataFrame, side: str) -> str:
            chain_oi = g['OPEN_INT'].sum()
            if chain_oi <= 0:
                return "Neutral"

            # An untraded strike's close is stale, so it neither counts as flow nor votes.
            traded = g[g['VOLUME'] > 0]
            net_oi_chg = g['CHG_IN_OI'].sum()
            gross_oi_chg = traded['CHG_IN_OI'].abs().sum()

            if gross_oi_chg < FLOW_QUIET_OI_FRAC * chain_oi:
                return "Neutral"
            # Heavy flow that nets to nothing is two-way churn, not conviction. Judging
            # on net alone would report a direction that the gross flow does not support.
            if abs(net_oi_chg) < FLOW_NET_VS_GROSS * gross_oi_chg:
                return "Two-Sided Churn"

            building = net_oi_chg > 0
            # Only the strikes moving in the net direction inform what that net is.
            legs = traded[(traded['CHG_IN_OI'] > 0) if building else (traded['CHG_IN_OI'] < 0)]
            if legs.empty:
                return "Neutral"

            weight = legs['CHG_IN_OI'].abs()
            prem_chg = legs['CLOSE'] - legs['PREV_CLOSE']
            up = weight[prem_chg > 0].sum()
            down = weight[prem_chg < 0].sum()
            decided = up + down
            if decided <= 0:
                return "Neutral"

            up_frac = up / decided
            if up_frac >= FLOW_VOTE_MAJORITY:
                prem_up = True
            elif (1 - up_frac) >= FLOW_VOTE_MAJORITY:
                prem_up = False
            else:
                return "Mixed Build-up" if building else "Mixed Unwind"

            if building:
                return f"{side} Buying (Long Build-up)" if prem_up else f"{side} Writing (Short Build-up)"
            return "Short Covering" if prem_up else "Long Unwinding"

        rows = {}
        for (symbol, opt_typ), g in df_opt.groupby(['SYMBOL', 'OPTION_TYP']):
            if opt_typ not in ('CE', 'PE'):
                continue
            col = 'CE_INTERP' if opt_typ == 'CE' else 'PE_INTERP'
            rows.setdefault(symbol, {})[col] = classify_side(g, 'Call' if opt_typ == 'CE' else 'Put')

        out = pd.DataFrame.from_dict(rows, orient='index')
        out.index.name = 'SYMBOL'
        for col in ('CE_INTERP', 'PE_INTERP'):
            if col not in out.columns:
                out[col] = "Neutral"
        return out[['CE_INTERP', 'PE_INTERP']].fillna("Neutral")

    @staticmethod
    def verified_oi_flow(df_opt: pd.DataFrame) -> pd.DataFrame:
        """
        Premium-verified per-symbol net OI flow, in the same units (shares of OI
        change) as the raw CHG_IN_OI it replaces, but signed from the option's own
        premium move instead of assumed from OI direction alone.

        An option's premium direction alone carries the informational content
        regardless of whether OI is building or unwinding: a put getting more
        expensive is bearish news whether that came from fresh buying or from
        writers stepping away, and a put getting cheaper is bullish news whether
        that came from fresh writing or from buyers giving up (mirrored for
        calls). So every state collapses to one rule, verified against all four
        OI-direction x premium-direction combinations before being written here:

            CE contribution = +sign(premium_chg) * |CHG_IN_OI|
            PE contribution = -sign(premium_chg) * |CHG_IN_OI|

        Untraded strikes (VOLUME == 0) have a stale close and are excluded, same
        as classify_oi_flow. A flat premium contributes zero. Genuine two-way
        churn cancels out through the per-strike sign rather than needing a
        separate churn/neutral special case — unlike classify_oi_flow, this is a
        continuous magnitude, not a categorical label, so partial conviction
        should shrink the number rather than being collapsed to "Neutral".
        """
        need = {'SYMBOL', 'OPTION_TYP', 'CLOSE', 'PREV_CLOSE', 'CHG_IN_OI', 'VOLUME'}
        missing = need - set(df_opt.columns)
        if missing:
            raise KeyError(f"verified_oi_flow requires columns {sorted(missing)}")

        traded = df_opt[df_opt['VOLUME'] > 0].copy()
        prem_sign = np.sign(traded['CLOSE'] - traded['PREV_CLOSE'])
        side_sign = np.where(traded['OPTION_TYP'] == 'CE', 1.0,
                              np.where(traded['OPTION_TYP'] == 'PE', -1.0, 0.0))
        traded['VERIFIED_FLOW'] = side_sign * prem_sign * traded['CHG_IN_OI'].abs()

        out = traded.groupby(['SYMBOL', 'OPTION_TYP'])['VERIFIED_FLOW'].sum().unstack(fill_value=0.0)
        out = out.reindex(columns=['CE', 'PE'], fill_value=0.0)
        out.columns = ['VERIFIED_CE_FLOW', 'VERIFIED_PE_FLOW']
        # Every symbol present in the input gets a row, even one with zero
        # traded strikes (e.g. a symbol that hasn't traded at all today) — same
        # guarantee classify_oi_flow makes, so callers never need a defensive
        # fillna just to look a known symbol up.
        return out.reindex(df_opt['SYMBOL'].unique(), fill_value=0.0)

    @staticmethod
    def compute_walls_and_flip(greeks_df: pd.DataFrame) -> dict:
        """
        Per-symbol call_wall/put_wall/gamma_flip from raw OPEN INTEREST on the
        already-filtered candidate strikes GreeksEngine.process_dataframe()
        hands in (15%-of-spot OR each side's top-5-OI strikes regardless of
        distance — see that function's wall_candidates param — so dead
        deep-OTM dust never reaches here). Wall = the strike carrying the
        most open interest on that side. Gamma flip = the strike maximizing
        min(CE_OI, PE_OI) — the strike where both sides have the largest
        simultaneous conviction (the "straddle pin"), forcing dealers to
        actively hedge both ways around it.

        Previously this weighted by Gamma * OI ("GEX") instead of raw OI.
        Retired 2026-07-24 after validation (vanguard/research/
        gex_wall_validation.py, data/research/gex_wall_validation.md):
        Black-Scholes Gamma is identical for a call and a put at the same
        strike/expiry/IV and decays sharply away from the money, so the
        Gamma term routinely overpowered genuine OI differences between
        strikes and dragged call_wall, put_wall AND gamma_flip toward
        whichever strike sat closest to spot regardless of where OI actually
        concentrated — confirmed on SRF 2026-07-23, where raw OI put the real
        call wall at strike 2900 (the largest CE OI on the board) but
        GEX-weighting picked 2700 instead, purely because Gamma decays ~5.7x
        faster than the OI gap between those two strikes. That collapsed
        call_wall==put_wall==gamma_flip on 27.6% of all symbol-days in the
        compiled history, and fed PINCH_ZONE's "extreme volatility coiling"
        condition into firing on 25.8% of all symbol-days — not remotely
        "extreme." Raw OI drops that trigger rate to 8.9%, with a modestly
        cleaner pre/post-pinch forward-realized-volatility split.

        Shared by the EOD compiler (analyze_market_structure below) and the
        live structure engine (vanguard/live/live_compute.py) so the two paths
        computing this from either bhav closes or live ticks can never
        silently diverge on the math itself.

        greeks_df: SYMBOL, STRIKE_PR, OPTION_TYP, OPEN_INT columns —
        the shape GreeksEngine.process_dataframe emits.
        Returns {symbol: {"call_wall": float, "put_wall": float, "gamma_flip": float}}.
        """
        if greeks_df.empty:
            return {}
        out = {}
        for symbol, group in greeks_df.groupby('SYMBOL'):
            ce_oi = group[group['OPTION_TYP'] == 'CE'].groupby('STRIKE_PR')['OPEN_INT'].sum()
            pe_oi = group[group['OPTION_TYP'] == 'PE'].groupby('STRIKE_PR')['OPEN_INT'].sum()

            ce_oi_pos = ce_oi[ce_oi > 0]
            pe_oi_pos = pe_oi[pe_oi > 0]
            call_wall = float(ce_oi_pos.idxmax()) if not ce_oi_pos.empty else 0.0
            put_wall = float(pe_oi_pos.idxmax()) if not pe_oi_pos.empty else 0.0

            overlap = pd.concat([ce_oi, pe_oi], axis=1).min(axis=1)
            overlap_pos = overlap[overlap > 0]
            gamma_flip = float(overlap_pos.idxmax()) if not overlap_pos.empty else 0.0

            out[symbol] = {"call_wall": call_wall, "put_wall": put_wall, "gamma_flip": gamma_flip}
        return out

    @staticmethod
    def gamma_regime(spot: float, gamma_flip: float, gex_total: float) -> str:
        """
        Scale-free gamma regime: spot vs gamma flip (absolute GEX thresholds
        aren't comparable across symbols of very different notional size).
        0.8% band around the flip reads as TRANSITION_REGIME rather than
        flapping LONG/SHORT on noise right at the pivot.

        Shared by daily_compiler.py (EOD), vanguard/core/market_structure_engine.py
        (time-travel recompute), and the live structure engine — one formula,
        three callers, so they can never silently diverge.
        """
        if gamma_flip > 0 and spot > 0:
            if abs(spot - gamma_flip) / spot <= 0.008:
                return "TRANSITION_REGIME"
            return "LONG_GAMMA" if spot > gamma_flip else "SHORT_GAMMA"
        # Fallback when no flip strike exists: polarity of total GEX
        if gex_total > 0:
            return "LONG_GAMMA"
        if gex_total < 0:
            return "SHORT_GAMMA"
        return "TRANSITION_REGIME"

    def analyze_market_structure(self, file_t, file_t_minus_1, export_path="data/processed"):
        print(f"[*] Deep Dive Analysis: {os.path.basename(file_t)} vs {os.path.basename(file_t_minus_1)}")
        
        # 1. Get Base Data
        df_t, df_fut_t = self.processor.normalize(file_t)
        df_tm1, df_fut_tm1 = self.processor.normalize(file_t_minus_1)

        # ── Expiry-Aware Filter ──────────────────────────────────────────────────
        # For index options (IDO), a weekly expiry series disappears overnight
        # every week (MIDCPNIFTY Mon, FINNIFTY Tue, BANKNIFTY Wed, NIFTY Thu).
        # Without this filter the system would subtract a huge expired-weekly OI
        # block from T-1, producing a massive false delta signal for every index.
        # STO (stocks) are left untouched — they roll naturally to the next month.
        common_expiries, dropped_expiries = self.processor.get_common_expiries(df_t, df_tm1)
        expiry_filtered = len(dropped_expiries) > 0

        if expiry_filtered:
            dropped_str = ", ".join(sorted([str(d.date()) for d in dropped_expiries]))
            print(f"[*] Weekly Expiry Rollover Detected — filtering {len(dropped_expiries)} expired series from T-1:")
            print(f"    Dropped: {dropped_str}")
            df_tm1 = self.processor.filter_tm1_to_common_expiries(df_tm1, common_expiries)
        # ────────────────────────────────────────────────────────────────────────

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
            # OI-weighted IV: an unweighted mean lets dust — deep-OTM strikes that
            # often carry a hardcoded 0.20 fallback IV — pull the aggregate as hard
            # as the liquid, OI-heavy strikes that actually drive the chain.
            # Measured: NIFTY's unweighted mean IV was 2x its OI-weighted true IV.
            df_greeks = df_greeks.copy()
            df_greeks['IV_X_OI'] = df_greeks['IV'] * df_greeks['OPEN_INT']

            summary = df_greeks.groupby(['SYMBOL', 'OPTION_TYP']).agg({
                'OPEN_INT': 'sum',
                'CHG_IN_OI': 'sum',
                'VOLUME': 'sum',
                'IV_X_OI': 'sum',
                'GAMMA': 'sum',
                'CLOSE': 'mean' # Avg option price
            }).unstack()
            # Flatten columns: ('OPEN_INT', 'CE'), ('OPEN_INT', 'PE')
            summary.columns = [f"{c[0]}_{c[1]}" for c in summary.columns]

            for side in ('CE', 'PE'):
                oi_col, ivoi_col = f'OPEN_INT_{side}', f'IV_X_OI_{side}'
                if oi_col in summary.columns and ivoi_col in summary.columns:
                    summary[f'IV_{side}'] = (
                        summary[ivoi_col] / summary[oi_col].replace(0, np.nan)
                    ).fillna(0.0)
                    summary = summary.drop(columns=[ivoi_col])
            return summary

        metrics_t = get_detailed_metrics(greeks_t, spots_t)
        metrics_tm1 = get_detailed_metrics(greeks_tm1, spots_tm1)
        
        # Defensive check: Inject zero-filled fallbacks for missing columns in one-sided option chains
        expected_cols = [
            'OPEN_INT_CE', 'OPEN_INT_PE',
            'CHG_IN_OI_CE', 'CHG_IN_OI_PE',
            'VOLUME_CE', 'VOLUME_PE',
            'IV_CE', 'IV_PE',
            'GAMMA_CE', 'GAMMA_PE',
            'CLOSE_CE', 'CLOSE_PE'
        ]
        for col in expected_cols:
            if col not in metrics_t.columns:
                metrics_t[col] = 0.0
            if col not in metrics_tm1.columns:
                metrics_tm1[col] = 0.0
        
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
        # Add Spot Price Info
        final['SPOT_T'] = final.index.map(spots_t)
        final['SPOT_TM1'] = final.index.map(spots_tm1)
        final['SPOT_CHG_PCT'] = ((final['SPOT_T'] - final['SPOT_TM1']) / final['SPOT_TM1']) * 100

        # Aggregate and merge futures open interest metrics
        if not df_fut_t.empty:
            fut_t_grouped = df_fut_t.groupby('SYMBOL').agg({
                'OPEN_INT': 'sum',
                'CHG_IN_OI': 'sum'
            }).rename(columns={'OPEN_INT': 'FUT_OI_T', 'CHG_IN_OI': 'FUT_CHG_OI_T'})
            final = pd.merge(final, fut_t_grouped, on='SYMBOL', how='left')
        else:
            final['FUT_OI_T'] = 0.0
            final['FUT_CHG_OI_T'] = 0.0
            
        final['FUT_OI_T'] = final['FUT_OI_T'].fillna(0.0)
        final['FUT_CHG_OI_T'] = final['FUT_CHG_OI_T'].fillna(0.0)

        # --- INVENTORY IMBALANCE METRICS ---
        # 1. PCR Calculation (Put OI / Call OI)
        final['PCR_T'] = final['OPEN_INT_PE_T'] / final['OPEN_INT_CE_T'].replace(0, 1)
        final['PCR_TM1'] = final['OPEN_INT_PE_TM1'] / final['OPEN_INT_CE_TM1'].replace(0, 1)
        final['PCR_SHIFT'] = final['PCR_T'] - final['PCR_TM1']
        
        # 2. Net Bullish Inventory Addition (Put OI added - Call OI added)
        final['NET_BULL_INV_SHIFT'] = final['CHG_IN_OI_PE_T'] - final['CHG_IN_OI_CE_T']

        # Diagnostic only, not wired into NET_BULL_INV_SHIFT/IFS: a premium-verified
        # read of the same flow (verified_oi_flow). A full-history forward-return
        # backtest (vanguard/research/ifs_verified_flow_backtest.py) showed it failing
        # the same monotonicity gate flip_backtester.py uses, so production keeps
        # the raw-OI-sign formula above despite its weaker economic justification —
        # see data/research/ifs_verified_flow_validation.md for the full result.
        verified_flow = self.verified_oi_flow(df_t)
        final = final.join(verified_flow)
        final['VERIFIED_CE_FLOW'] = final['VERIFIED_CE_FLOW'].fillna(0.0)
        final['VERIFIED_PE_FLOW'] = final['VERIFIED_PE_FLOW'].fillna(0.0)

        # 6. Interpretation Logic
        flow = self.classify_oi_flow(df_t)
        final = final.join(flow)
        final['CE_INTERP'] = final['CE_INTERP'].fillna("Neutral")
        final['PE_INTERP'] = final['PE_INTERP'].fillna("Neutral")

        # 7. Gamma Structure Change
        analyzer = GammaAnalyzer()
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
            
            # Bull Put Spread: Put Writing. The spot direction is not re-checked here —
            # PE_INTERP is now decided from the put's own premium, which already
            # carries the direction the old SPOT_CHG_PCT gate was standing in for.
            if "Put Writing" in row['PE_INTERP']:
                return "Bull Put Spread (Credit)"

            # Bear Call Spread: Call Writing
            if "Call Writing" in row['CE_INTERP']:
                return "Bear Call Spread (Credit)"

            return "Wait for Setup"

        final['SUGGESTED_STRATEGY'] = final.apply(suggest_strategy, axis=1)

        # Expose LOT_SIZE so downstream compilers can scale contracts to shares
        # Expose LOT_SIZE so downstream compilers can scale contracts to shares
        final['LOT_SIZE'] = final['SYMBOL'].map(lambda x: lots.get(x, 1.0))

        # --- EXPORT RAW GREEKS FOR DASHBOARD ---
        if export_path:
            os.makedirs(export_path, exist_ok=True)
            # We also need the lot sizes and spots inside the greeks file so Streamlit can calculate GEX
            greeks_t['LOT_SIZE'] = greeks_t['SYMBOL'].map(lambda x: lots.get(x, 1))
            greeks_t['SPOT'] = greeks_t['SYMBOL'].map(spots_t)
            
            # Pre-calculate GEX for the dashboard (saves streamlit from having to do it)
            greeks_t['MULTIPLIER'] = greeks_t['OPTION_TYP'].apply(lambda x: 1 if x == 'CE' else -1)
            greeks_t['GEX'] = greeks_t['GAMMA'] * greeks_t['OPEN_INT'] * greeks_t['SPOT'] * 0.01 * greeks_t['MULTIPLIER']
            
            greeks_t.to_csv(os.path.join(export_path, "greeks.csv"), index=False)
        
        # --- OVERRIDE WALLS WITH RAW-OI WALLS ---
        # Replaces the earlier max_ce/max_pe (per-expiry, not the combined
        # candidate set below) with the shared, validated implementation.
        # Shared with the live structure engine — see compute_walls_and_flip above.
        walls_and_flip = self.compute_walls_and_flip(greeks_t)
        for symbol, wf in walls_and_flip.items():
            final.loc[final['SYMBOL'] == symbol, 'CALL_WALL_T'] = wf['call_wall']
            final.loc[final['SYMBOL'] == symbol, 'PUT_WALL_T'] = wf['put_wall']
            final.loc[final['SYMBOL'] == symbol, 'GAMMA_FLIP_T'] = wf['gamma_flip']

        # ── Attach expiry rollover metadata ─────────────────────────────────────
        # Downstream (daily_compiler.py) reads these to persist the flag in
        # session_history so the UI can show a "Weekly Expiry Rollover" banner
        # on the exact days the filter was active.
        final['EXPIRY_FILTERED'] = expiry_filtered
        final['DROPPED_EXPIRY_DATES'] = (
            ", ".join(sorted([str(d.date()) for d in dropped_expiries]))
            if expiry_filtered else ""
        )
        # ────────────────────────────────────────────────────────────────────────

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

