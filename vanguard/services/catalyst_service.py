"""
catalyst_service.py — Fetch news, match F&O symbols, score impact.

Pipeline:
  1. Fetch headlines from RSS feeds (ET Markets, MoneyControl, NSE)
  2. Match symbols & sectors from F&O universe
  3. Score impact:
       - If GEMINI_API_KEY in env → use Gemini 1.5 Flash (AI mode)
       - Otherwise             → use keyword rules (offline mode)
  4. Return list[CatalystEntry] — caller writes daily_catalysts.json

Usage (standalone):
    from vanguard.services.catalyst_service import run_catalyst_scan
    results = run_catalyst_scan(fno_symbols={"TCS","INFY",...}, date="2026-06-25")
"""
from __future__ import annotations

import json
import os
import re
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone, timedelta
from pathlib import Path

import feedparser

# ─────────────────────────────────────────────────────────────────────────────
# Environment loader (fallback for python-dotenv)
# ─────────────────────────────────────────────────────────────────────────────
def _load_env() -> None:
    """Manually load environment variables from .env file in the project root."""
    try:
        current = Path(__file__).resolve().parent
        for _ in range(5):
            env_path = current / ".env"
            if env_path.exists():
                with open(env_path, "r", encoding="utf-8") as f:
                    for line in f:
                        line = line.strip()
                        if not line or line.startswith("#"):
                            continue
                        if "=" in line:
                            key, val = line.split("=", 1)
                            val = val.strip().strip("'\"")
                            os.environ[key.strip()] = val
                break
            current = current.parent
    except Exception as e:
        print(f"[CATALYST] Warning: Failed to load .env: {e}")

_load_env()

# Data model
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class CatalystEntry:
    headline:    str
    source:      str
    published:   str           # "HH:MM IST" or "DD-Mon-YYYY HH:MM IST"
    url:         str
    impact:      str           # BULLISH | BEARISH | NEUTRAL | MIXED
    confidence:  float         # 0.0 – 1.0
    affected_symbols: list[str]
    affected_sectors: list[str]
    reason:      str
    suggestion:  str
    mode:        str           # "AI" | "RULES"

    def to_dict(self) -> dict:
        return asdict(self)


# ─────────────────────────────────────────────────────────────────────────────
# RSS Feed sources
# ─────────────────────────────────────────────────────────────────────────────

RSS_FEEDS: list[dict] = [
    {
        "name":  "Economic Times Markets",
        "url":   "https://economictimes.indiatimes.com/markets/rssfeeds/1977021501.cms",
        "focus": "broad",
    },
    {
        "name":  "MoneyControl News",
        "url":   "https://www.moneycontrol.com/rss/marketreports.xml",
        "focus": "broad",
    },
    {
        "name":  "NSE Corporate Announcements",
        "url":   "https://www.nseindia.com/xml-data/corpInfo/equities/corp_annfeed.xml",
        "focus": "corporate",
    },
    {
        "name":  "Mint Markets",
        "url":   "https://www.livemint.com/rss/markets",
        "focus": "broad",
    },
]

# Max headlines to fetch per feed
MAX_PER_FEED = 20
# Minimum confidence to include in the report
MIN_CONFIDENCE = 0.35


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

def _ist_now_str() -> str:
    ist = datetime.now(timezone(timedelta(hours=5, minutes=30)))
    return ist.strftime("%d-%b-%Y %H:%M IST")


def _parse_published(entry) -> str:
    """Extract human-readable published time from a feedparser entry."""
    try:
        if hasattr(entry, "published_parsed") and entry.published_parsed:
            dt = datetime(*entry.published_parsed[:6], tzinfo=timezone.utc)
            ist = dt.astimezone(timezone(timedelta(hours=5, minutes=30)))
            return ist.strftime("%d-%b-%Y %H:%M IST")
    except Exception:
        pass
    return _ist_now_str()


def _clean_html(text: str) -> str:
    """Strip HTML tags from feed summaries."""
    return re.sub(r"<[^>]+>", "", str(text)).strip()


_RSS_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept": "application/rss+xml, application/xml, text/xml, */*",
}


def _fetch_headlines() -> list[dict]:
    """
    Fetch from all RSS feeds using browser headers to bypass User-Agent blocks.
    Returns list of {title, summary, source, published, url}.
    Gracefully skips any feed that fails or returns non-200.
    """
    import requests

    all_items: list[dict] = []
    seen_titles: set[str] = set()

    for feed_cfg in RSS_FEEDS:
        try:
            resp = requests.get(
                feed_cfg["url"], headers=_RSS_HEADERS, timeout=10
            )
            if resp.status_code != 200:
                continue
            feed = feedparser.parse(resp.content)
            for entry in feed.entries[:MAX_PER_FEED]:
                title = _clean_html(getattr(entry, "title", ""))
                if not title or title.lower() in seen_titles:
                    continue
                seen_titles.add(title.lower())
                summary = _clean_html(getattr(entry, "summary", ""))
                all_items.append({
                    "title":     title,
                    "summary":   summary,
                    "source":    feed_cfg["name"],
                    "published": _parse_published(entry),
                    "url":       getattr(entry, "link", ""),
                })
        except Exception:
            # Network failure, malformed feed — skip silently
            pass

    return all_items


# ─────────────────────────────────────────────────────────────────────────────
# AI Analysis (Gemini)
# ─────────────────────────────────────────────────────────────────────────────

def _build_gemini_prompt(headlines: list[dict], fno_symbols: set[str]) -> str:
    symbol_list = ", ".join(sorted(fno_symbols)[:150])  # cap to avoid token overflow
    headline_block = "\n".join(
        f"{i+1}. [{h['source']}] {h['title']}"
        for i, h in enumerate(headlines)
    )
    return f"""You are a senior NSE equity analyst. Analyze these market news headlines 
and identify which ones could have a material impact on any of the listed F&O stocks or 
index sectors.

F&O UNIVERSE SYMBOLS (NSE):
{symbol_list}

TODAY'S HEADLINES:
{headline_block}

For each headline that has a SIGNIFICANT impact (skip generic/noise headlines), 
return a JSON array. Each element must have EXACTLY these fields:
{{
  "headline_index": <1-based int>,
  "impact": "BULLISH" | "BEARISH" | "NEUTRAL" | "MIXED",
  "confidence": <float 0.0-1.0>,
  "affected_symbols": [<NSE symbol strings only from the universe above>],
  "affected_sectors": [<NSE sector index names e.g. "NIFTY IT", "NIFTY AUTO">],
  "reason": "<1-2 sentence analyst rationale>",
  "suggestion": "<1 sentence actionable trading note>"
}}

Rules:
- Only include symbols from the F&O universe list provided.
- Skip headlines with confidence < 0.4 (pure noise, generic market commentary).
- If a headline affects only indices (NIFTY/BANKNIFTY), set affected_symbols=["NIFTY"] or ["BANKNIFTY"].
- Be precise. Fewer high-conviction entries are better than many weak ones.
- Return ONLY the JSON array. No markdown, no explanation outside the JSON.
"""


def _analyze_with_gemini(
    headlines: list[dict],
    fno_symbols: set[str],
    api_key: str,
) -> list[dict]:
    """Call Gemini Flash to score headlines. Returns list of analysis dicts."""
    import time
    try:
        from google import genai
        from google.genai import types
    except ImportError as e:
        print(f"[CATALYST] ImportError ({e}) — falling back to keyword rules.")
        return []

    max_retries = 3
    delay = 2

    for attempt in range(max_retries):
        try:
            client = genai.Client(api_key=api_key)
            prompt = _build_gemini_prompt(headlines, fno_symbols)
            response = client.models.generate_content(
                model="gemini-3.5-flash",
                contents=prompt,
                config=types.GenerateContentConfig(temperature=0.1),
            )
            text = response.text.strip()
            # Strip markdown code fences if present
            text = re.sub(r"^```[a-z]*\n?", "", text)
            text = re.sub(r"\n?```$", "", text)
            return json.loads(text)
        except Exception as e:
            if attempt < max_retries - 1:
                print(f"[CATALYST] Gemini attempt {attempt + 1} failed ({e}). Retrying in {delay}s...")
                time.sleep(delay)
                delay *= 2
            else:
                print(f"[CATALYST] Gemini error after {max_retries} attempts ({e}) — falling back to keyword rules.")
                return []
    return []


# ─────────────────────────────────────────────────────────────────────────────
# Rules-based Analysis
# ─────────────────────────────────────────────────────────────────────────────

def _analyze_with_rules(
    headlines: list[dict],
    fno_symbols: set[str],
) -> list[dict]:
    """Score each headline using keyword rules + name matching."""
    from vanguard.core.catalyst_rules import (
        score_headline_keywords,
        match_symbols_in_headline,
        match_sectors_in_headline,
        CONTEXTUAL_RULES,
        SECTOR_TO_SYMBOLS,
    )

    results = []
    for i, h in enumerate(headlines):
        full_text = f"{h['title']} {h['summary']}"
        tl = full_text.lower()

        # Check contextual rules first (highest specificity)
        contextual_hit = None
        for rule in CONTEXTUAL_RULES:
            if any(kw in tl for kw in rule["keywords"]):
                contextual_hit = rule
                break

        if contextual_hit:
            # Build per-sector analysis from contextual rule
            for sector, (impact, reason) in contextual_hit["sector_impacts"].items():
                syms = [s for s in SECTOR_TO_SYMBOLS.get(sector, []) if s in fno_symbols]
                if not syms and sector in ("NIFTY", "BANKNIFTY"):
                    syms = [sector]
                results.append({
                    "headline_index": i + 1,
                    "impact":          impact,
                    "confidence":      0.75,
                    "affected_symbols": syms,
                    "affected_sectors": [sector],
                    "reason":          reason,
                    "suggestion":      f"Monitor {sector} for {impact.lower()} price action at the open.",
                })
            continue

        # General keyword scoring
        impact, reason_frag, conf = score_headline_keywords(full_text)
        if conf < MIN_CONFIDENCE or impact == "NEUTRAL":
            continue

        affected_syms    = match_symbols_in_headline(full_text, fno_symbols)
        affected_sectors = match_sectors_in_headline(full_text)

        # If sectors matched but no direct symbols, expand via sector map
        if not affected_syms and affected_sectors:
            for sec in affected_sectors:
                affected_syms += [
                    s for s in SECTOR_TO_SYMBOLS.get(sec, []) if s in fno_symbols
                ]
            affected_syms = sorted(set(affected_syms))

        if not affected_syms and not affected_sectors:
            continue  # No F&O relevance detected

        # Build suggestion
        if affected_syms:
            targets = ", ".join(affected_syms[:4])
            suggestion = (
                f"Watch {targets} for {impact.lower()} reaction at open. "
                f"Confirm with live price action before initiating."
            )
        else:
            suggestion = (
                f"Monitor {', '.join(affected_sectors[:2])} sector at open for {impact.lower()} follow-through."
            )

        results.append({
            "headline_index":  i + 1,
            "impact":          impact,
            "confidence":      conf,
            "affected_symbols": list(dict.fromkeys(affected_syms)),
            "affected_sectors": affected_sectors,
            "reason":          reason_frag,
            "suggestion":      suggestion,
        })

    return results


# ─────────────────────────────────────────────────────────────────────────────
# Main entry point
# ─────────────────────────────────────────────────────────────────────────────

def run_catalyst_scan(
    fno_symbols: set[str],
    date: str,
    output_path: str | None = None,
    quiet: bool = False,
) -> list[CatalystEntry]:
    """
    Full pipeline: fetch → analyse → assemble CatalystEntry list → write JSON.

    Parameters
    ----------
    fno_symbols : set of NSE symbols in today's F&O universe
    date        : YYYY-MM-DD session date string
    output_path : where to write daily_catalysts.json (None = skip write)
    quiet       : suppress print statements

    Returns
    -------
    list[CatalystEntry]
    """
    if not quiet:
        print("[CATALYST] Fetching news headlines...")

    headlines = _fetch_headlines()

    if not quiet:
        print(f"[CATALYST] {len(headlines)} unique headlines fetched.")

    if not headlines:
        return []

    # Choose analysis mode
    api_key = os.getenv("GEMINI_API_KEY", "").strip()
    ai_mode = os.getenv("CATALYST_AI_MODE", "").strip().lower() in ("1", "true", "yes")

    if api_key and ai_mode:
        if not quiet:
            print("[CATALYST] Using Gemini AI analysis mode.")
        raw_results = _analyze_with_gemini(headlines, fno_symbols, api_key)
        mode = "AI"
        # If Gemini returned empty (error fallback), use rules
        if not raw_results:
            raw_results = _analyze_with_rules(headlines, fno_symbols)
            mode = "RULES"
    else:
        if not quiet:
            print("[CATALYST] Using keyword rules analysis mode.")
        raw_results = _analyze_with_rules(headlines, fno_symbols)
        mode = "RULES"

    # Assemble CatalystEntry objects
    entries: list[CatalystEntry] = []
    for res in raw_results:
        idx = res.get("headline_index", 1) - 1
        if idx < 0 or idx >= len(headlines):
            continue
        h = headlines[idx]
        conf = float(res.get("confidence", 0.0))
        if conf < MIN_CONFIDENCE:
            continue

        entries.append(CatalystEntry(
            headline          = h["title"],
            source            = h["source"],
            published         = h["published"],
            url               = h["url"],
            impact            = res.get("impact", "NEUTRAL"),
            confidence        = round(conf, 2),
            affected_symbols  = res.get("affected_symbols", []),
            affected_sectors  = res.get("affected_sectors", []),
            reason            = res.get("reason", ""),
            suggestion        = res.get("suggestion", ""),
            mode              = mode,
        ))

    # Deduplicate by headline + impact combo
    seen: set[str] = set()
    unique_entries: list[CatalystEntry] = []
    for e in entries:
        key = f"{e.headline[:60]}|{e.impact}"
        if key not in seen:
            seen.add(key)
            unique_entries.append(e)

    # Sort: highest confidence first, BEARISH before BULLISH (risk-first)
    unique_entries.sort(
        key=lambda e: (-(e.confidence), 0 if e.impact == "BEARISH" else 1)
    )

    # Write to JSON if requested
    if output_path:
        payload = {
            "date":       date,
            "generated":  _ist_now_str(),
            "mode":       mode,
            "count":      len(unique_entries),
            "catalysts":  [e.to_dict() for e in unique_entries],
        }
        Path(output_path).parent.mkdir(parents=True, exist_ok=True)
        with open(output_path, "w", encoding="utf-8") as f:
            json.dump(payload, f, indent=2, ensure_ascii=False)
        if not quiet:
            print(f"[CATALYST] {len(unique_entries)} catalysts written → {output_path}")

    return unique_entries


# ─────────────────────────────────────────────────────────────────────────────
# Load cached JSON (for UI / briefing rendering)
# ─────────────────────────────────────────────────────────────────────────────

def load_catalysts(path: str) -> dict:
    """
    Load daily_catalysts.json. Returns the raw dict or {} if not found.
    Safe to call from Streamlit — no network requests.
    """
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {}
