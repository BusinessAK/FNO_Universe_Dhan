from vanguard.config.settings import (
    NARRATIVE_BULL_PERSISTENCE, NARRATIVE_BEAR_PERSISTENCE,
    NARRATIVE_MILD_BULL, NARRATIVE_MILD_BEAR, NARRATIVE_ROTATIONAL,
    NARRATIVE_ABOVE_CALL_WALL, NARRATIVE_NEAR_CALL_WALL, NARRATIVE_NEAR_PUT_WALL, NARRATIVE_CHANNEL,
    NARRATIVE_LONG_GAMMA, NARRATIVE_SHORT_GAMMA, NARRATIVE_REGIME_FLIP
)

class NarrativeEngine:
    """
    Decoupled template-based structural narrative generator.
    Replaces monolithic conditional strings logic with centralized clean template mapping.
    """
    def __init__(self):
        pass

    def generate(self, m: dict) -> str:
        """
        Generates a comprehensive market structure intelligence narrative from raw symbol metrics.
        """
        spot = m.get("spot_close", 0.0)
        cw = m.get("call_wall", 0.0)
        pw = m.get("put_wall", 0.0)
        gf = m.get("gamma_flip", 0.0)
        bias = m.get("structural_bias", "Transition Regime")
        regime = m.get("gamma_regime", "TRANSITION_REGIME")
        bull_p = m.get("bullish_persistence", 0)
        bear_p = m.get("bearish_persistence", 0)
        suggested_strategy = m.get("suggested_strategy", "Wait for Setup")

        narrative = []

        # 1. Conviction/Persistence Insight
        if bull_p >= 3:
            narrative.append(NARRATIVE_BULL_PERSISTENCE.format(days=bull_p))
        elif bear_p >= 3:
            narrative.append(NARRATIVE_BEAR_PERSISTENCE.format(days=bear_p))
        elif bull_p > 0:
            plural = "s" if bull_p > 1 else ""
            narrative.append(NARRATIVE_MILD_BULL.format(days=bull_p, plural=plural))
        elif bear_p > 0:
            plural = "s" if bear_p > 1 else ""
            narrative.append(NARRATIVE_MILD_BEAR.format(days=bear_p, plural=plural))
        else:
            narrative.append(NARRATIVE_ROTATIONAL)

        # 2. Key Level Proximity
        if spot > cw and cw > 0:
            narrative.append(NARRATIVE_ABOVE_CALL_WALL.format(cw=cw))
        elif cw > 0 and abs(spot - cw) / spot <= 0.025:
            narrative.append(NARRATIVE_NEAR_CALL_WALL.format(cw=cw))
        elif pw > 0 and abs(spot - pw) / spot <= 0.025:
            narrative.append(NARRATIVE_NEAR_PUT_WALL.format(pw=pw))
        else:
            narrative.append(NARRATIVE_CHANNEL.format(cw=cw, pw=pw))

        # 3. Dealer Hedging Volatility Regime
        if regime == "LONG_GAMMA":
            narrative.append(NARRATIVE_LONG_GAMMA)
        elif regime == "SHORT_GAMMA":
            narrative.append(NARRATIVE_SHORT_GAMMA)
        else:
            narrative.append(NARRATIVE_REGIME_FLIP.format(gf=gf))

        # 4. Tactical Synthesis
        setups = m.get("setups", [])
        if setups:
            narrative.append(f"This specific structure triggers the <b>{' / '.join(setups)} Setup</b>. Recommended tactical strategy: <b>{suggested_strategy}</b>.")
        else:
            narrative.append(f"Tactical structure shows a <b>{bias}</b> regime. Suggested positioning: <b>{suggested_strategy}</b>.")

        return " ".join(narrative)
