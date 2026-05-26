"""
Rock On Ruby — Trend Scraper
Data sources:
  - Google Trends via pytrends (free, no API key required)
  - People Also Ask via Serper.dev (uses SERPER_API_KEY — free credits)
  - Knowledge-seeded baseline scores as fallback

Usage:
  python3 scraper.py          → Full run (fetches all live data)
  python3 scraper.py --cached → Rebuild report from last cached run (no API calls)
"""

import json
import os
import sys
import time
import random
from datetime import datetime, timedelta
from pathlib import Path
import requests
from pytrends.request import TrendReq

# ── Config ───────────────────────────────────────────────────────────────────

SERPER_KEY   = os.environ.get("SERPER_API_KEY", "")
OUTPUT_DIR   = Path(__file__).parent
REPORT_FILE  = OUTPUT_DIR / "trend_report.html"
CACHE_FILE   = OUTPUT_DIR / "trend_cache.json"
FOCUS_FILE   = OUTPUT_DIR / "ror_focus.json"
LAYER4_CACHE = OUTPUT_DIR / "layer4_expanded.json"

GEO            = "GB"
TIMEFRAME      = "today 3-m"
CATALOGUE_FILE = OUTPUT_DIR / "shopify_catalogue.json"

_PT        = TrendReq(hl="en-GB", tz=0, retries=3, backoff_factor=0.5)
_CATALOGUE: dict = {}


def load_catalogue() -> dict:
    global _CATALOGUE
    if CATALOGUE_FILE.exists():
        try:
            _CATALOGUE = json.loads(CATALOGUE_FILE.read_text())
        except Exception:
            pass
    return _CATALOGUE


# ── Season config ─────────────────────────────────────────────────────────────

def load_focus_config() -> dict:
    if FOCUS_FILE.exists():
        try:
            return json.loads(FOCUS_FILE.read_text())
        except Exception:
            pass
    return {}


def expand_layer4_with_claude(seeds: list[str]) -> list[str]:
    """
    Ask Claude to suggest 10 additional Layer 4 keywords based on seeds.
    Result is cached in layer4_expanded.json for 7 days.
    """
    # Return cached result if fresh (< 7 days old)
    if LAYER4_CACHE.exists():
        try:
            cached = json.loads(LAYER4_CACHE.read_text())
            age_days = (datetime.now() - datetime.fromisoformat(cached["date"])).days
            if age_days < 7:
                return cached.get("keywords", [])
        except Exception:
            pass

    api_key = os.environ.get("ANTHROPIC_API_KEY", "")
    if not api_key:
        return []

    try:
        import anthropic
        client = anthropic.Anthropic(api_key=api_key)
        prompt = (
            "You are a keyword researcher for Rock On Ruby, a UK personalised clothing brand. "
            "Based on these seed keywords for birthday/milestone gifting searches, suggest 10 additional "
            "high-volume UK search terms that would drive traffic to personalised birthday clothing and gifts. "
            "Return ONLY a JSON array of strings, no explanation:\n"
            f"{json.dumps(seeds[:8])}"
        )
        msg = client.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=256,
            messages=[{"role": "user", "content": prompt}],
        )
        raw = msg.content[0].text.strip()
        # Extract JSON array from response
        start = raw.find("[")
        end   = raw.rfind("]") + 1
        suggestions = json.loads(raw[start:end]) if start >= 0 else []
        suggestions = [s.lower().strip() for s in suggestions if isinstance(s, str)][:10]

        LAYER4_CACHE.write_text(json.dumps({"date": datetime.now().isoformat(), "keywords": suggestions}))
        print(f"  Layer 4 expanded with {len(suggestions)} Claude-suggested keywords")
        return suggestions
    except Exception as e:
        print(f"  Layer 4 expansion skipped: {e}")
        return []


def build_term_groups(config: dict) -> list[dict]:
    """
    Build TERM_GROUPS dynamically from ror_focus.json using the 4-layer system.
    Cap total queries at 50 across all groups.
    """
    if not config:
        return TERM_GROUPS_FALLBACK

    l1     = config.get("layer_1_industry", [])
    l2     = config.get("layer_2_products", [])
    l3     = config.get("layer_3_trends", [])
    l4     = config.get("layer_4_bestsellers", [])
    broad  = config.get("broad_categories", [])

    # Expand Layer 4 with Claude suggestions (cached)
    l4_extra = expand_layer4_with_claude(l4)
    l4_all   = list(dict.fromkeys(l4 + l4_extra))  # deduplicate, preserve order

    # Supplement Layer 4 with live Shopify bestsellers if catalogue is loaded
    if _CATALOGUE and _CATALOGUE.get("bestsellers"):
        _skip = {"personalisation", "option-set", "mystery bag", "back of the neck",
                 "2nd line", "add ", "gift box"}
        existing_lower = {t.lower() for t in l4_all}
        for bs in _CATALOGUE["bestsellers"][:15]:
            bt = bs["title"].lower().strip()
            if any(s in bt for s in _skip):
                continue
            if bt not in existing_lower:
                l4_all.append(bs["title"].lower())
                existing_lower.add(bt)

    groups = []
    used   = 0
    CAP    = 50

    # Layer 4 — best sellers (priority, tracked most heavily, generates 3 content pieces)
    l4_terms = [(t, 35, "rising") for t in l4_all[:20]]
    if l4_terms:
        groups.append({"label": "Best Sellers & Birthday (Layer 4)", "terms": l4_terms, "layer": 4})
        used += len(l4_terms)

    # Broad categories — for rising query discovery, breakout detection
    if used < CAP:
        broad_terms = [(t, 20, "stable") for t in broad[:7]]
        if broad_terms:
            groups.append({"label": "Broad Category Discovery", "terms": broad_terms, "layer": 0})
            used += len(broad_terms)

    # Layer 3 — seasonal trends
    if used < CAP:
        remaining  = min(CAP - used, 15)
        l3_terms   = [(t, 25, "rising") for t in l3[:remaining]]
        if l3_terms:
            groups.append({"label": "Seasonal Trends (Layer 3)", "terms": l3_terms, "layer": 3})
            used += len(l3_terms)

    # Layer 1 × Layer 2 cross combinations (personalised/embroidered/slogan × product)
    if used < CAP:
        l1_priority = [x for x in l1 if x in ("personalised", "embroidered", "custom", "slogan")]
        combos = []
        for mod in l1_priority[:3]:
            for product in l2[:4]:
                combo = f"{mod} {product} uk"
                if combo not in [t[0] for g in groups for t in g["terms"]]:
                    combos.append((combo, 15, "stable"))
                if len(combos) >= min(8, CAP - used):
                    break
            if len(combos) >= min(8, CAP - used):
                break
        if combos:
            groups.append({"label": "Industry × Product (Layers 1+2)", "terms": combos, "layer": 12})
            used += len(combos)

    # Layer 2 standalone — product keyword tracking
    if used < CAP:
        remaining  = min(CAP - used, 6)
        all_used   = {t[0] for g in groups for t in g["terms"]}
        l2_terms   = [(f"{p} uk", 12, "stable") for p in l2 if f"{p} uk" not in all_used][:remaining]
        if l2_terms:
            groups.append({"label": "Product Keywords (Layer 2)", "terms": l2_terms, "layer": 2})

    return groups

# ── ROR static fallback catalogue (used only if shopify_catalogue.json missing) ──

ROR_EXISTING = [
    # Top sellers by revenue — keep in sync with actual Shopify data
    "personalised year sweatshirt", "personalised year t-shirt",
    "happy hour sweatshirt", "happy hour t-shirt",
    "personalised handwriting cuff sweatshirt",
    "embroidered personalised slogan cap",
    "yes i like pina colada cap", "pina colada",
    "custard cream sweatshirt", "custard cream connoisseur",
    "blah blah blah slogan t-shirt",
    "rock on ruby branded tote bag",
    "tea please sweatshirt", "tea please",
    "funky font personalised year sweatshirt",
    # Collections / categories
    "personalised caps", "embroidered caps", "slogan cap",
    "personalised sweatshirts", "slogan sweatshirts",
    "personalised tote bags", "make up bag", "makeup bag",
    "wedding party", "teacher gifts", "twinning",
    "personalised gifts", "funny gifts for women",
    "father's day gifts", "gifts for dad", "gifts for mum",
    "bourbon biscuit", "custard cream", "jammy dodger",
    "only here for the", "tea please", "coffee please",
    "leopard print", "festival clothing", "festival outfit",
    "christmas jumper", "pyjamas",
]

# ── Term groups (built dynamically from ror_focus.json) ───────────────────────

# Fallback used only if ror_focus.json is missing
TERM_GROUPS_FALLBACK = [
    {
        "label": "Seasonal Trends",
        "layer": 3,
        "terms": [
            ("fathers day gifts uk",    45, "rising"),
            ("glastonbury 2026",        52, "rising"),
            ("personalised gifts uk",   58, "stable"),
            ("funny gifts for women uk",42, "stable"),
            ("birthday gift uk",        48, "stable"),
        ],
    },
]

load_catalogue()   # must run before build_term_groups so _CATALOGUE is populated
FOCUS_CONFIG = load_focus_config()
TERM_GROUPS  = build_term_groups(FOCUS_CONFIG)

# ── Product + social suggestions ──────────────────────────────────────────────

SUGGESTIONS = {
    "fathers day": [
        "Cap: 'Only Here for the BBQ' — embroidered slogan, Father's Day gifting angle",
        "Sweatshirt: 'Tea Please Dad' — simple embroidered text, gift-ready",
        "Cap: 'Coffee First, Dad Stuff Second' — funny and fast to execute",
        "Social: 'What Dad Really Wants' reel featuring BBQ-themed personalised cap",
    ],
    "bbq": [
        "Cap: 'Grill Sergeant' — Father's Day BBQ gifting, fast to produce",
        "Cap: 'Ketchup or Brown Sauce' — divisive, funny, conversation-starting",
        "Gap product: Personalised apron — 'Head Chef (Self-Appointed)'",
        "Social: 'Team Ketchup vs Team Brown Sauce' poll — big engagement driver",
    ],
    "biscuit": [
        "Cap: 'Only Here for the Bourbons' — biscuit range hero product",
        "Sweatshirt: Custard Cream slogan print — nostalgic British humour",
        "Tote: 'Only Here for the Jammy Dodgers' — low cost, high shareability",
        "Social: 'Rank our biscuit range' poll — drives engagement and discovery",
    ],
    "personalised": [
        "Gap: Personalised aprons — Father's Day / BBQ crossover, not on ROR yet",
        "Gap: Personalised BBQ accessories — gifting gap for food-loving dads",
        "Social: 'Weird personalisation requests we've actually had' — relatable content",
    ],
    "slogan": [
        "Slogan drop: 'Only Here for the…' extended into summer — beach, Prosecco, festival",
        "Cap: 'Festival Hair, Don't Care' — festival season tie-in",
        "Sweatshirt: 'Only Here for the Headliners' — Glastonbury hype angle",
    ],
    "festival": [
        "Festival cap collection — embroidered, practical, gifting angle pre-June",
        "Social: 'What goes on tour' — personalised cap gifting content for festival groups",
        "Tote: Festival tote with custom name or slogan — low cost, high gift appeal",
    ],
    "summer": [
        "Drop: personalised beach tote + 'Girls Trip 2026' cap",
        "Social: 'Your summer sorted' gift guide email pulling existing products together",
        "Cap: 'Only Here for the Sunshine' — seasonal slogan, fast to execute",
    ],
    "leopard": [
        "Leopard print sweatshirt with embroidered slogan — bold colourway",
        "Social: 'Leopard print is forever' — leans into ROR's anti-boring positioning",
    ],
    "women": [
        "Funny birthday gift sets — cap + tote bundle, gift-wrapped",
        "Social: 'Gifts that aren't a candle' — positions ROR against generic gifting",
        "Sweatshirt: 'Bra Off By 7' — speaks directly to the ROR customer",
    ],
    "novelty": [
        "Novelty slogan caps for gifting — lean into the anti-boring positioning",
        "Social: 'Slogans we've actually embroidered' reel — funny UGC-style content",
    ],
    "tea": [
        "Cap/tote: 'Tea Please' — already in ROR range, push harder pre-Father's Day",
        "Social: 'The great British tea debate — milk first?' poll",
    ],
    "coffee": [
        "Cap: 'Coffee Please' — already in range, bundle with Tea Please for gifting drop",
        "Social: 'Your coffee order = your personality' — high-engagement content",
    ],
}


def get_suggestions(label: str, term: str) -> list[str]:
    combined = (label + " " + term).lower()
    results = []
    for key, items in SUGGESTIONS.items():
        if key in combined:
            results.extend(items)
    if not results:
        results = [
            f"Slogan cap or sweatshirt tied to '{term}' — quick to produce as print-on-demand",
            "Social: behind-the-scenes making content featuring this theme",
        ]
    return results[:4]


def already_sells(term: str) -> str:
    """Return matching product/collection title if ROR sells something related, else ''."""
    term_lower = term.lower()
    words = [w for w in term_lower.split()
             if len(w) > 3 and w not in {"with", "from", "that", "this", "your", "they", "have", "here"}]
    if not words:
        return ""

    _SKIP_COLL = {"gift-vouchers", "all", "frontpage", "homepage-collection",
                  "imported", "best-sellers-vs-hidden-gems", "collections",
                  "sale", "christmas-sale", "year-sale", "sale-tops", "sale-accessories",
                  "winter-sale", "holiday-bundle", "basics", "easter"}

    if _CATALOGUE:
        # Collections first — highest confidence for SEO mapping
        for c in _CATALOGUE.get("collections", []):
            if c.get("handle") in _SKIP_COLL:
                continue
            c_lower = c["title"].lower()
            if any(w in c_lower for w in words):
                return c["title"]
        # Bestsellers — proven sellers, highest relevance for content
        for b in _CATALOGUE.get("bestsellers", []):
            b_lower = b["title"].lower()
            if any(w in b_lower for w in words):
                return b["title"]
        # All products — broad match
        for p in _CATALOGUE.get("products", []):
            p_lower = p["title"].lower()
            p_tags  = " ".join(p.get("tags", [])).lower()
            if any(w in p_lower for w in words) or any(w in p_tags for w in words):
                return p["title"]

    # Static fallback
    for existing in ROR_EXISTING:
        if any(w in existing for w in words):
            return existing
    return ""


def score_term(avg: int, trend: str, term: str) -> int:
    score = 0
    if avg > 50:   score += 4
    elif avg > 35: score += 3
    elif avg > 20: score += 2
    elif avg > 8:  score += 1
    if trend == "rising":  score += 3
    elif trend == "stable": score += 1
    t = term.lower()
    if any(k in t for k in ["gift", "personalised", "custom"]): score += 1
    if any(k in t for k in ["fathers day", "dad", "festival", "summer", "holiday", "bbq"]): score += 1
    if not already_sells(term): score += 1
    return min(score, 10)


# ── Trends + PAA data fetches ─────────────────────────────────────────────────

def _trends_query(q: str) -> dict:
    """Single pytrends interest-over-time call. Returns parsed dict or {}."""
    try:
        _PT.build_payload([q], cat=0, timeframe=TIMEFRAME, geo=GEO)
        df = _PT.interest_over_time()
    except Exception:
        return {}
    if df is None or df.empty or q not in df.columns:
        return {}
    values = [int(v) for v in df[q].tolist() if isinstance(v, (int, float))]
    if not values or max(values) == 0:
        return {}
    avg  = int(sum(values) / len(values))
    peak = max(values)
    half = max(1, len(values) // 2)
    fh   = sum(values[:half]) / half
    sh   = sum(values[half:]) / max(1, len(values) - half)
    trend = "rising" if sh > fh * 1.15 else ("falling" if sh < fh * 0.85 else "stable")
    return {"avg": avg, "peak": peak, "trend": trend}


def pytrends_interest_over_time(term: str) -> dict:
    """
    Fetch interest-over-time for a term (0-100 scale, UK, 90-day window).
    Falls back to stripping trailing ' uk' suffix if first call returns no data.
    Returns {"avg": int, "peak": int, "trend": str} or {}.
    """
    try:
        result = _trends_query(term)
        if result:
            return result
        cleaned = term
        for suffix in (" uk 2026", " uk"):
            if cleaned.lower().endswith(suffix):
                cleaned = cleaned[: -len(suffix)].strip()
                break
        if cleaned != term:
            time.sleep(random.uniform(10.0, 13.0))
            result = _trends_query(cleaned)
            if result:
                return result
        return {}
    except Exception as e:
        print(f"    Trends error for '{term}': {e}")
        return {}


def pytrends_related_queries(term: str) -> dict[str, list[str]]:
    """
    Rising + top + breakout related queries via pytrends.
    Breakout = Google marks the rising value as 'Breakout' (>5000% increase).
    Returns {"rising": [...], "top": [...], "breakout": [...]}.
    """
    out = {"rising": [], "top": [], "breakout": []}
    try:
        _PT.build_payload([term], cat=0, timeframe=TIMEFRAME, geo=GEO)
        related   = _PT.related_queries()
        if not related or term not in related:
            return out
        term_data = related[term]

        rising_df = term_data.get("rising")
        if rising_df is not None and not rising_df.empty and "query" in rising_df.columns:
            for _, row in rising_df.head(6).iterrows():
                q = str(row.get("query", ""))
                v = row.get("value", 0)
                if not q:
                    continue
                if str(v).lower() == "breakout" or (isinstance(v, (int, float)) and v >= 5000):
                    out["breakout"].append(q)
                else:
                    out["rising"].append(q)

        top_df = term_data.get("top")
        if top_df is not None and not top_df.empty and "query" in top_df.columns:
            out["top"] = [str(r["query"]) for _, r in top_df.head(6).iterrows() if r.get("query")]
    except Exception as e:
        print(f"    Related queries error for '{term}': {e}")
    return out


def serper_people_also_ask(term: str) -> list[str]:
    """Fetch People Also Ask questions via Serper.dev (uses SERPER_API_KEY)."""
    if not SERPER_KEY:
        return []
    try:
        resp = requests.post(
            "https://google.serper.dev/search",
            headers={"X-API-KEY": SERPER_KEY, "Content-Type": "application/json"},
            json={"q": term, "gl": "gb", "hl": "en"},
            timeout=10,
        )
        if not resp.ok:
            return []
        return [item["question"] for item in resp.json().get("peopleAlsoAsk", [])[:5]
                if "question" in item]
    except Exception as e:
        print(f"    PAA error for '{term}': {e}")
        return []


def fetch_related_queries_weekly(term: str, gprop: str = "") -> dict[str, list[str]]:
    """Fetch related queries for a term, past 7 days. gprop='' for web, 'youtube' for YouTube.
    Retries up to 3 times with a 30-second wait on 429 rate-limit errors."""
    out: dict[str, list[str]] = {"rising": [], "top": []}
    MAX_RETRIES = 3
    RETRY_WAIT  = 30  # seconds
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            _PT.build_payload([term], cat=0, timeframe="now 7-d", geo=GEO, gprop=gprop)
            related = _PT.related_queries()
            if not related or term not in related:
                return out
            term_data = related[term]
            rising_df = term_data.get("rising")
            if rising_df is not None and not rising_df.empty and "query" in rising_df.columns:
                out["rising"] = [str(r["query"]) for _, r in rising_df.head(10).iterrows() if r.get("query")]
            top_df = term_data.get("top")
            if top_df is not None and not top_df.empty and "query" in top_df.columns:
                out["top"] = [str(r["query"]) for _, r in top_df.head(10).iterrows() if r.get("query")]
            return out
        except Exception as e:
            err_str = str(e)
            if "429" in err_str and attempt < MAX_RETRIES:
                print(f"    429 rate limit — waiting {RETRY_WAIT}s then retrying (attempt {attempt}/{MAX_RETRIES})")
                time.sleep(RETRY_WAIT)
            else:
                print(f"    Weekly trends error '{term}' (gprop={gprop or 'web'}): {e}")
                return out
    return out


def fetch_trending_queries_uk(all_groups: list[dict]) -> dict:
    """
    Fetch UK trending + rising queries, past 7 days, web and YouTube.
    Uses the top 3 scoring terms to pull related query data via pytrends.
    Returns {"web": {"top": [...], "rising": [...]}, "youtube": {"top": [...], "rising": [...]},
             "fallback": bool}.
    If the 7-day endpoint fails for all terms, falls back to trending_searches() for today's top UK
    searches and sets "fallback": True.
    """
    all_results = [r for g in all_groups for r in g["results"]]
    top_terms   = [r["term"] for r in sorted(all_results, key=lambda r: -r["score"])[:3]]
    if not top_terms:
        return {}

    web_top:    list[str] = []
    web_rising: list[str] = []
    yt_top:     list[str] = []
    yt_rising:  list[str] = []
    seen_wt: set[str] = set()
    seen_wr: set[str] = set()
    seen_yt: set[str] = set()
    seen_yr: set[str] = set()

    for term in top_terms:
        print(f"  → Weekly web trends: {term}")
        web = fetch_related_queries_weekly(term, "")
        for q in web["top"]:
            if q not in seen_wt:
                seen_wt.add(q); web_top.append(q)
        for q in web["rising"]:
            if q not in seen_wr:
                seen_wr.add(q); web_rising.append(q)
        time.sleep(random.uniform(10.0, 13.0))

        print(f"  → Weekly YouTube trends: {term}")
        yt = fetch_related_queries_weekly(term, "youtube")
        for q in yt["top"]:
            if q not in seen_yt:
                seen_yt.add(q); yt_top.append(q)
        for q in yt["rising"]:
            if q not in seen_yr:
                seen_yr.add(q); yt_rising.append(q)
        time.sleep(random.uniform(10.0, 13.0))

    # If we got any weekly data, return it normally
    if web_top or web_rising or yt_top or yt_rising:
        return {
            "web":      {"top": web_top[:10],  "rising": web_rising[:10]},
            "youtube":  {"top": yt_top[:10],   "rising": yt_rising[:10]},
            "fallback": False,
        }

    # ── Fallback: weekly 7-day endpoint failed — use trending_searches() instead ──
    print("  Weekly trends unavailable — falling back to today's trending searches (UK)")
    try:
        df = _PT.trending_searches(pn="united_kingdom")
        today_top = df.iloc[:, 0].dropna().tolist()[:10]
        today_top = [str(t) for t in today_top]
    except Exception as e:
        print(f"  Fallback trending_searches() also failed: {e}")
        today_top = []

    return {
        "web":      {"top": today_top, "rising": []},
        "youtube":  {"top": [],        "rising": []},
        "fallback": True,
    }


# ── Fetch all data ────────────────────────────────────────────────────────────

def fetch_all(cached: bool = False) -> tuple[list[dict], dict]:
    """
    Fetch or load all data. Returns (all_groups, trending_data) tuple.
    """
    if cached and CACHE_FILE.exists():
        print("  Loading from cache...")
        raw = json.loads(CACHE_FILE.read_text())
        if isinstance(raw, list):
            return raw, {}
        return raw.get("groups", []), raw.get("trending", {})

    all_groups = []
    total_groups = len(TERM_GROUPS)

    for g_idx, group in enumerate(TERM_GROUPS):
        label     = group["label"]
        term_list = [(t[0], t[1], t[2]) for t in group["terms"]]
        terms     = [t[0] for t in term_list]

        print(f"\n[{g_idx+1}/{total_groups}] {label}")

        # ── 1. Trends timeseries (pytrends, 1 call per term) ──
        ts_data = {}
        for term in terms:
            print(f"  → Trends: {term}")
            ts_data[term] = pytrends_interest_over_time(term)
            time.sleep(random.uniform(10.0, 13.0))

        # ── 2. Related queries (pytrends, includes breakout detection) ──
        related_data = {}
        for term in terms:
            print(f"  → Related queries: {term}")
            related_data[term] = pytrends_related_queries(term)
            if related_data[term].get("breakout"):
                print(f"    🚨 BREAKOUT detected in related: {related_data[term]['breakout']}")
            time.sleep(random.uniform(10.0, 13.0))

        # ── 3. PAA via Serper.dev — only for terms scoring 6+ ──
        paa_data = {}
        for term, seed_avg, seed_trend in term_list:
            live        = ts_data.get(term, {})
            avg         = live.get("avg", seed_avg)
            trend       = live.get("trend", seed_trend)
            rough_score = score_term(avg, trend, term)
            if rough_score >= 6:
                print(f"  → People Also Ask: {term}")
                paa_data[term] = serper_people_also_ask(term)
                time.sleep(random.uniform(0.8, 1.2))

        # ── Build result dicts ──
        results = []
        for term, seed_avg, seed_trend in term_list:
            live   = ts_data.get(term, {})
            avg    = live.get("avg", seed_avg)
            peak   = live.get("peak", 0)
            trend  = live.get("trend", seed_trend)
            is_live = bool(live)

            rising_q   = related_data.get(term, {}).get("rising", [])
            top_q      = related_data.get(term, {}).get("top", [])
            breakout_q = related_data.get(term, {}).get("breakout", [])
            paa        = paa_data.get(term, [])

            existing    = already_sells(term)
            suggestions = get_suggestions(label, term)
            score       = score_term(avg, trend, term)

            results.append({
                "term":             term,
                "avg_interest":     avg,
                "peak_interest":    peak,
                "trend":            trend,
                "rising_queries":   rising_q,
                "top_queries":      top_q,
                "breakout_queries": breakout_q,
                "paa":              paa,
                "ror_existing":     existing,
                "suggestions":      suggestions,
                "score":            score,
                "seo_action":       seo_action(score, trend, existing),
                "layer":            group.get("layer", 3),
                "data_source":      "live" if is_live else "estimated",
            })

        all_groups.append({"label": label, "results": results})
        if g_idx < total_groups - 1:
            pause = random.uniform(10.0, 15.0)
            print(f"  Pausing {pause:.1f}s...")
            time.sleep(pause)

    print("\n── Trending Queries UK (past week) ──")
    trending_data = fetch_trending_queries_uk(all_groups)

    # Cache results
    CACHE_FILE.write_text(json.dumps({"groups": all_groups, "trending": trending_data}, indent=2))
    print(f"\nCached to: {CACHE_FILE}")
    return all_groups, trending_data


# ── SEO Keyword Export ────────────────────────────────────────────────────────

# Maps score + gap status to a recommended SEO action
def seo_action(score: int, trend: str, existing: str) -> str:
    if trend == "falling":
        return "Monitor only — search demand declining"
    if score >= 8 and not existing:
        return "Create new product page targeting this keyword"
    if score >= 8 and existing:
        return "Update product title & meta description with this keyword"
    if score >= 6 and trend == "rising" and not existing:
        return "Write blog post — no ROR page to land on yet"
    if score >= 6 and trend == "rising" and existing:
        return "Update collection page copy + add to FAQs"
    if score >= 4 and existing:
        return "Refresh product description — keyword is stable"
    if not existing:
        return "Potential new product — monitor volume before committing"
    return "Low priority — review next quarter"

def seo_page_map(term: str, existing: str) -> str:
    """Return the best matching ROR page URL for a trend term."""
    t     = term.lower()
    words = [w for w in t.split() if len(w) > 3]

    # Collections to skip for SEO mapping — internal/utility, not SEO landing pages
    _SKIP_COLL = {"gift-vouchers", "all", "frontpage", "homepage-collection",
                  "imported", "best-sellers-vs-hidden-gems", "collections",
                  "sale", "christmas-sale", "year-sale", "sale-tops", "sale-accessories",
                  "winter-sale", "holiday-bundle", "basics", "easter"}

    # Live catalogue — match collections first (SEO gold: collection URLs rank best)
    if _CATALOGUE:
        for c in _CATALOGUE.get("collections", []):
            if c.get("handle") in _SKIP_COLL:
                continue
            c_lower = c["title"].lower()
            if any(w in c_lower for w in words):
                return c["url"]
        for b in _CATALOGUE.get("bestsellers", []):
            b_lower = b["title"].lower()
            if any(w in b_lower for w in words):
                return b.get("url", f"rockonruby.co.uk/products/search?q={term}")
        for p in _CATALOGUE.get("products", []):
            p_lower = p["title"].lower()
            if any(w in p_lower for w in words):
                return p["url"]

    # Static fallback mapping
    fallback = {
        "fathers day":     "rockonruby.co.uk/collections/gifts-for-dad",
        "father's day":    "rockonruby.co.uk/collections/gifts-for-dad",
        "festival":        "rockonruby.co.uk/collections/clothing",
        "glastonbury":     "rockonruby.co.uk/collections/clothing",
        "biscuit":         "rockonruby.co.uk/collections/clothing",
        "bourbon":         "rockonruby.co.uk/collections/clothing",
        "custard cream":   "rockonruby.co.uk/collections/clothing",
        "sweatshirt":      "rockonruby.co.uk/collections/sweatshirts",
        "hoodie":          "rockonruby.co.uk/collections/sweatshirts",
        "cap":             "rockonruby.co.uk/collections/hats",
        "tote":            "rockonruby.co.uk/collections/tote-bags",
        "make up bag":     "rockonruby.co.uk/collections/make-up-bags",
        "wedding":         "rockonruby.co.uk/collections/wedding-party",
        "teacher":         "rockonruby.co.uk/collections/teacher-gifts",
        "birthday":        "rockonruby.co.uk/collections/personalised-year",
        "personalised":    "rockonruby.co.uk/collections/personalised-accessories",
        "leopard":         "rockonruby.co.uk/collections/sweatshirts",
        "funny gifts":     "rockonruby.co.uk/collections/gifting",
        "gifts for her":   "rockonruby.co.uk/collections/gifts-for-her",
        "gifts for him":   "rockonruby.co.uk/collections/gifts-for-him",
    }
    for key, url in fallback.items():
        if key in t:
            return url
    if existing:
        return f"rockonruby.co.uk — {existing}"
    return "New page needed"


def build_seo_section(all_groups: list[dict]) -> str:
    """Return an HTML string for the SEO Keyword Export section."""
    all_results = [r for g in all_groups for r in g["results"]]
    # Sort: rising first, then by score desc
    sorted_results = sorted(
        all_results,
        key=lambda r: (-(1 if r["trend"] == "rising" else 0), -r["score"], -r["avg_interest"])
    )

    rows = ""
    for r in sorted_results:
        trend_icon = {"rising": "↑", "falling": "↓", "stable": "→"}.get(r["trend"], "→")
        trend_col  = {"rising": "#00b894", "falling": "#d63031", "stable": "#aaa"}.get(r["trend"], "#aaa")
        action     = seo_action(r["score"], r["trend"], r["ror_existing"])
        page       = seo_page_map(r["term"], r["ror_existing"])
        src        = "●" if r["data_source"] == "live" else "○"
        score_col  = "#e91e8c" if r["score"] >= 8 else ("#fdcb6e" if r["score"] >= 5 else "#636e72")

        # Action colour coding
        if "Create new product" in action or "Write blog" in action:
            action_cls = "act-create"
        elif "Update" in action:
            action_cls = "act-update"
        elif "Monitor only" in action or "Low priority" in action:
            action_cls = "act-low"
        else:
            action_cls = "act-watch"

        page_html = _as_link(page) if page.startswith("rockonruby.co.uk/") else f'<span style="color:var(--yellow);font-size:.75rem">{page}</span>'
        rows += f"""
<tr>
  <td class="kw-cell">{r['term']} <span class="src-dot">{src}</span></td>
  <td style="color:{trend_col};font-weight:600">{trend_icon} {r['trend'].capitalize()}</td>
  <td style="color:{score_col};font-weight:700;text-align:center">{r['score']}/10</td>
  <td class="page-cell">{page_html}</td>
  <td><span class="act {action_cls}">{action}</span></td>
</tr>"""

    return f"""
<section class="seo-section">
  <h2 class="seo-title">SEO Keyword Action List</h2>
  <p class="seo-sub">For every trending term — which ROR page it maps to and what to do next.
     ● = live Trends data &nbsp; ○ = estimated</p>
  <div class="table-wrap">
  <table class="seo-table">
    <thead>
      <tr>
        <th>Keyword</th>
        <th>Trend</th>
        <th style="text-align:center">Score</th>
        <th>ROR Page / Product</th>
        <th>Recommended Action</th>
      </tr>
    </thead>
    <tbody>
      {rows}
    </tbody>
  </table>
  </div>
</section>"""


def build_breakout_section(all_groups: list[dict]) -> str:
    """Return an HTML alert block for any breakout keywords found this run."""
    breakouts = []
    for g in all_groups:
        for r in g["results"]:
            for bq in r.get("breakout_queries", []):
                breakouts.append({"query": bq, "parent": r["term"], "score": r["score"]})
    if not breakouts:
        return ""
    items_html = "".join(
        f'<div class="bo-item"><span class="bo-kw">{b["query"]}</span>'
        f'<span class="bo-via">via "{b["parent"]}"</span></div>'
        for b in breakouts
    )
    return f"""
<section class="breakout-section">
  <div class="breakout-header">🚨 BREAKOUT KEYWORDS — Urgent Opportunities This Week</div>
  <p class="breakout-sub">These keywords are showing a sudden spike in search interest. Act fast — early content wins rankings.</p>
  <div class="breakout-grid">{items_html}</div>
</section>"""


def _as_link(url_or_text: str, label: str = None) -> str:
    """Return an HTML anchor if the string looks like a real ROR URL, else plain text."""
    display = label or url_or_text
    if url_or_text.startswith("rockonruby.co.uk/"):
        return f'<a href="https://{url_or_text}" target="_blank" rel="noopener">{display}</a>'
    return display


def build_gaps_section(all_groups: list[dict]) -> str:
    """Trending keywords where ROR has no matching product page — top SEO opportunities."""
    all_results = [r for g in all_groups for r in g["results"]]
    gaps = [r for r in all_results if not r["ror_existing"] and r["score"] >= 5]
    gaps.sort(key=lambda r: (-r["score"], -r["avg_interest"]))
    if not gaps:
        return ""

    items_html = ""
    for r in gaps[:12]:
        action     = seo_action(r["score"], r["trend"], r["ror_existing"])
        trend_icon = {"rising": "↑", "falling": "↓", "stable": "→"}.get(r["trend"], "→")
        t_col      = {"rising": "var(--green)", "falling": "var(--red)", "stable": "var(--muted)"}.get(r["trend"], "var(--muted)")
        s_col      = score_color(r["score"])
        items_html += f"""
<div class="gap-item">
  <div class="gap-kw">{r['term']}</div>
  <div class="gap-meta">
    <span style="color:{s_col};font-weight:700">{r['score']}/10</span>
    <span style="color:{t_col}">{trend_icon} {r['trend'].capitalize()}</span>
    <span style="color:var(--muted);font-size:.72rem">~{r['avg_interest']}/100 interest</span>
  </div>
  <div class="gap-action">{action}</div>
</div>"""

    count = len(gaps)
    return f"""
<section class="gap-section">
  <div class="gap-header">⚡ {count} Search Gap{"s" if count != 1 else ""} — Trending but No Matching ROR Page</div>
  <p class="gap-sub">These keywords have real search demand but no product or collection page on rockonruby.co.uk targeting them. Each is a direct SEO opportunity to create or improve a page.</p>
  <div class="gap-grid">{items_html}</div>
</section>"""


def build_bestseller_demand_section(all_groups: list[dict]) -> str:
    """Cross-reference live Shopify bestsellers against trend data from this run."""
    if not _CATALOGUE or not _CATALOGUE.get("bestsellers"):
        return ""

    all_results  = [r for g in all_groups for r in g["results"]]
    bestsellers  = [b for b in _CATALOGUE["bestsellers"]
                    if b["title"] and "personalisation" not in b["title"].lower()
                    and "back of the neck" not in b["title"].lower()][:20]

    rows = ""
    for bs in bestsellers:
        title   = bs["title"]
        revenue = f"£{bs['revenue']:,.0f}" if bs.get("revenue") else "—"
        orders  = str(bs.get("orders", "—"))
        handle  = bs.get("handle", "")

        # Link the product title if we have a handle
        if handle:
            title_cell = f'<a href="https://rockonruby.co.uk/products/{handle}" target="_blank" rel="noopener">{title}</a>'
        else:
            title_cell = title

        # Fuzzy-match against this run's trend results (≥2 significant words in common)
        bs_words = {w for w in title.lower().split() if len(w) > 3}
        matched  = None
        for r in all_results:
            term_words = {w for w in r["term"].lower().split() if len(w) > 3}
            if len(bs_words & term_words) >= 2:
                matched = r
                break

        if matched:
            s_col  = score_color(matched["score"])
            t_icon = {"rising": "↑", "falling": "↓", "stable": "→"}.get(matched["trend"], "→")
            t_col  = {"rising": "var(--green)", "falling": "var(--red)", "stable": "var(--muted)"}.get(matched["trend"], "var(--muted)")
            score_cell    = f'<span style="color:{s_col};font-weight:700">{matched["score"]}/10</span>'
            trend_cell    = f'<span style="color:{t_col}">{t_icon} {matched["trend"].capitalize()}</span>'
            interest_cell = f'~{matched["avg_interest"]}/100'
        else:
            score_cell    = '<span style="color:var(--muted);font-size:.75rem">Not tracked</span>'
            trend_cell    = "—"
            interest_cell = '<span style="color:var(--yellow);font-size:.72rem">Add to ror_focus.json →</span>'

        rows += f"""
<tr>
  <td class="bs-prod">{title_cell}</td>
  <td class="bs-rev">{revenue}</td>
  <td style="text-align:center;color:var(--muted)">{orders}</td>
  <td style="text-align:center">{score_cell}</td>
  <td style="text-align:center">{trend_cell}</td>
  <td style="text-align:center;color:var(--muted);font-size:.78rem">{interest_cell}</td>
</tr>"""

    return f"""
<section class="bs-section">
  <h2 class="bs-header">Your Bestsellers vs Search Demand</h2>
  <p class="bs-sub">Top-selling products from Shopify (last 90 days) matched against what people are actually searching. "Not tracked" = add to <code>ror_focus.json</code> to monitor.</p>
  <div class="table-wrap">
  <table class="bs-table">
    <thead>
      <tr>
        <th>Product</th>
        <th>Revenue (90d)</th>
        <th style="text-align:center">Orders</th>
        <th style="text-align:center">Trend Score</th>
        <th style="text-align:center">Direction</th>
        <th style="text-align:center">Search Interest</th>
      </tr>
    </thead>
    <tbody>{rows}</tbody>
  </table>
  </div>
</section>"""


SEO_CSS = """
  .breakout-section {{ padding: 1rem 2rem; max-width: 1440px; margin: 0 auto 1rem; }}
  .breakout-header {{ font-size: 1rem; font-weight: 700; color: #fff;
                      background: linear-gradient(90deg,#d63031,#e91e8c);
                      padding: .6rem 1.2rem; border-radius: 8px 8px 0 0; }}
  .breakout-sub {{ font-size: .8rem; color: var(--muted); padding: .5rem 1.2rem;
                   background: rgba(214,48,49,.08); border: 1px solid rgba(214,48,49,.25);
                   border-top: none; border-radius: 0; margin-bottom: .6rem; }}
  .breakout-grid {{ display: flex; flex-wrap: wrap; gap: .5rem; padding: .2rem 0; }}
  .bo-item {{ background: rgba(214,48,49,.12); border: 1px solid rgba(214,48,49,.35);
              border-radius: 6px; padding: .3rem .7rem; display: flex; gap: .5rem; align-items: center; }}
  .bo-kw {{ font-weight: 700; color: #ff7675; font-size: .85rem; }}
  .bo-via {{ font-size: .72rem; color: var(--muted); }}
  .seo-section {{ padding: 0 2rem 3rem; max-width: 1440px; margin: 0 auto; }}
  .seo-title { font-size: 1.2rem; color: var(--pink); padding-bottom: .7rem;
               border-bottom: 2px solid rgba(233,30,140,.25); margin-bottom: .5rem; }
  .seo-sub { font-size: .8rem; color: var(--muted); margin-bottom: 1.2rem; }
  .table-wrap { overflow-x: auto; }
  .seo-table { width: 100%; border-collapse: collapse; font-size: .82rem; }
  .seo-table thead tr { background: rgba(255,255,255,.05); }
  .seo-table th { padding: .6rem .8rem; text-align: left; color: var(--muted);
                  font-size: .72rem; text-transform: uppercase; letter-spacing: .05em;
                  border-bottom: 1px solid rgba(255,255,255,.1); white-space: nowrap; }
  .seo-table td { padding: .55rem .8rem; border-bottom: 1px solid rgba(255,255,255,.04);
                  vertical-align: middle; }
  .seo-table tr:hover td { background: rgba(255,255,255,.03); }
  .kw-cell { font-weight: 600; color: #fff; }
  .src-dot { font-size: .7rem; color: var(--muted); margin-left: .3rem; }
  .page-cell { color: var(--muted); font-size: .78rem; }
  .act { display: inline-block; padding: .18rem .55rem; border-radius: 20px;
         font-size: .75rem; font-weight: 600; white-space: nowrap; }
  .act-create { background: rgba(233,30,140,.18); color: var(--pink);
                border: 1px solid rgba(233,30,140,.35); }
  .act-update { background: rgba(0,184,148,.12); color: var(--green);
                border: 1px solid rgba(0,184,148,.3); }
  .act-watch  { background: rgba(253,203,110,.1); color: var(--yellow);
                border: 1px solid rgba(253,203,110,.3); }
  .act-low    {{ background: rgba(255,255,255,.05); color: var(--muted);
                border: 1px solid rgba(255,255,255,.1); }}
  .page-cell a {{ color: var(--blue); text-decoration: none; }}
  .page-cell a:hover {{ text-decoration: underline; }}

  .gap-section {{ padding: 1rem 2rem; max-width: 1440px; margin: 0 auto 1.5rem; }}
  .gap-header {{ font-size: 1rem; font-weight: 700; color: #fff;
                background: linear-gradient(90deg,#fdcb6e,#e17055);
                padding: .6rem 1.2rem; border-radius: 8px 8px 0 0; }}
  .gap-sub {{ font-size: .8rem; color: var(--muted); padding: .6rem 1.2rem .8rem;
              background: rgba(253,203,110,.05); border: 1px solid rgba(253,203,110,.2);
              border-top: none; }}
  .gap-grid {{ display: grid; grid-template-columns: repeat(auto-fill, minmax(280px,1fr));
               gap: .6rem; padding: .8rem 0 .2rem; }}
  .gap-item {{ background: rgba(253,203,110,.06); border: 1px solid rgba(253,203,110,.2);
               border-radius: 8px; padding: .8rem 1rem; }}
  .gap-kw {{ font-weight: 700; color: #fff; font-size: .9rem; margin-bottom: .35rem; }}
  .gap-meta {{ display: flex; gap: .8rem; align-items: center; font-size: .78rem; margin-bottom: .3rem; }}
  .gap-action {{ font-size: .72rem; color: var(--yellow); }}

  .bs-section {{ padding: 0 2rem 2.5rem; max-width: 1440px; margin: 0 auto; }}
  .bs-header {{ font-size: 1.2rem; color: var(--pink); padding-bottom: .7rem;
                border-bottom: 2px solid rgba(233,30,140,.25); margin-bottom: .5rem; }}
  .bs-sub {{ font-size: .8rem; color: var(--muted); margin-bottom: 1.2rem; }}
  .bs-table {{ width: 100%; border-collapse: collapse; font-size: .82rem; }}
  .bs-table thead tr {{ background: rgba(255,255,255,.05); }}
  .bs-table th {{ padding: .6rem .8rem; text-align: left; color: var(--muted);
                  font-size: .72rem; text-transform: uppercase; letter-spacing: .05em;
                  border-bottom: 1px solid rgba(255,255,255,.1); white-space: nowrap; }}
  .bs-table td {{ padding: .55rem .8rem; border-bottom: 1px solid rgba(255,255,255,.04); vertical-align: middle; }}
  .bs-table tr:hover td {{ background: rgba(255,255,255,.03); }}
  .bs-prod {{ font-weight: 600; }}
  .bs-prod a {{ color: var(--pink); text-decoration: none; }}
  .bs-prod a:hover {{ text-decoration: underline; }}
  .bs-rev {{ color: var(--green); font-weight: 600; }}
"""


TRENDING_CSS = """
  .trending-section { padding: 0 2rem 2.5rem; max-width: 1440px; margin: 0 auto; }
  .trending-title { font-size: 1.2rem; color: var(--pink); padding-bottom: .7rem;
                    border-bottom: 2px solid rgba(233,30,140,.25); margin-bottom: .5rem; }
  .trending-sub { font-size: .8rem; color: var(--muted); margin-bottom: 1.4rem; }
  .trending-tables { display: grid; grid-template-columns: 1fr 1fr; gap: 2.5rem; }
  .trending-table-wrap h3 { font-size: .9rem; color: var(--text); margin-bottom: .8rem; font-weight: 600; }
  .tq-table { width: 100%; border-collapse: collapse; font-size: .82rem; }
  .tq-table th { padding: .5rem .7rem; text-align: left; color: var(--muted);
                 font-size: .72rem; text-transform: uppercase; letter-spacing: .05em;
                 border-bottom: 1px solid rgba(255,255,255,.1); }
  .tq-table td { padding: .45rem .7rem; border-bottom: 1px solid rgba(255,255,255,.04); vertical-align: middle; }
  .tq-table tr:hover td { background: rgba(255,255,255,.03); }
  .tq-num { color: var(--muted); font-size: .75rem; width: 28px; }
  .tq-query { color: #fff; font-weight: 500; }
  .tq-src { display: inline-block; font-size: .72rem; padding: .1rem .4rem;
            border-radius: 10px; white-space: nowrap; }
  .tq-web { background: rgba(116,185,255,.12); color: var(--blue); }
  .tq-yt  { background: rgba(233,30,140,.12); color: var(--pink); }
  @media (max-width: 640px) {
    .trending-tables { grid-template-columns: 1fr; }
    .trending-section { padding-left: 1rem; padding-right: 1rem; }
  }
"""


def build_trending_section(trending_data: dict) -> str:
    """Return an HTML string for the UK Trending Queries section."""
    if not trending_data:
        return ""

    is_fallback = trending_data.get("fallback", False)
    web = trending_data.get("web", {})
    yt  = trending_data.get("youtube", {})

    def merge_rows(web_list: list[str], yt_list: list[str]) -> list[tuple[str, str]]:
        rows: list[tuple[str, str]] = []
        seen: set[str] = set()
        for q in web_list:
            if q not in seen:
                seen.add(q); rows.append((q, "Web"))
        for q in yt_list:
            if q not in seen:
                seen.add(q); rows.append((q, "YouTube"))
        return rows[:10]

    top_rows    = merge_rows(web.get("top", []),    yt.get("top", []))
    rising_rows = merge_rows(web.get("rising", []), yt.get("rising", []))
    if not top_rows and not rising_rows:
        return ""

    def render_table(rows: list[tuple[str, str]]) -> str:
        if not rows:
            return "<p style='color:var(--muted);font-size:.8rem'>No data captured this run.</p>"
        trs = ""
        for i, (query, src) in enumerate(rows, 1):
            src_cls = "tq-web" if src == "Web" else "tq-yt"
            trs += f"""
<tr>
  <td class="tq-num">{i}</td>
  <td class="tq-query">{query}</td>
  <td><span class="tq-src {src_cls}">{src}</span></td>
</tr>"""
        return f"""<table class="tq-table">
  <thead><tr><th>#</th><th>Query</th><th>Source</th></tr></thead>
  <tbody>{trs}
  </tbody>
</table>"""

    if is_fallback:
        title    = "UK Trending Searches — Today"
        sub      = "Showing today&#39;s trending searches — weekly data temporarily unavailable"
        sub_note = f' &nbsp;<span style="color:var(--yellow);font-size:.75rem">({sub})</span>'
        top_heading    = "Top Searches UK — Today"
        rising_heading = "Rising Searches UK — Today"
    else:
        sub_note       = ""
        title          = "UK Trending Searches — Past Week"
        top_heading    = "Top Searches UK — Past Week"
        rising_heading = "Rising Searches UK — Past Week"

    return f"""
<section class="trending-section">
  <h2 class="trending-title">{title}</h2>
  <p class="trending-sub">Raw data from Google Trends via pytrends &nbsp;·&nbsp; Web &amp; YouTube &nbsp;·&nbsp; UK &nbsp;·&nbsp; Past 7 days{sub_note}</p>
  <div class="trending-tables">
    <div class="trending-table-wrap">
      <h3>{top_heading}</h3>
      {render_table(top_rows)}
    </div>
    <div class="trending-table-wrap">
      <h3>{rising_heading}</h3>
      {render_table(rising_rows)}
    </div>
  </div>
</section>"""


# ── HTML Report ───────────────────────────────────────────────────────────────

HTML_TEMPLATE = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Rock On Ruby — Trend Report {date}</title>
<style>
  :root {{
    --pink: #e91e8c; --dark: #1a1a2e; --mid: #16213e; --card: #0f3460;
    --green: #00b894; --yellow: #fdcb6e; --red: #d63031; --blue: #74b9ff;
    --text: #eee; --muted: #aaa;
  }}
  * {{ box-sizing: border-box; margin: 0; padding: 0; }}
  body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
          background: var(--dark); color: var(--text); line-height: 1.6; }}

  header {{ background: linear-gradient(135deg, var(--mid), var(--dark));
            padding: 2.5rem 2rem; border-bottom: 3px solid var(--pink); }}
  header h1 {{ font-size: 2rem; color: var(--pink); margin-bottom: .3rem; }}
  header p  {{ color: var(--muted); font-size: .9rem; }}

  .notice {{ background: rgba(116,185,255,.08); border-left: 4px solid var(--blue);
             padding: .9rem 1.5rem; margin: 1rem 2rem; border-radius: 0 6px 6px 0;
             font-size: .85rem; color: var(--blue); }}

  .summary {{ display: flex; gap: 1.5rem; padding: 1.4rem 2rem;
              background: var(--mid); flex-wrap: wrap;
              border-bottom: 1px solid rgba(255,255,255,.08); }}
  .stat .num {{ font-size: 1.9rem; font-weight: 700; color: var(--pink); }}
  .stat .lbl {{ font-size: .75rem; color: var(--muted); text-transform: uppercase;
                letter-spacing: .05em; }}

  .legend {{ display: flex; gap: 1.2rem; flex-wrap: wrap; padding: .8rem 2rem;
             font-size: .78rem; color: var(--muted);
             background: rgba(255,255,255,.02);
             border-bottom: 1px solid rgba(255,255,255,.05); }}

  main {{ padding: 2rem; max-width: 1440px; margin: 0 auto; }}

  .group {{ margin-bottom: 3rem; }}
  .group h2 {{ font-size: 1.2rem; color: var(--pink); padding-bottom: .7rem;
               border-bottom: 2px solid rgba(233,30,140,.25); margin-bottom: 1.1rem; }}

  .cards {{ display: grid; grid-template-columns: repeat(auto-fill, minmax(360px,1fr));
            gap: 1.1rem; }}

  .card {{ background: var(--card); border-radius: 12px; padding: 1.3rem;
           border: 1px solid rgba(255,255,255,.07); position: relative;
           overflow: hidden; transition: transform .15s; }}
  .card:hover {{ transform: translateY(-2px); }}

  .card.hot    {{ border-color: var(--pink); box-shadow: 0 0 22px rgba(233,30,140,.18); }}
  .card.rising {{ border-color: var(--green); }}

  .card.hot::before    {{ content: '🔥 HOT'; }}
  .card.rising::before {{ content: '↑ RISING'; background: var(--green) !important; }}
  .card.hot::before, .card.rising::before {{
    position: absolute; top: 0; right: 0; background: var(--pink);
    color: #fff; font-size: .68rem; font-weight: 700;
    padding: .22rem .55rem; border-radius: 0 12px 0 8px;
  }}

  .card-term {{ font-size: 1rem; font-weight: 600; color: #fff;
                margin-bottom: .7rem; padding-right: 5rem; }}

  .badges {{ display: flex; gap: .4rem; flex-wrap: wrap; margin-bottom: .9rem; }}
  .badge {{ padding: .18rem .55rem; border-radius: 20px; font-size: .74rem;
            font-weight: 600; display: inline-flex; align-items: center; }}
  .b-avg   {{ background: rgba(255,255,255,.1); color: var(--text); }}
  .b-peak  {{ background: rgba(253,203,110,.12); color: var(--yellow); }}
  .b-rise  {{ background: rgba(0,184,148,.14); color: var(--green); }}
  .b-fall  {{ background: rgba(214,48,49,.14); color: var(--red); }}
  .b-stbl  {{ background: rgba(255,255,255,.07); color: var(--muted); }}
  .b-live  {{ background: rgba(0,184,148,.15); color: var(--green); font-size: .68rem; }}
  .b-est   {{ background: rgba(255,255,255,.05); color: var(--muted); font-size: .68rem; }}

  .score-row {{ display: flex; align-items: center; gap: .7rem; margin-bottom: .9rem; }}
  .score-lbl {{ font-size: .72rem; color: var(--muted); width: 78px; flex-shrink: 0; }}
  .bar-track {{ flex: 1; height: 5px; background: rgba(255,255,255,.09);
                border-radius: 3px; overflow: hidden; }}
  .bar-fill  {{ height: 100%; border-radius: 3px; }}
  .score-val {{ font-size: .78rem; font-weight: 700; width: 22px; text-align: right; }}

  .ror-tag {{ display: inline-block; border-radius: 6px; padding: .13rem .45rem;
              font-size: .73rem; margin-bottom: .6rem; }}
  .ror-gap {{ background: rgba(253,203,110,.18); color: var(--yellow);
              border: 1px solid rgba(253,203,110,.35); }}
  .ror-has {{ background: rgba(0,184,148,.1); color: var(--green);
              border: 1px solid rgba(0,184,148,.3); }}

  .section-label {{ font-size: .68rem; text-transform: uppercase;
                    letter-spacing: .07em; color: var(--muted);
                    margin: .85rem 0 .3rem; }}

  ul.items {{ list-style: none; }}
  ul.items li {{ font-size: .8rem; color: var(--text); padding: .32rem 0 .32rem .95rem;
                 border-bottom: 1px solid rgba(255,255,255,.04); position: relative; }}
  ul.items li::before {{ content: '→'; position: absolute; left: 0; color: var(--pink); }}
  ul.items li:last-child {{ border: none; }}

  ul.queries li::before {{ content: '🔍'; font-size: .7rem; }}
  ul.paa li::before     {{ content: '❓'; font-size: .7rem; }}

  .two-col {{ display: grid; grid-template-columns: 1fr 1fr; gap: .5rem; }}

  footer {{ text-align: center; padding: 1.8rem; color: var(--muted);
            font-size: .78rem; border-top: 1px solid rgba(255,255,255,.05);
            margin-top: 2rem; }}
  code {{ background: rgba(255,255,255,.08); padding: .1rem .35rem;
          border-radius: 4px; font-family: monospace; font-size: .85em; }}

  {seo_css}
  {trending_css}
  @media (max-width: 640px) {{
    header h1 {{ font-size: 1.4rem; }}
    .cards {{ grid-template-columns: 1fr; }}
    main, .summary, .notice, .legend {{ padding-left: 1rem; padding-right: 1rem; }}
    .two-col {{ grid-template-columns: 1fr; }}
    .seo-section {{ padding-left: 1rem; padding-right: 1rem; }}
  }}
</style>
</head>
<body>

<header>
  <h1>Rock On Ruby — Trend Intelligence Report</h1>
  <p>Generated {date} · Google Trends (pytrends) · PAA via Serper.dev · UK · 90-day window</p>
</header>

{breakout_section}

{notice}

<div class="summary">
  <div class="stat"><div class="num">{total}</div><div class="lbl">Terms tracked</div></div>
  <div class="stat"><div class="num">{hot}</div><div class="lbl">Hot (8–10)</div></div>
  <div class="stat"><div class="num">{rising}</div><div class="lbl">Rising</div></div>
  <div class="stat"><div class="num">{gaps}</div><div class="lbl">Product gaps</div></div>
  <div class="stat"><div class="num">{live}</div><div class="lbl">Live data</div></div>
  <div class="stat"><div class="num">{paa_count}</div><div class="lbl">PAA questions</div></div>
</div>

<div class="legend">
  <span>🔥 HOT = Score 8–10 &nbsp;</span>
  <span>↑ RISING = Growing vs 45 days ago &nbsp;</span>
  <span>⚡ Gap = Not on rockonruby.co.uk &nbsp;</span>
  <span>● Live = Google Trends confirmed &nbsp;</span>
  <span>○ Est = Knowledge-seeded estimate</span>
</div>

{gaps_section}

{bestseller_section}

<main>
{trending_section}
{groups_html}
</main>

{seo_section}

<footer>
  Rock On Ruby Trend Scraper · rockonruby.co.uk · Re-run: <code>python3 scraper.py</code>
  &nbsp;·&nbsp; Use cached data: <code>python3 scraper.py --cached</code>
</footer>
</body>
</html>"""


def score_color(s: int) -> str:
    if s >= 8: return "#e91e8c"
    if s >= 5: return "#fdcb6e"
    return "#636e72"


def trend_badge(trend: str) -> str:
    cls  = {"rising": "b-rise", "falling": "b-fall", "stable": "b-stbl"}.get(trend, "b-stbl")
    lbl  = {"rising": "↑ Rising", "falling": "↓ Falling", "stable": "→ Stable"}.get(trend, trend)
    return f'<span class="badge {cls}">{lbl}</span>'


def render_card(r: dict) -> str:
    is_hot    = r["score"] >= 8
    is_rising = r["trend"] == "rising" and not is_hot
    cls       = "card hot" if is_hot else ("card rising" if is_rising else "card")

    src_badge = '<span class="badge b-live">● Live</span>' if r["data_source"] == "live" \
                else '<span class="badge b-est">○ Est</span>'

    if r["ror_existing"]:
        ror_url  = seo_page_map(r["term"], r["ror_existing"])
        ror_link = _as_link(ror_url, r["ror_existing"])
        ror_html = f'<span class="ror-tag ror-has">✓ ROR sells: {ror_link}</span>'
    else:
        ror_html = '<span class="ror-tag ror-gap">⚡ Product gap — not on rockonruby.co.uk yet</span>'

    color   = score_color(r["score"])
    bar_pct = r["score"] * 10

    avg_badge  = f'<span class="badge b-avg">~{r["avg_interest"]}/100</span>'
    peak_badge = f'<span class="badge b-peak">Peak {r["peak_interest"]}</span>' if r.get("peak_interest") else ""

    # Suggestions
    sugg_html = "".join(f"<li>{s}</li>" for s in r["suggestions"])

    # Rising queries
    rq_html = ""
    if r.get("rising_queries"):
        items = "".join(f"<li>{q}</li>" for q in r["rising_queries"][:5])
        rq_html = f'<div class="section-label">Rising related searches</div><ul class="items queries">{items}</ul>'

    # PAA
    paa_html = ""
    if r.get("paa"):
        items = "".join(f"<li>{q}</li>" for q in r["paa"])
        paa_html = f'<div class="section-label">People also ask</div><ul class="items paa">{items}</ul>'

    return f"""
<div class="{cls}">
  <div class="card-term">{r['term']}</div>
  <div class="badges">
    {avg_badge}{peak_badge}{trend_badge(r['trend'])}{src_badge}
  </div>
  <div class="score-row">
    <div class="score-lbl">Opportunity</div>
    <div class="bar-track">
      <div class="bar-fill" style="width:{bar_pct}%;background:{color}"></div>
    </div>
    <div class="score-val" style="color:{color}">{r['score']}</div>
  </div>
  {ror_html}
  <div class="section-label">ROR product &amp; social ideas</div>
  <ul class="items">{sugg_html}</ul>
  <div class="two-col">
    {rq_html}
    {paa_html}
  </div>
</div>"""


def build_report(all_groups: list[dict], trending_data: dict | None = None) -> None:
    all_results  = [r for g in all_groups for r in g["results"]]
    total        = len(all_results)
    hot          = sum(1 for r in all_results if r["score"] >= 8)
    rising       = sum(1 for r in all_results if r["trend"] == "rising")
    gaps         = sum(1 for r in all_results if not r["ror_existing"])
    live         = sum(1 for r in all_results if r["data_source"] == "live")
    paa_count    = sum(len(r.get("paa", [])) for r in all_results)

    if live == total:
        notice = ""
    elif live > 0:
        notice = f'<div class="notice">⚡ Partial live data: {live}/{total} terms confirmed via Google Trends API. Remaining show knowledge-seeded estimates.</div>'
    else:
        notice = '<div class="notice">📊 Knowledge-seeded estimates only — re-run <code>python3 scraper.py</code> to fetch live data.</div>'

    groups_html = ""
    for g in all_groups:
        cards = "".join(render_card(r) for r in sorted(g["results"], key=lambda x: -x["score"]))
        groups_html += f'<div class="group"><h2>{g["label"]}</h2><div class="cards">{cards}</div></div>\n'

    seo_section           = build_seo_section(all_groups)
    breakout_section      = build_breakout_section(all_groups)
    gaps_section          = build_gaps_section(all_groups)
    bestseller_section    = build_bestseller_demand_section(all_groups)
    seo_css_clean         = SEO_CSS.strip()
    trending_section_html = build_trending_section(trending_data or {})
    trending_css_clean    = TRENDING_CSS.strip()

    date_str = datetime.now().strftime("%d %B %Y, %H:%M")
    html = HTML_TEMPLATE.format(
        date=date_str, total=total, hot=hot, rising=rising,
        gaps=gaps, live=live, paa_count=paa_count,
        notice=notice, groups_html=groups_html,
        seo_section=seo_section, seo_css=seo_css_clean,
        breakout_section=breakout_section,
        gaps_section=gaps_section,
        bestseller_section=bestseller_section,
        trending_section=trending_section_html,
        trending_css=trending_css_clean,
    )
    REPORT_FILE.write_text(html, encoding="utf-8")
    print(f"Report → {REPORT_FILE}")


# ── Main ──────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    cached = "--cached" in sys.argv

    if cached:
        print("Rock On Ruby — Trend Scraper (cached mode)\n")
    else:
        total_terms = sum(len(g["terms"]) for g in TERM_GROUPS)
        print(f"Rock On Ruby — Trend Scraper (live · pytrends + Serper.dev PAA)")
        print(f"Groups: {len(TERM_GROUPS)}  ·  Terms: {total_terms}")
        print(f"pytrends calls: ~{total_terms * 2} (interest + related per term) · PAA: Serper.dev (score≥6 only)\n")

    all_groups, trending_data = fetch_all(cached=cached)
    build_report(all_groups, trending_data)

    all_results = [r for g in all_groups for r in g["results"]]
    hot    = sorted([r for r in all_results if r["score"] >= 8], key=lambda x: -x["score"])
    rising = sorted(
        [r for r in all_results if r["trend"] == "rising" and r["avg_interest"] > 20],
        key=lambda x: -x["avg_interest"]
    )

    print("\n── Hot Opportunities (8+/10) ──")
    for r in hot:
        src = "●" if r["data_source"] == "live" else "○"
        gap = " [GAP]" if not r["ror_existing"] else ""
        print(f"  {r['score']:2d}/10 {src}  {r['term']}{gap}")

    print("\n── Rising Trends ──")
    for r in rising:
        src = "●" if r["data_source"] == "live" else "○"
        gap = " [GAP]" if not r["ror_existing"] else ""
        print(f"  ~{r['avg_interest']:3d}/100 {src}  {r['term']}{gap}")

    print(f"\n● live  ○ estimated")
    print(f"\nDone.")
    print(f"  HTML report → {REPORT_FILE}")
    print(f"  Cache       → {CACHE_FILE}")
