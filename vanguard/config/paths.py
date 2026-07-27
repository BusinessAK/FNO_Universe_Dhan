"""Canonical filesystem layout (R2). One home for every path literal —
new code imports from here; the 48 scattered "data/..." literals migrate
opportunistically as their modules get touched (see docs/ARCHITECTURE.md)."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DATA = ROOT / "data"
RAW = DATA / "raw"
PROCESSED = DATA / "processed"
COMPILED = DATA / "compiled"
LIVE = DATA / "live"
RESEARCH = DATA / "research"
DB = COMPILED / "vanguard.duckdb"
HUD = ROOT / "hud"

# Local HUD/API server bind address (vanguard/serve/api.py).
BRIDGE_HOST, BRIDGE_PORT = "127.0.0.1", 8787
