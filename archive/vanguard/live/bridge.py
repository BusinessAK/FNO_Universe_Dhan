"""Backward-compat shim (wave 3) — the bridge grew into vanguard/serve/api.py
(adds /session/latest from the shared export service). See docs/ARCHITECTURE.md."""
from vanguard.serve.api import Bridge, _Handler, HUD_FILE, C  # noqa: F401
