"""
Bridge — a tiny localhost HTTP server that serves the HUD *and* the live
snapshot from the same origin, so the HUD can fetch /snapshot without CORS/file
issues. Runs in a daemon thread inside the live process.

    http://127.0.0.1:8787/           -> hud/vanguard_hud.html
    http://127.0.0.1:8787/snapshot   -> live_snapshot.json
"""
from __future__ import annotations

import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from src.live import config as C

ROOT = Path(__file__).resolve().parents[2]
HUD_FILE = ROOT / "hud" / "vanguard_hud.html"


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
        print(f"[bridge] serving HUD + /snapshot at http://{self.host}:{self.port}/")
        return t

    def stop(self):
        if self._srv:
            self._srv.shutdown()
