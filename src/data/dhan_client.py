"""
Thin wrapper over the official dhanhq SDK — the single seam between our code and
Dhan. Centralizes auth (from .env), REST calls (option chain, historical), and
the MarketFeed factory, so the rest of the platform never imports dhanhq directly.
"""
from __future__ import annotations

import os
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def _load_env():
    """Minimal .env loader (avoids a hard python-dotenv dependency)."""
    env = ROOT / ".env"
    if env.exists():
        for line in env.read_text().splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


def _ensure_ssl_certs():
    """macOS Python often lacks a CA bundle for the websockets SSL handshake
    (REST via requests works, but the feed socket fails CERTIFICATE_VERIFY).
    Point SSL_CERT_FILE at certifi's bundle so the live feed connects."""
    if "SSL_CERT_FILE" not in os.environ:
        try:
            import certifi
            os.environ["SSL_CERT_FILE"] = certifi.where()
        except Exception:
            pass


class DhanClient:
    """Auth + REST + feed factory. One instance owns the credentials."""

    def __init__(self, client_id: str | None = None, access_token: str | None = None):
        _load_env()
        _ensure_ssl_certs()
        self.client_id = client_id or os.environ.get("DHAN_CLIENT_ID")
        self.access_token = access_token or os.environ.get("DHAN_ACCESS_TOKEN")
        if not self.client_id or not self.access_token:
            raise RuntimeError(
                "Dhan credentials missing — set DHAN_CLIENT_ID and DHAN_ACCESS_TOKEN in .env"
            )
        from dhanhq import DhanContext, dhanhq
        self.ctx = DhanContext(self.client_id, self.access_token)
        self.rest = dhanhq(self.ctx)

    # ── auth health ───────────────────────────────────────────────────────
    def check_auth(self) -> tuple[bool, str]:
        """Cheap live auth probe (fund limit). Returns (ok, message)."""
        try:
            res = self.rest.get_fund_limits()
            status = res.get("status") if isinstance(res, dict) else None
            if status == "success":
                return True, "authenticated"
            return False, f"auth response: {res}"
        except Exception as e:
            return False, f"auth error: {e}"

    # ── REST: option chain (T-Sweep) ──────────────────────────────────────
    def option_chain(self, under_security_id: int, under_segment: str, expiry: str) -> dict:
        """Full-chain Greeks/IV/OI for one underlying+expiry. Rate-limited 1/3s by caller."""
        return self.rest.option_chain(under_security_id, under_segment, expiry)

    # ── REST: historical (backfill / backtest corpus) ─────────────────────
    def daily(self, security_id: int, segment: str, instrument_type: str,
              from_date: str, to_date: str, oi: bool = False) -> dict:
        return self.rest.historical_daily_data(
            security_id, segment, instrument_type, from_date, to_date, oi=oi)

    def intraday(self, security_id: int, segment: str, instrument_type: str,
                 from_date: str, to_date: str, interval: int = 5, oi: bool = False) -> dict:
        return self.rest.intraday_minute_data(
            security_id, segment, instrument_type, from_date, to_date,
            interval=interval, oi=oi)

    # ── WebSocket feed factory ────────────────────────────────────────────
    def market_feed(self, instruments: list, on_ticks=None, on_connect=None,
                    on_close=None, on_error=None):
        """instruments = [(feed_segment:int, "security_id":str, mode:int), ...]"""
        from dhanhq import MarketFeed
        return MarketFeed(self.ctx, instruments, version="v2",
                          on_ticks=on_ticks, on_connect=on_connect,
                          on_close=on_close, on_error=on_error)
