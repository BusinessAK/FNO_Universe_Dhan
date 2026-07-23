"""
Platform API (wave 3 / P1) — the bridge grown up. One localhost server for
every read surface:

    /                 hud/vanguard_hud.html (the baked artifact)
    /snapshot         live_snapshot.json (5s live overlay — unchanged contract)
    /session/latest   the EOD payload from store.export_service — the SAME
                      builder build_hud bakes, so served and baked data
                      cannot drift. Cached, invalidated on DB mtime change.

Runs in a daemon thread inside the live process (vanguard/live/bridge.py is
now a shim over this module).
"""
from __future__ import annotations

import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from vanguard.config import live as C
from vanguard.config.paths import DB, HUD

HUD_FILE = HUD / "vanguard_hud.html"

_payload_lock = threading.Lock()
_payload_cache: dict = {"mtime": None, "body": None}

_greeks_lock = threading.Lock()
_greeks_cache: dict = {"mtime": None, "df": None}

def get_chain_json(symbol: str) -> bytes | None:
    import pandas as pd
    greeks_path = Path("data/processed/greeks.csv")
    try:
        mtime = greeks_path.stat().st_mtime
    except OSError:
        return None
    with _greeks_lock:
        if _greeks_cache["mtime"] != mtime:
            try:
                _greeks_cache["df"] = pd.read_csv(greeks_path)
            except Exception:
                return None
            _greeks_cache["mtime"] = mtime
        df = _greeks_cache["df"]
    if df is None or df.empty:
        return b'[]'
    sdf = df[df["SYMBOL"] == symbol]
    if sdf.empty:
        return b'[]'
    return sdf.to_json(orient="records").encode("utf-8")



def session_payload_bytes() -> bytes | None:
    """Compact-JSON payload for /session/latest, rebuilt only when the DB
    file changes. Returns None when the DB is absent (pre-first-compile)."""
    try:
        mtime = Path(DB).stat().st_mtime
    except OSError:
        return None
    with _payload_lock:
        if _payload_cache["mtime"] != mtime:
            from vanguard.store.export_service import payload_json
            _payload_cache["body"] = payload_json().encode("utf-8")
            _payload_cache["mtime"] = mtime
        return _payload_cache["body"]


class _Handler(BaseHTTPRequestHandler):
    def log_message(self, *a):            # silence per-request logging
        pass

    def _send(self, code, body: bytes, ctype: str):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        path = self.path.split("?", 1)[0]
        if path in ("/", "/hud", "/index.html"):
            if HUD_FILE.exists():
                self._send(200, HUD_FILE.read_bytes(), "text/html; charset=utf-8")
            else:
                self._send(404, b"HUD not built", "text/plain")
        elif path == "/snapshot":
            if C.SNAPSHOT_JSON.exists():
                self._send(200, C.SNAPSHOT_JSON.read_bytes(), "application/json")
            else:
                self._send(200, b'{"market_open":false,"n":0,"quotes":{}}', "application/json")
        elif path == "/session/latest":
            body = session_payload_bytes()
            if body is None:
                self._send(503, b'{"error":"no compiled database"}', "application/json")
            else:
                self._send(200, body, "application/json")
        elif path.startswith("/api/chain/"):
            symbol = path.split("/")[-1]
            body = get_chain_json(symbol)
            if body is None:
                self._send(503, b'{"error":"no greeks data"}', "application/json")
            else:
                self._send(200, body, "application/json")
        else:
            self._send(404, b"not found", "text/plain")


class Bridge:
    def __init__(self, host: str = C.BRIDGE_HOST, port: int = C.BRIDGE_PORT):
        self.host, self.port = host, port
        self._srv = None

    def start(self):
        self._srv = ThreadingHTTPServer((self.host, self.port), _Handler)
        t = threading.Thread(target=self._srv.serve_forever, daemon=True)
        t.start()
        print(f"[bridge] serving HUD + /snapshot + /session/latest at "
              f"http://{self.host}:{self.port}/")
        return t
