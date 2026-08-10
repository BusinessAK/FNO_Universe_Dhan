#!/usr/bin/env python3
"""Generate the daily AI-interpreted EOD summary for the HUD.

Feeds briefing.build_report() (the same digest briefing.py already assembles —
breadth, positioning, setups, sector flow, corporate actions) to an LLM for a
short narrative interpretation, and writes the result to
data/compiled/daily_ai_summary.json for export_service.py to embed in the HUD
payload.

Provider selection: tries NVIDIA NIM (Nemotron, NVIDIA_API_KEY — free tier)
first, then falls back to Claude (ANTHROPIC_API_KEY — paid) if unset or the
call fails. Same best-effort stance as vanguard/services/catalyst_service.py
falling back to keyword rules when GEMINI_API_KEY is absent: if neither key
is set or both calls fail, this prints a warning and exits 0 without writing
a file — the HUD's summary card just doesn't render that day. Never blocks
the EOD pipeline (poll_eod.py runs it with check=False).

Usage:
    python3 scripts/generate_ai_summary.py              # most recent compiled session
    python3 scripts/generate_ai_summary.py 2026-06-25   # specific date
"""
from __future__ import annotations

import json
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from vanguard.config.paths import COMPILED  # noqa: E402

OUT_PATH = COMPILED / "daily_ai_summary.json"
ANTHROPIC_MODEL = "claude-opus-4-8"
NEMOTRON_MODEL = "nvidia/nemotron-3-ultra-550b-a55b"
NEMOTRON_URL = "https://integrate.api.nvidia.com/v1/chat/completions"

SYSTEM_PROMPT = (
    "You are a terse markets desk analyst writing the briefing a trader reads "
    "before the rest of the dashboard. You will be given a full EOD quant "
    "report covering market breadth, participant positioning (FII/DII/Pro/"
    "Client), top setups, sector flow, and corporate actions. Interpret what "
    "actually matters today — not a recap of numbers already visible "
    "elsewhere on the dashboard. Call out genuine divergences, conviction, "
    "or risk; skip anything unremarkable.\n\n"
    "Return ONLY a JSON object with exactly these fields, no markdown fences, "
    "no text outside the JSON:\n"
    '{\n'
    '  "verdict": "<one punchy sentence, the single most important takeaway>",\n'
    '  "takeaways": ["<short standalone point>", "... 2 to 4 total"],\n'
    '  "watch": ["<up to 5 NSE ticker symbols worth watching tomorrow>"]\n'
    '}\n\n'
    "Each takeaway must be a complete, self-contained sentence a reader can "
    "scan in isolation — no partial fragments, no sentence spanning two "
    "entries. Use tickers/numbers from the report, not vague language.\n\n"
    "Two hard rules, because getting these wrong misleads a trader with real "
    "money on the line:\n"
    "1. Any percentage you state (GEX change, price change, etc.) must be "
    "computed directly from the two raw numbers in the report — (new-old)/"
    "abs(old)*100 — not eyeballed or estimated. If you are not confident in "
    "the arithmetic, omit the percentage rather than state an approximate "
    "one.\n"
    "2. Never describe a symbol as offering \"upside\", \"long\", or a "
    "bullish setup based on its gamma regime (LONG_GAMMA/SHORT_GAMMA) alone — "
    "gamma regime describes volatility/dealer-hedging behavior, not price "
    "direction. If a symbol's institutional flow score (IFS) is strongly "
    "negative, do not pair it with bullish language; describe it as a "
    "volatility setup only, or note the conflict explicitly (e.g. "
    "\"long-gamma but IFS deeply negative — vol expansion, not a directional "
    "call\")."
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


def _parse_structured(text: str) -> dict | None:
    """Parse the {verdict, takeaways, watch} JSON contract out of raw model
    output, stripping markdown code fences if the model added them anyway."""
    cleaned = text.strip()
    if cleaned.startswith("```"):
        cleaned = re.sub(r"^```[a-z]*\n?", "", cleaned)
        cleaned = re.sub(r"\n?```$", "", cleaned)
    try:
        obj = json.loads(cleaned)
    except json.JSONDecodeError:
        return None
    verdict = str(obj.get("verdict", "")).strip()
    takeaways = [str(t).strip() for t in obj.get("takeaways", []) if str(t).strip()]
    watch = [str(w).strip().upper() for w in obj.get("watch", []) if str(w).strip()]
    if not verdict or not takeaways:
        return None
    return {"verdict": verdict, "takeaways": takeaways, "watch": watch}


def _generate_with_nemotron(report_text: str, api_key: str) -> dict | None:
    import requests

    try:
        resp = requests.post(
            NEMOTRON_URL,
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
            json={
                "model": NEMOTRON_MODEL,
                "messages": [
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user", "content": report_text},
                ],
                "max_tokens": 2048,
                "temperature": 0.3,
            },
            timeout=120,
        )
        resp.raise_for_status()
        data = resp.json()
        choice = data["choices"][0]
        if choice.get("finish_reason") == "length":
            print("[AI_SUMMARY] Nemotron hit max_tokens — response truncated, skipping.")
            return None
        text = choice["message"]["content"]
        parsed = _parse_structured(text)
        if parsed is None:
            print("[AI_SUMMARY] Nemotron response wasn't valid structured JSON — falling back.")
        return parsed
    except requests.RequestException as e:
        print(f"[AI_SUMMARY] Nemotron request error ({e}) — falling back.")
        return None
    except (KeyError, IndexError, ValueError) as e:
        print(f"[AI_SUMMARY] Nemotron response malformed ({e}) — falling back.")
        return None


def _generate_with_anthropic(report_text: str, api_key: str) -> dict | None:
    try:
        import anthropic
    except ImportError as e:
        print(f"[AI_SUMMARY] anthropic package not installed ({e}) — skipping.")
        return None

    try:
        client = anthropic.Anthropic(api_key=api_key)
        response = client.messages.create(
            model=ANTHROPIC_MODEL,
            max_tokens=1024,
            system=SYSTEM_PROMPT,
            messages=[{"role": "user", "content": report_text}],
        )
        if response.stop_reason == "refusal":
            print("[AI_SUMMARY] Model declined to respond — skipping.")
            return None
        text = next((b.text for b in response.content if b.type == "text"), "")
        parsed = _parse_structured(text)
        if parsed is None:
            print("[AI_SUMMARY] Anthropic response wasn't valid structured JSON — skipping.")
        return parsed
    except anthropic.APIStatusError as e:
        print(f"[AI_SUMMARY] API error ({e.status_code}): {e.message} — skipping.")
        return None
    except anthropic.APIConnectionError as e:
        print(f"[AI_SUMMARY] Connection error ({e}) — skipping.")
        return None


def generate_summary(report_text: str) -> tuple[dict, str] | None:
    """Returns ({verdict, takeaways, watch}, model_id_used) or None if no
    provider available/succeeded."""
    nvidia_key = os.getenv("NVIDIA_API_KEY", "").strip()
    if nvidia_key:
        parsed = _generate_with_nemotron(report_text, nvidia_key)
        if parsed:
            return parsed, NEMOTRON_MODEL

    anthropic_key = os.getenv("ANTHROPIC_API_KEY", "").strip()
    if anthropic_key:
        parsed = _generate_with_anthropic(report_text, anthropic_key)
        if parsed:
            return parsed, ANTHROPIC_MODEL

    if not nvidia_key and not anthropic_key:
        print("[AI_SUMMARY] Neither NVIDIA_API_KEY nor ANTHROPIC_API_KEY set — skipping.")
    return None


def main() -> int:
    _load_env()
    from briefing import build_report, _resolve_date  # noqa: E402 (needs ROOT on sys.path)

    date_arg = sys.argv[1] if len(sys.argv) > 1 else None
    date = _resolve_date(date_arg)

    print(f"[AI_SUMMARY] Building report for {date}...")
    report_text = build_report(date)

    result = generate_summary(report_text)
    if result is None:
        print("[AI_SUMMARY] No summary generated this run.")
        return 0
    parsed, model_used = result

    COMPILED.mkdir(parents=True, exist_ok=True)
    payload = {
        "date": date,
        "verdict": parsed["verdict"],
        "takeaways": parsed["takeaways"],
        "watch": parsed["watch"],
        "model": model_used,
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }
    OUT_PATH.write_text(json.dumps(payload, indent=2))
    print(f"[AI_SUMMARY] Wrote {OUT_PATH}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
