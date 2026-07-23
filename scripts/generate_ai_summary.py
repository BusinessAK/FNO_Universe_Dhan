#!/usr/bin/env python3
"""Generate the daily AI-interpreted EOD summary for the HUD.

Feeds briefing.build_report() (the same digest briefing.py already assembles —
breadth, positioning, setups, sector flow, corporate actions) to Claude for a
short narrative interpretation, and writes the result to
data/compiled/daily_ai_summary.json for export_service.py to embed in the HUD
payload.

Best-effort, same stance as vanguard/services/catalyst_service.py falling back
to keyword rules when GEMINI_API_KEY is absent: if ANTHROPIC_API_KEY is unset
or the API call fails, this prints a warning and exits 0 without writing a
file — the HUD's summary card just doesn't render that day. Never blocks the
EOD pipeline (poll_eod.py runs it with check=False).

Usage:
    python3 scripts/generate_ai_summary.py              # most recent compiled session
    python3 scripts/generate_ai_summary.py 2026-06-25   # specific date
"""
from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from vanguard.config.paths import COMPILED  # noqa: E402

OUT_PATH = COMPILED / "daily_ai_summary.json"
MODEL = "claude-opus-4-8"

SYSTEM_PROMPT = (
    "You are a terse markets desk analyst writing the one paragraph a trader "
    "reads before the rest of the dashboard. You will be given a full EOD "
    "quant report covering market breadth, participant positioning (FII/DII/"
    "Pro/Client), top setups, sector flow, and corporate actions. Write 3-5 "
    "sentences interpreting what actually matters today — not a recap of "
    "numbers already visible elsewhere on the dashboard. Call out genuine "
    "divergences, conviction, or risk; skip anything unremarkable. Plain "
    "prose, no headers, no bullet points, no markdown."
)


def _load_env() -> None:
    """Minimal .env loader (matches vanguard/data/dhan_client.py — avoids a
    hard python-dotenv dependency). .env is authoritative and overrides any
    pre-existing process env var of the same name."""
    env = ROOT / ".env"
    if env.exists():
        for line in env.read_text().splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                os.environ[k.strip()] = v.strip().strip('"').strip("'")


def generate_summary(report_text: str) -> str | None:
    api_key = os.getenv("ANTHROPIC_API_KEY", "").strip()
    if not api_key:
        print("[AI_SUMMARY] ANTHROPIC_API_KEY not set — skipping.")
        return None

    try:
        import anthropic
    except ImportError as e:
        print(f"[AI_SUMMARY] anthropic package not installed ({e}) — skipping.")
        return None

    try:
        client = anthropic.Anthropic(api_key=api_key)
        response = client.messages.create(
            model=MODEL,
            max_tokens=1024,
            system=SYSTEM_PROMPT,
            messages=[{"role": "user", "content": report_text}],
        )
        if response.stop_reason == "refusal":
            print("[AI_SUMMARY] Model declined to respond — skipping.")
            return None
        text = next((b.text for b in response.content if b.type == "text"), "")
        return text.strip() or None
    except anthropic.APIStatusError as e:
        print(f"[AI_SUMMARY] API error ({e.status_code}): {e.message} — skipping.")
        return None
    except anthropic.APIConnectionError as e:
        print(f"[AI_SUMMARY] Connection error ({e}) — skipping.")
        return None


def main() -> int:
    _load_env()
    from briefing import build_report, _resolve_date  # noqa: E402 (needs ROOT on sys.path)

    date_arg = sys.argv[1] if len(sys.argv) > 1 else None
    date = _resolve_date(date_arg)

    print(f"[AI_SUMMARY] Building report for {date}...")
    report_text = build_report(date)

    summary = generate_summary(report_text)
    if summary is None:
        print("[AI_SUMMARY] No summary generated this run.")
        return 0

    COMPILED.mkdir(parents=True, exist_ok=True)
    payload = {
        "date": date,
        "summary": summary,
        "model": MODEL,
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }
    OUT_PATH.write_text(json.dumps(payload, indent=2))
    print(f"[AI_SUMMARY] Wrote {OUT_PATH}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
