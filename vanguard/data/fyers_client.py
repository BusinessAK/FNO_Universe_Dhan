"""
Thin wrapper over the official fyers-apiv3 SDK. This is a skeleton implementation 
prepared for the Phase 4 Fyers migration.
It matches the interface exposed by DhanClient.
"""
from __future__ import annotations

import os
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def _load_env():
    """Minimal .env loader."""
    env = ROOT / ".env"
    if env.exists():
        for line in env.read_text().splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                os.environ[k.strip()] = v.strip().strip('"').strip("'")


class FyersClient:
    """Auth + REST + feed factory for Fyers."""

    def __init__(self, client_id: str | None = None, access_token: str | None = None):
        _load_env()
        self.client_id = client_id or os.environ.get("FYERS_CLIENT_ID") or os.environ.get("FYERS_APP_ID")
        self.access_token = access_token or os.environ.get("FYERS_ACCESS_TOKEN")
        if not self.client_id or not self.access_token:
            raise RuntimeError(
                "Fyers credentials missing — set FYERS_CLIENT_ID and FYERS_ACCESS_TOKEN in .env"
            )
        
        from fyers_apiv3 import fyersModel
        self.rest = fyersModel.FyersModel(
            client_id=self.client_id, 
            is_async=False, 
            token=self.access_token, 
            log_path=""
        )

    def check_auth(self) -> tuple[bool, str]:
        """Cheap live auth probe."""
        try:
            res = self.rest.get_profile()
            if res.get("s") == "ok":
                return True, f"authenticated as {res.get('data', {}).get('name', 'user')}"
            return False, f"auth response: {res}"
        except Exception as e:
            return False, f"auth error: {e}"

    def _fetch_history(self, symbol: str, resolution: str, from_date: str, to_date: str) -> dict:
        data = {
            "symbol": symbol,
            "resolution": resolution,
            "date_format": "1",
            "range_from": from_date,
            "range_to": to_date,
            "cont_flag": "1"
        }
        res = self.rest.history(data=data)
        if res.get("s") == "ok":
            candles = res.get("candles", [])
            # Convert to Dhan-like format for compatibility if needed, but Fyers returns [[epoch, o, h, l, c, v]]
            return {"status": "success", "data": candles}
        return {"status": "error", "data": res}

    def option_chain(self, under_security_id: str, under_segment: str, expiry: str) -> dict:
        """Permanent no-op, not a TODO: Fyers has no single REST call for an
        entire option chain, so this can never be filled in the way the old
        DhanClient.option_chain() was. Live chains are served instead from
        vanguard.live.live_compute.compute()'s in-memory chains_json, wired
        through vanguard.serve.api's /api/chain/<symbol> — see Bridge's
        live_chains_cache. This stub only exists so callers written against
        the DhanClient interface don't crash."""
        return {"status": "success", "data": {"oc": {}}}

    def daily(self, security_id: str, segment: str, instrument_type: str,
              from_date: str, to_date: str, oi: bool = False) -> dict:
        return self._fetch_history(security_id, "D", from_date, to_date)

    def intraday(self, security_id: str, segment: str, instrument_type: str,
                 from_date: str, to_date: str, interval: int = 5, oi: bool = False) -> dict:
        return self._fetch_history(security_id, str(interval), from_date, to_date)

    def market_feed(self, instruments: list, on_ticks=None, on_connect=None,
                    on_close=None, on_error=None):
        """WebSocket feed factory."""
        from fyers_apiv3.FyersWebsocket import data_ws
        
        # Fyers requires 'app_id:access_token' format for WS access_token
        ws_token = f"{self.client_id}:{self.access_token}"
        
        ws = data_ws.FyersDataSocket(
            access_token=ws_token,
            log_path="",
            litemode=False,
            write_to_file=False,
            reconnect=True,
            on_connect=on_connect,
            on_close=on_close,
            on_error=on_error,
            on_message=on_ticks
        )
        # We do not call ws.subscribe() here because FyersDataSocket requires connection first.
        # Subscribe logic is usually called inside on_connect.
        # But we can attach the symbols to the ws object for on_connect to use.
        ws._vanguard_instruments = instruments
        return ws
