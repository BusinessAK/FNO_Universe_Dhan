"""
Platform API — the localhost read server for the EOD terminal.

    /                 hud/vanguard_hud.html (the baked artifact)
    /session/latest   the EOD payload from store.export_service — the SAME
                      builder build_hud bakes, so served and baked data
                      cannot drift. Cached, invalidated on DB mtime change.

The live /snapshot overlay was removed when the intraday layer was archived
(see archive/live/); this now serves purely static EOD data. Start it with
scripts/serve_hud.py.
"""
from __future__ import annotations

import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from vanguard.config.paths import DB, HUD, BRIDGE_HOST, BRIDGE_PORT

HUD_FILE = HUD / "vanguard_hud.html"

_payload_lock = threading.Lock()
_payload_cache: dict = {"mtime": None, "body": None}


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
        elif path == "/session/latest":
            body = session_payload_bytes()
            if body is None:
                self._send(503, b'{"error":"no compiled database"}', "application/json")
            else:
                self._send(200, body, "application/json")
        else:
            self._send(404, b"not found", "text/plain")


class Bridge:
    def __init__(self, host: str = BRIDGE_HOST, port: int = BRIDGE_PORT):
        self.host, self.port = host, port
        self._srv = None

    def start(self):
        self._srv = ThreadingHTTPServer((self.host, self.port), _Handler)
        t = threading.Thread(target=self._srv.serve_forever, daemon=True)
        t.start()
        print(f"[server] serving HUD + /session/latest at "
              f"http://{self.host}:{self.port}/")
        return t

    def serve_forever(self):
        """Blocking start — for a foreground `scripts/serve_hud.py` process."""
        self._srv = ThreadingHTTPServer((self.host, self.port), _Handler)
        print(f"[server] serving HUD + /session/latest at "
              f"http://{self.host}:{self.port}/  (Ctrl-C to stop)")
        try:
            self._srv.serve_forever()
        except KeyboardInterrupt:
            print("\n[server] stopped")
