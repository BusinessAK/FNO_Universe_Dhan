"""
catalyst_service.py — Fetch news, match F&O symbols, score impact.

Pipeline:
  1. Fetch headlines from RSS feeds (ET Markets, MoneyControl, NSE)
  2. Match symbols & sectors from F&O universe
  3. Score impact, provider priority (same free-tier-first stance as
     scripts/generate_ai_summary.py):
       - NVIDIA_API_KEY set        → Nemotron Ultra (free tier)
       - else GEMINI_API_KEY set + CATALYST_AI_MODE=true → Gemini Flash
       - else                      → keyword rules (offline mode)
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

DDL = """CREATE TABLE IF NOT EXISTS daily_catalysts (
    date VARCHAR, headline VARCHAR, source VARCHAR, published VARCHAR, url VARCHAR,
    impact VARCHAR, confidence DOUBLE, affected_symbols VARCHAR, affected_sectors VARCHAR,
    reason VARCHAR, suggestion VARCHAR, mode VARCHAR)"""


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
# AI Analysis (Nemotron via NVIDIA NIM, Gemini)
# ─────────────────────────────────────────────────────────────────────────────

NEMOTRON_MODEL = "nvidia/nemotron-3-ultra-550b-a55b"
NEMOTRON_URL = "https://integrate.api.nvidia.com/v1/chat/completions"


def _strip_json_fences(text: str) -> str:
    cleaned = text.strip()
    cleaned = re.sub(r"^```[a-z]*\n?", "", cleaned)
    cleaned = re.sub(r"\n?```$", "", cleaned)
    return cleaned


def _parse_analysis(text: str, who: str) -> list[dict]:
    """Parse a model reply into the analysis-dict list the assembler expects.

    The prompt asks for a bare JSON array, but a model may wrap it
    ({"results": [...]}) or return something else entirely. An unvalidated
    parse is worse than a failure: a truthy non-list sets mode="AI", skips
    every fallback, and then blows up in the assembler's `res.get(...)`.
    Returning [] instead lets the caller fall through to the next provider.
    """
    obj = json.loads(_strip_json_fences(text))
    if isinstance(obj, dict):
        # tolerate a single wrapper key holding the array
        for v in obj.values():
            if isinstance(v, list):
                obj = v
                break
    if not isinstance(obj, list):
        print(f"[CATALYST] {who} returned {type(obj).__name__}, expected a list — falling back.")
        return []
    rows = [r for r in obj if isinstance(r, dict)]
    if len(rows) != len(obj):
        print(f"[CATALYST] {who}: dropped {len(obj) - len(rows)} non-object entries.")
    return rows


def _analyze_with_nemotron(
    headlines: list[dict],
    fno_symbols: set[str],
    api_key: str,
) -> list[dict]:
    """Call Nemotron via NVIDIA NIM (OpenAI-compatible chat completions) to
    score headlines. Returns list of analysis dicts, or [] on any failure —
    caller falls back to Gemini/rules."""
    import requests

    prompt = _build_gemini_prompt(headlines, fno_symbols)
    try:
        resp = requests.post(
            NEMOTRON_URL,
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
            json={
                "model": NEMOTRON_MODEL,
                "messages": [{"role": "user", "content": prompt}],
                "max_tokens": 8192,
                "temperature": 0.1,
            },
            timeout=240,
        )
        resp.raise_for_status()
        data = resp.json()
        choice = data["choices"][0]
        if choice.get("finish_reason") == "length":
            print("[CATALYST] Nemotron hit max_tokens — response truncated, falling back.")
            return []
        return _parse_analysis(choice["message"]["content"], "Nemotron")
    except requests.RequestException as e:
        print(f"[CATALYST] Nemotron request error ({e}) — falling back.")
        return []
    except (KeyError, IndexError, ValueError, json.JSONDecodeError) as e:
        print(f"[CATALYST] Nemotron response malformed ({e}) — falling back.")
        return []


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
                model="gemini-1.5-flash",
                contents=prompt,
                config=types.GenerateContentConfig(temperature=0.1),
            )
            return _parse_analysis(response.text, "Gemini")
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
    con=None,
) -> list[CatalystEntry]:
    """
    Full pipeline: fetch → analyse → assemble CatalystEntry list → write JSON.

    RSS feeds only ever expose *current* headlines — there is no way to fetch
    what was live on a past date. Callers MUST NOT invoke this for a backfill
    date; it fetches today's news and would mislabel it as belonging to
    `date`. Use `load_catalysts_for_date` to read back what was actually
    archived for a given session instead.

    Parameters
    ----------
    fno_symbols : set of NSE symbols in today's F&O universe
    date        : YYYY-MM-DD session date string
    output_path : where to write daily_catalysts.json (None = skip write)
    quiet       : suppress print statements
    con         : optional DuckDB connection — if given, results are also
                  upserted into daily_catalysts keyed by `date` so past
                  sessions can be looked up later (e.g. by the HUD export)

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

    # Choose analysis mode — free tier first, same stance as
    # scripts/generate_ai_summary.py: Nemotron (NVIDIA_API_KEY, free) tried
    # before Gemini (GEMINI_API_KEY, gated behind CATALYST_AI_MODE), before
    # the offline keyword-rules fallback.
    nvidia_key = os.getenv("NVIDIA_API_KEY", "").strip()
    gemini_key = os.getenv("GEMINI_API_KEY", "").strip()
    ai_mode = os.getenv("CATALYST_AI_MODE", "").strip().lower() in ("1", "true", "yes")

    raw_results: list[dict] = []
    mode = "RULES"

    if nvidia_key:
        if not quiet:
            print("[CATALYST] Using Nemotron AI analysis mode.")
        raw_results = _analyze_with_nemotron(headlines, fno_symbols, nvidia_key)
        if raw_results:
            mode = "AI"

    if not raw_results and gemini_key and ai_mode:
        if not quiet:
            print("[CATALYST] Using Gemini AI analysis mode.")
        raw_results = _analyze_with_gemini(headlines, fno_symbols, gemini_key)
        if raw_results:
            mode = "AI"

    if not raw_results:
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

    if con is not None:
        con.execute(DDL)
        # Replace the day's rows only when there is something to replace them
        # with. An empty result is usually a transient scan failure (feeds
        # down, every headline below MIN_CONFIDENCE, provider error) — wiping
        # a good archive on that would defeat the point of keeping one.
        if unique_entries:
            con.execute("DELETE FROM daily_catalysts WHERE date = ?", [date])
            rows = [
                (date, e.headline, e.source, e.published, e.url, e.impact,
                 e.confidence, json.dumps(e.affected_symbols),
                 json.dumps(e.affected_sectors), e.reason, e.suggestion, e.mode)
                for e in unique_entries
            ]
            con.executemany(
                "INSERT INTO daily_catalysts VALUES (?,?,?,?,?,?,?,?,?,?,?,?)", rows
            )
        elif not quiet:
            print(f"[CATALYST] no catalysts this run — leaving {date} archive untouched.")

    return unique_entries


def load_catalysts_for_date(con, date: str) -> dict:
    """
    Read back archived catalysts for a past session date from DuckDB.
    Returns the same shape as `load_catalysts` (raw JSON dict), or an empty
    dict if the table doesn't exist yet or nothing was archived for that date.
    """
    try:
        tables = {r[0] for r in con.execute("SHOW TABLES").fetchall()}
        if "daily_catalysts" not in tables:
            return {}
        rows = con.execute(
            "SELECT headline, source, published, url, impact, confidence, "
            "affected_symbols, affected_sectors, reason, suggestion, mode "
            "FROM daily_catalysts WHERE date = ? ORDER BY confidence DESC",
            [date],
        ).fetchall()
    except Exception:
        return {}

    if not rows:
        return {}

    catalysts = [
        {
            "headline": r[0], "source": r[1], "published": r[2], "url": r[3],
            "impact": r[4], "confidence": r[5],
            "affected_symbols": json.loads(r[6]) if r[6] else [],
            "affected_sectors": json.loads(r[7]) if r[7] else [],
            "reason": r[8], "suggestion": r[9], "mode": r[10],
        }
        for r in rows
    ]
    return {"date": date, "mode": catalysts[0]["mode"], "count": len(catalysts), "catalysts": catalysts}


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
