"""
Subscription manager — turns the instrument master into Dhan MarketFeed
instrument tuples (feed_segment, "security_id", mode), respecting the
per-connection (5,000) and per-message (100) caps, and the near-ATM scoping
that keeps the options universe inside budget.

M0/M1 use spot + futures (the live tape). M2 adds scoped near-ATM options.
"""
from __future__ import annotations

from vanguard.data.instrument_master import InstrumentMaster
from vanguard.live import config as C


class SubscriptionManager:
    def __init__(self, im: InstrumentMaster | None = None):
        self.im = im or InstrumentMaster()

    # ── universe helpers ──────────────────────────────────────────────────
    def fno_underlyings(self, whitelist: list[str] | None = None) -> list[str]:
        """F&O tradable set = real underlyings with futures (test symbols dropped).
        Pass whitelist (e.g. the compiled DB's 215 symbols) to pin it exactly."""
        names = self.im.df[self.im.df.kind == "FUT"].underlying.unique()
        names = [n for n in names if "TEST" not in n.upper()]
        if whitelist is not None:
            wl = set(whitelist)
            names = [n for n in names if n in wl]
        return sorted(names)

    # ── manifests (lists of (segment, "sid", mode) tuples) ────────────────
    def spot_manifest(self, symbols: list[str], mode: int = C.MODE_QUOTE) -> list[tuple]:
        out = []
        for s in symbols:
            row = self.im.spot(s)
            if row:
                out.append((int(row["feed_segment"]), str(row["security_id"]), mode))
        return out

    # F&O default is FULL, not QUOTE: Dhan's Quote packet carries NO OI field
    # (SDK-verified, TRD_fullmap_live_v1 §0 V6) — a Quote-mode F&O subscription
    # silently starves every OI-derived metric. Observed live 2026-07-16:
    # ~1.15M ticks, zero OI all day.
    def futures_manifest(self, underlyings: list[str], mode: int = C.MODE_FULL) -> list[tuple]:
        out = []
        for u in underlyings:
            fut = self.im.futures(u)
            if not fut.empty:
                fut = fut.sort_values("expiry")               # front future
                r = fut.iloc[0]
                out.append((C.SEG_NSE_FNO, str(int(r.security_id)), mode))
        return out

    def options_manifest(self, name_spots: dict[str, float], mode: int = C.MODE_FULL) -> list[tuple]:
        """Near-ATM CE/PE for each name in name_spots={symbol: live_spot} (M2)."""
        out = []
        for sym, spot in name_spots.items():
            win = C.STRIKE_WINDOW_INDEX if sym in C.INDEX_SYMBOLS else C.STRIKE_WINDOW
            chain = self.im.near_atm(sym, spot, n_strikes=win)
            for r in chain.itertuples():
                out.append((C.SEG_NSE_FNO, str(int(r.security_id)), mode))
        return out

    # ── budget-aware packing ──────────────────────────────────────────────
    @staticmethod
    def pack_connections(instruments: list[tuple]) -> list[list[tuple]]:
        """Split into per-connection groups of ≤ WS_MAX_PER_CONN."""
        return [instruments[i:i + C.WS_MAX_PER_CONN]
                for i in range(0, len(instruments), C.WS_MAX_PER_CONN)]

    @staticmethod
    def chunks(instruments: list[tuple], size: int = C.WS_MAX_PER_MSG) -> list[list[tuple]]:
        """Split into ≤ WS_MAX_PER_MSG subscribe messages."""
        return [instruments[i:i + size] for i in range(0, len(instruments), size)]
