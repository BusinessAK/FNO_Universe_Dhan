import pandas as pd
import numpy as np

def screen_watchlist_candidates(
    df_ms: pd.DataFrame,
    df_setups: pd.DataFrame,
    df_sectors: pd.DataFrame,
    symbol_rsi: dict
) -> tuple[list, list]:
    """
    Decoupled analytics logic to screen swing and intraday watchlist candidates.
    No Streamlit imports. Safe for pure unit testing.
    """
    # 1. Identify sectors with tailwinds
    accumulation_sectors = set()
    distribution_sectors = set()
    if not df_sectors.empty:
        accumulation_sectors = set(df_sectors[df_sectors['avg_ifs'] >= 15]['sector'].tolist())
        distribution_sectors = set(df_sectors[df_sectors['avg_ifs'] <= -15]['sector'].tolist())

    # 2. Map setups by symbol
    symbol_setups = {}
    for idx, row in df_setups.iterrows():
        sym = row['symbol']
        if sym not in symbol_setups:
            symbol_setups[sym] = []
        symbol_setups[sym].append(row)

    swing_candidates = []
    intraday_candidates = []

    # 3. Process each F&O symbol
    for idx, ms_row in df_ms.iterrows():
        sym = ms_row['symbol']
        sector = ms_row['sector']
        spot = ms_row['spot_close']
        conviction = ms_row['conviction_score']
        ifs = ms_row['ifs_score']
        gamma_regime = ms_row['gamma_regime']
        gamma_flip = ms_row['gamma_flip']
        
        rsi = symbol_rsi.get(sym, np.nan)
        setups_list = symbol_setups.get(sym, [])
        setup_types = [s['setup_type'] for s in setups_list]
        
        # ── SWING FILTER ──
        # conviction_score is a 0–100 magnitude (never negative); direction
        # comes from the IFS sign, otherwise shorts can never be generated.
        is_swing_long = conviction >= 30 and ifs >= 0
        is_swing_short = conviction >= 30 and ifs < 0
        
        if is_swing_long or is_swing_short:
            has_tailwind = False
            if is_swing_long and sector in accumulation_sectors:
                has_tailwind = True
            elif is_swing_short and sector in distribution_sectors:
                has_tailwind = True
                
            if has_tailwind:
                has_swing_setup = any(stype in ['REGIME_SHIFT', 'INVENTORY_MIGRATION'] for stype in setup_types)
                if has_swing_setup:
                    for setup in setups_list:
                        if setup['setup_type'] in ['REGIME_SHIFT', 'INVENTORY_MIGRATION']:
                            trigger = setup['trigger_strike']
                            invalidation = setup['invalidation_strike']
                            bias = setup['bias']
                            stype = setup['setup_type']
                            
                            if trigger and trigger > 0:
                                pct_diff = abs(spot - trigger) / trigger
                                if pct_diff <= 0.03:
                                    swing_candidates.append({
                                        'symbol': sym,
                                        'sector': sector,
                                        'spot': spot,
                                        'conviction': conviction,
                                        'ifs': ifs,
                                        'bias': bias,
                                        'trigger': trigger,
                                        'invalidation': invalidation,
                                        'setup': stype,
                                        'pct_diff': pct_diff,
                                        'rsi': rsi,
                                        'gamma_regime': gamma_regime
                                    })

        # ── INTRADAY FILTER ──
        has_intra_setup = any(stype in ['VOLATILITY_COIL', 'PINCH_ZONE'] for stype in setup_types)
        if has_intra_setup:
            is_short_gamma = (gamma_regime == 'SHORT_GAMMA')
            is_near_flip = False
            if gamma_flip and gamma_flip > 0:
                if abs(spot - gamma_flip) / gamma_flip <= 0.005:
                    is_near_flip = True
                    
            if is_short_gamma or is_near_flip:
                if not np.isnan(rsi) and (25 <= rsi <= 75):
                    for setup in setups_list:
                        if setup['setup_type'] in ['VOLATILITY_COIL', 'PINCH_ZONE']:
                            trigger = setup['trigger_strike']
                            invalidation = setup['invalidation_strike']
                            bias = setup['bias']
                            stype = setup['setup_type']
                            
                            intraday_candidates.append({
                                'symbol': sym,
                                'sector': sector,
                                'spot': spot,
                                'conviction': conviction,
                                'ifs': ifs,
                                'bias': bias,
                                'trigger': trigger,
                                'invalidation': invalidation,
                                'setup': stype,
                                'rsi': rsi,
                                'gamma_regime': gamma_regime,
                                'gamma_flip': gamma_flip,
                                'is_short_gamma': is_short_gamma,
                                'is_near_flip': is_near_flip
                            })

    return swing_candidates, intraday_candidates
