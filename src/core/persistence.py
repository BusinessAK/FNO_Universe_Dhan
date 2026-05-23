class PersistenceEngine:
    """
    Decoupled engine for analyzing and styling institutional daily inventory persistence.
    Categorizes cycles into High-Conviction Bullish Accumulation, Bearish Call writing ceilings, or rotational flow.
    """
    def __init__(self, bull_threshold: int = 3, conviction_threshold: int = 5):
        self.bull_threshold = bull_threshold
        self.conviction_threshold = conviction_threshold

    def get_persistence_styles(self, bull_p: int, bear_p: int, regime_transition: bool) -> tuple:
        """
        Computes the visual grid class name and badge HTML based on persistence metrics.
        """
        sym_cell_class = ""
        badge_html = ""

        if regime_transition:
            sym_cell_class = "regime-transition-gold"
            badge_html = '<span class="persistence-badge" style="background:#4d3c00;color:#fbbf24;border:1px solid #78350f;">⭐ Transition</span>'
        elif bull_p >= self.conviction_threshold:
            sym_cell_class = "persist-glow-bull-5"
            badge_html = f'<span class="persistence-badge" style="background:#064e3b;color:#00ff66;border:1px solid #047857;">🔥 Conviction {bull_p}d</span>'
        elif bull_p >= self.bull_threshold:
            sym_cell_class = "persist-glow-bull-3"
            badge_html = f'<span class="persistence-badge" style="background:#064e3b;color:#10b981;">🔥 Bull {bull_p}d</span>'
        elif bear_p >= self.conviction_threshold:
            sym_cell_class = "persist-glow-bear-5"
            badge_html = f'<span class="persistence-badge" style="background:#4c0519;color:#ff3333;border:1px solid #9f1239;">❄️ Conviction {bear_p}d</span>'
        elif bear_p >= self.bull_threshold:
            sym_cell_class = "persist-glow-bear-3"
            badge_html = f'<span class="persistence-badge" style="background:#4c0519;color:#f43f5e;">❄️ Bear {bear_p}d</span>'
        else:
            badge_html = '<span class="persistence-badge" style="background:#141435;color:#7888aa;">⇅ Rotation</span>'

        return sym_cell_class, badge_html
