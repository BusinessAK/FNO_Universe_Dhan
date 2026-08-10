"""
catalyst_rules.py — Keyword rules and sector→symbol mapping for the Catalyst Engine.

This is the offline / deterministic fallback. The catalyst_service.py uses
these rules when GEMINI_API_KEY is absent or CATALYST_AI_MODE is not set.
"""
from __future__ import annotations

# ─────────────────────────────────────────────────────────────────────────────
# Impact keyword lists
# ─────────────────────────────────────────────────────────────────────────────

STRONG_BULLISH = [
    "record profit", "beat estimates", "record revenue", "buyback", "bonus issue",
    "special dividend", "deal win", "contract win", "order win", "mega deal",
    "capacity expansion", "acquisition approved", "upgrade to buy",
    "fda approval", "sebi approval", "cci approval", "merger approved",
    "npa falls", "asset quality improves", "credit rating upgrade",
    "strong guidance", "outperform", "price target raised", "bullish outlook",
]

MODERATE_BULLISH = [
    "profit rises", "revenue up", "volume growth", "market share gain",
    "new product launch", "partnership", "export order", "govt order",
    "tariff cut", "import duty cut", "subsidy", "incentive scheme",
    "rate cut", "repo rate cut", "emi reduction", "positive surprise",
    "overweight", "strong buy", "stock split",
]

MODERATE_BEARISH = [
    "profit falls", "revenue decline", "margin pressure", "cost overruns",
    "miss estimates", "below expectation", "inventory buildup",
    "competition intensifies", "market share loss", "import competition",
    "price hike", "tariff hike", "import duty hike", "raw material surge",
    "underperform", "reduce", "sell rating", "downgrade", "caution",
]

STRONG_BEARISH = [
    "fraud", "scam", "cbi probe", "sebi investigation", "penalty", "fine imposed",
    "show cause notice", "corporate governance", "promoter pledge",
    "debt default", "npa rises", "credit downgrade", "rating cut",
    "factory shutdown", "plant closure", "major accident", "fire",
    "profit warning", "guidance cut", "earnings miss", "bankruptcy",
    "insolvency", "ed raid", "it raid", "gst notice",
]

# Keywords that flip sector-level interpretation
# e.g. "RBI raises rates" → BULLISH for banks, BEARISH for NBFCs/realty
CONTEXTUAL_RULES: list[dict] = [
    {
        "keywords": ["repo rate hike", "rate hike", "rbi raises rate", "rbi increases rate"],
        "sector_impacts": {
            "NIFTY PSU BANK":     ("BULLISH",  "Rate hike widens NIM for PSU banks"),
            "NIFTY PVT BANK":     ("BULLISH",  "Rate hike widens NIM for private banks"),
            "NIFTY FIN SERVICE":  ("BEARISH",  "Higher rates compress NBFC spreads"),
            "NIFTY REALTY":       ("BEARISH",  "Rate hike raises mortgage costs, dampens demand"),
            "NIFTY AUTO":         ("BEARISH",  "Higher EMIs reduce consumer vehicle demand"),
        }
    },
    {
        "keywords": ["crude oil rises", "crude surges", "brent rises", "oil prices up"],
        "sector_impacts": {
            "NIFTY OIL & GAS":    ("BULLISH",  "Upstream E&P margins improve with crude rise"),
            "NIFTY AUTO":         ("BEARISH",  "Higher input costs for auto manufacturers"),
            "NIFTY FMCG":         ("BEARISH",  "Packaging and logistics cost inflation"),
            "NIFTY INFRA":        ("BEARISH",  "Fuel cost increase pressures infra projects"),
        }
    },
    {
        "keywords": ["crude falls", "oil prices fall", "crude declines", "brent drops"],
        "sector_impacts": {
            "NIFTY OIL & GAS":    ("BEARISH",  "Upstream margin compression on crude decline"),
            "NIFTY AUTO":         ("BULLISH",  "Input cost relief, consumer sentiment improves"),
            "NIFTY FMCG":         ("BULLISH",  "Packaging cost relief"),
        }
    },
    {
        "keywords": ["rupee weakens", "rupee falls", "inr weakens", "dollar strengthens"],
        "sector_impacts": {
            "NIFTY IT":           ("BULLISH",  "USD earnings translate to higher INR revenue"),
            "NIFTY PHARMA":       ("BULLISH",  "Export revenue gains on weak rupee"),
            "NIFTY OIL & GAS":    ("BEARISH",  "Higher import bill in INR terms"),
            "NIFTY METAL":        ("MIXED",    "Export benefit but import ore cost rises"),
        }
    },
    {
        "keywords": ["gst collection record", "gst surges", "tax revenue rises"],
        "sector_impacts": {
            "NIFTY FMCG":         ("BULLISH",  "High GST collection signals strong consumption"),
            "NIFTY AUTO":         ("BULLISH",  "High GST = strong auto sales read-through"),
        }
    },
    {
        "keywords": ["sebi tightens f&o", "sebi curbs derivatives", "margin hike", "lot size increase"],
        "sector_impacts": {
            "NIFTY":              ("BEARISH",  "Margin hike reduces retail F&O participation"),
            "BANKNIFTY":          ("BEARISH",  "Lower derivatives volumes, premium compression"),
        }
    },
]

# ─────────────────────────────────────────────────────────────────────────────
# Sector → symbol mapping  (NSE F&O index composition, abridged)
# The catalyst engine will also do direct symbol-name matching from the DB.
# ─────────────────────────────────────────────────────────────────────────────

SECTOR_TO_SYMBOLS: dict[str, list[str]] = {
    "NIFTY IT": [
        "TCS", "INFY", "WIPRO", "HCLTECH", "TECHM", "LTIM", "MPHASIS",
        "COFORGE", "PERSISTENT", "KPITTECH",
    ],
    "NIFTY PSU BANK": [
        "SBIN", "BANKBARODA", "PNB", "CANBK", "UNIONBANK", "INDIANB",
        "BANKINDIA", "MAHABANK", "IDFCFIRSTB",
    ],
    "NIFTY PVT BANK": [
        "HDFCBANK", "ICICIBANK", "AXISBANK", "KOTAKBANK", "INDUSINDBK",
        "FEDERALBNK", "AUBANK", "BANDHANBNK", "RBLBANK",
    ],
    "NIFTY FIN SERVICE": [
        "BAJFINANCE", "BAJAJFINSV", "MUTHOOTFIN", "CHOLAFIN", "SHRIRAMFIN",
        "MANAPPURAM", "PNBHOUSING", "LICHSGFIN",
    ],
    "NIFTY PHARMA": [
        "SUNPHARMA", "DRREDDY", "CIPLA", "DIVISLAB", "AUROPHARMA",
        "ALKEM", "IPCALAB", "LUPIN", "TORNTPHARM", "BIOCON",
    ],
    "NIFTY AUTO": [
        "MARUTI", "TATAMOTORS", "M&M", "BAJAJ-AUTO", "HEROMOTOCO",
        "EICHERMOT", "ASHOKLEY", "TVSMOTOR", "BALKRISIND",
    ],
    "NIFTY METAL": [
        "TATASTEEL", "JSWSTEEL", "HINDALCO", "VEDL", "SAIL", "NMDC",
        "JINDALSTEL", "HINDZINC", "NATIONALUM",
    ],
    "NIFTY REALTY": [
        "DLF", "GODREJPROP", "OBEROIRLTY", "PRESTIGE", "BRIGADE",
        "MAHLIFE", "PHOENIXLTD", "SOBHA",
    ],
    "NIFTY OIL & GAS": [
        "RELIANCE", "ONGC", "IOC", "BPCL", "GAIL", "PETRONET",
        "MGL", "IGL", "HINDPETRO",
    ],
    "NIFTY FMCG": [
        "HINDUNILVR", "ITC", "NESTLEIND", "BRITANNIA", "DABUR",
        "MARICO", "EMAMILTD", "GODREJCP", "COLPAL", "TATACONSUM",
    ],
    "NIFTY INFRA": [
        "LT", "BHEL", "ADANIPORTS", "ADANIGREEN", "APLAPOLLO",
        "POLYCAB", "RVNL", "IRB", "KEC", "GMRAIRPORT",
    ],
    "NIFTY MEDIA & COMM": [
        "BHARTIARTL", "IDEA", "ZEEL", "PVR", "INOXLEISUR", "SUNTV",
    ],
}

# ─────────────────────────────────────────────────────────────────────────────
# Company name → symbol  (for fuzzy headline matching)
# ─────────────────────────────────────────────────────────────────────────────

NAME_TO_SYMBOL: dict[str, str] = {
    # IT
    "tata consultancy": "TCS", "tcs": "TCS",
    "infosys": "INFY", "wipro": "WIPRO",
    "hcl tech": "HCLTECH", "tech mahindra": "TECHM",
    "ltimindtree": "LTIM", "mphasis": "MPHASIS",
    # Banks
    "state bank": "SBIN", "sbi": "SBIN",
    "hdfc bank": "HDFCBANK", "icici bank": "ICICIBANK",
    "axis bank": "AXISBANK", "kotak": "KOTAKBANK",
    "bank of baroda": "BANKBARODA", "punjab national": "PNB",
    "indusind": "INDUSINDBK",
    # Finance
    "bajaj finance": "BAJFINANCE", "bajaj finserv": "BAJAJFINSV",
    # Pharma
    "sun pharma": "SUNPHARMA", "dr reddy": "DRREDDY",
    "cipla": "CIPLA", "divis": "DIVISLAB",
    "aurobindo": "AUROPHARMA", "lupin": "LUPIN",
    # Auto
    "maruti": "MARUTI", "tata motors": "TATAMOTORS",
    "mahindra": "M&M", "bajaj auto": "BAJAJ-AUTO",
    "hero moto": "HEROMOTOCO", "eicher": "EICHERMOT",
    "ashok leyland": "ASHOKLEY",
    # Energy
    "reliance": "RELIANCE", "ongc": "ONGC",
    "indian oil": "IOC", "bpcl": "BPCL", "gail": "GAIL",
    # Metal
    "tata steel": "TATASTEEL", "jsw steel": "JSWSTEEL",
    "hindalco": "HINDALCO", "vedanta": "VEDL",
    # FMCG
    "hindustan unilever": "HINDUNILVR", "hul": "HINDUNILVR",
    "itc": "ITC", "nestle": "NESTLEIND",
    "britannia": "BRITANNIA", "dabur": "DABUR",
    # Infra/Other
    "larsen": "LT", "l&t": "LT",
    "bharti airtel": "BHARTIARTL", "airtel": "BHARTIARTL",
    "adani ports": "ADANIPORTS", "adani green": "ADANIGREEN",
    "polycab": "POLYCAB", "tata power": "TATAPOWER",
    "ntpc": "NTPC", "power grid": "POWERGRID",
    "dlf": "DLF",
}


def score_headline_keywords(text: str) -> tuple[str, str, float]:
    """
    Rule-based impact scorer. Returns (impact, direction, confidence).
    impact    : 'BULLISH' | 'BEARISH' | 'NEUTRAL' | 'MIXED'
    direction : human-readable reason fragment
    confidence: 0.0–1.0
    """
    tl = text.lower()

    sb_hits = sum(1 for kw in STRONG_BULLISH  if kw in tl)
    mb_hits = sum(1 for kw in MODERATE_BULLISH if kw in tl)
    mr_hits = sum(1 for kw in MODERATE_BEARISH if kw in tl)
    sr_hits = sum(1 for kw in STRONG_BEARISH   if kw in tl)

    bull_score = sb_hits * 2 + mb_hits
    bear_score = sr_hits * 2 + mr_hits

    if bull_score == 0 and bear_score == 0:
        return "NEUTRAL", "No strong directional keywords detected", 0.3

    total = bull_score + bear_score
    if bull_score > bear_score:
        conf = min(0.5 + (bull_score / total) * 0.5, 0.95)
        strength = "Strong" if sb_hits > 0 else "Moderate"
        return "BULLISH", f"{strength} bullish signal", round(conf, 2)
    elif bear_score > bull_score:
        conf = min(0.5 + (bear_score / total) * 0.5, 0.95)
        strength = "Strong" if sr_hits > 0 else "Moderate"
        return "BEARISH", f"{strength} bearish signal", round(conf, 2)
    else:
        return "MIXED", "Conflicting bullish and bearish signals", 0.4


def match_symbols_in_headline(
    text: str,
    fno_universe: set[str],
) -> list[str]:
    """
    Returns list of F&O universe symbols that appear (by name or ticker)
    in the headline text.
    """
    import re as _re
    tl = text.lower()
    matched = set()

    # Direct symbol match (e.g. "TCS", "INFY") — bounded so "ITC" doesn't match
    # inside "Fitch", "IOC" inside "sociocultural", etc. Lookarounds instead of
    # \b because symbols may contain non-word chars (M&M, BAJAJ-AUTO).
    for sym in fno_universe:
        pattern = r"(?<![a-z0-9])" + _re.escape(sym.lower()) + r"(?![a-z0-9])"
        if _re.search(pattern, tl):
            matched.add(sym)

    # Company name match
    for name, sym in NAME_TO_SYMBOL.items():
        pattern = r"(?<![a-z0-9])" + _re.escape(name) + r"(?![a-z0-9])"
        if _re.search(pattern, tl) and sym in fno_universe:
            matched.add(sym)

    return sorted(matched)


def match_sectors_in_headline(text: str) -> list[str]:
    """Returns sector names that appear to be referenced in the headline.

    Bounded on the LEFT so a short keyword cannot fire inside a longer word
    ("ev" in "elevated", "ports" in "reports", "media" in "immediately",
     "oil" in "foiled") — every observed false positive had a preceding
    letter. An optional plural suffix is allowed on the right so legitimate
    inflections still match ("Metals", "Drugs", "Vehicles", "Oils"); anything
    longer than a plural still fails, so "every"/"event" stay excluded.
    """
    import re as _re
    tl = text.lower()
    matched = []
    sector_keywords = {
        "NIFTY IT":           ["it sector", "software", "tech companies", "infotech"],
        "NIFTY PSU BANK":     ["psu bank", "public sector bank", "government bank"],
        "NIFTY PVT BANK":     ["private bank", "pvt bank", "banking sector"],
        "NIFTY PHARMA":       ["pharma", "pharmaceutical", "drug", "medicine", "healthcare"],
        "NIFTY FIN SERVICE":  ["nbfc", "housing finance", "microfinance"],
        "NIFTY AUTO":         ["auto", "automobile", "ev", "electric vehicle", "vehicle"],
        "NIFTY METAL":        ["steel", "metal", "aluminium", "zinc", "iron ore"],
        "NIFTY REALTY":       ["real estate", "housing", "property", "realty"],
        "NIFTY OIL & GAS":    ["crude oil", "oil", "gas", "petroleum", "fuel"],
        "NIFTY FMCG":         ["fmcg", "consumer goods", "staples", "food company"],
        "NIFTY INFRA":        ["infrastructure", "capex", "power", "roads", "ports"],
        "NIFTY MEDIA & COMM": ["telecom", "media", "broadband", "5g"],
    }
    for sector, kws in sector_keywords.items():
        for kw in kws:
            pattern = r"(?<![a-z0-9])" + _re.escape(kw) + r"(?:s|es)?(?![a-z0-9])"
            if _re.search(pattern, tl):
                matched.append(sector)
                break
    return matched
