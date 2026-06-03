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
import re
import sys
import time
import random
from datetime import datetime, timedelta
from html import escape
from pathlib import Path
import requests
from pytrends.request import TrendReq

# ── Config ───────────────────────────────────────────────────────────────────

SERPER_KEY   = os.environ.get("SERPER_API_KEY", "")
SERPAPI_KEY  = os.environ.get("SERPAPI_KEY", "")
DATAFORSEO_LOGIN    = os.environ.get("DATAFORSEO_LOGIN", "")
DATAFORSEO_PASSWORD = os.environ.get("DATAFORSEO_PASSWORD", "")
OUTPUT_DIR   = Path(__file__).parent
REPORT_FILE  = OUTPUT_DIR / "trend_report.html"
CACHE_FILE   = OUTPUT_DIR / "trend_cache.json"
FOCUS_FILE   = OUTPUT_DIR / "ror_focus.json"
OPEN_TRENDS_FILE = OUTPUT_DIR / "open_trends.json"
LAYER4_CACHE = OUTPUT_DIR / "layer4_expanded.json"
SEARCH_CONSOLE_CACHE_FILE = OUTPUT_DIR / "search_console_cache.json"
RANK_TRACKER_CACHE_FILE = OUTPUT_DIR / "rank_tracker_cache.json"
CONTENT_FILE = OUTPUT_DIR / "ror_content_draft.md"

GEO              = "GB"
TIMEFRAME        = "today 3-m"
CATALOGUE_FILE   = OUTPUT_DIR / "shopify_catalogue.json"
TIMEOUT_SECONDS  = 480   # 8-minute hard cap — save & report with whatever was collected
RATE_LIMIT_WAIT  = 15    # seconds to pause after a 429 before retrying
TEAM_INPUT_LIST_URL = os.environ.get(
    "TEAM_INPUT_LIST_URL",
    "https://app.clickup.com/90121649956/v/l/li/901218496536",
)
CONTENT_WORKFLOW_URL = os.environ.get(
    "CONTENT_WORKFLOW_URL",
    "https://github.com/GrahamROR/ror-trend-scraper/actions/workflows/content.yml",
)

_PT: TrendReq | None = None
_CATALOGUE: dict = {}


def trends_client() -> TrendReq:
    """
    pytrends has been replaced by DataForSEO for reliable UK search volume.
    This stub exists so any remaining references do not cause import errors.
    """
    raise RuntimeError(
        "pytrends is no longer used. "
        "Set DATAFORSEO_LOGIN and DATAFORSEO_PASSWORD instead."
    )


def dataforseo_search_volume(term: str) -> dict:
    """
    Fetch real UK monthly search volume from DataForSEO Keywords Data API.
    Returns {"avg": int, "peak": int, "trend": str} or {} on failure.
    Cost: ~$0.0005 per keyword. 50 keywords/week ≈ £1/month.
    """
    if not DATAFORSEO_LOGIN or not DATAFORSEO_PASSWORD:
        return {}

    try:
        import base64
        credentials = base64.b64encode(
            f"{DATAFORSEO_LOGIN}:{DATAFORSEO_PASSWORD}".encode()
        ).decode()

        payload = [{
            "keywords": [term],
            "location_code": 2826,   # United Kingdom
            "language_code": "en",
            "date_from": (
                datetime.now() - timedelta(days=365)
            ).strftime("%Y-%m-%d"),
        }]

        resp = requests.post(
            "https://api.dataforseo.com/v3/keywords_data/google_ads/search_volume/live",
            headers={
                "Authorization": f"Basic {credentials}",
                "Content-Type": "application/json",
            },
            json=payload,
            timeout=30,
        )

        if not resp.ok:
            print(f"  DataForSEO error {resp.status_code} for '{term}'")
            return {}

        data = resp.json()
        tasks = data.get("tasks", [])
        if not tasks or tasks[0].get("status_code") != 20000:
            return {}

        results = tasks[0].get("result", [])
        if not results:
            return {}

        item = results[0]
        avg = int(item.get("search_volume", 0) or 0)

        # Monthly history for trend + peak calculation
        monthly = item.get("monthly_searches", []) or []
        volumes = [int(m.get("search_volume", 0) or 0) for m in monthly]

        if not volumes or max(volumes) == 0:
            return {"avg": avg, "peak": avg, "trend": "stable"}

        peak = max(volumes)

        # Trend: compare last 3 months vs first 3 months
        if len(volumes) >= 6:
            recent = sum(volumes[:3]) / 3
            older  = sum(volumes[-3:]) / 3
            if older > 0:
                if recent > older * 1.15:
                    trend = "rising"
                elif recent < older * 0.85:
                    trend = "falling"
                else:
                    trend = "stable"
            else:
                trend = "stable"
        else:
            trend = "stable"

        return {"avg": avg, "peak": peak, "trend": trend}

    except Exception as e:
        print(f"  DataForSEO exception for '{term}': {e}")
        return {}


def load_catalogue() -> dict:
    global _CATALOGUE
    if CATALOGUE_FILE.exists():
        try:
            _CATALOGUE = json.loads(CATALOGUE_FILE.read_text())
        except Exception:
            pass
    return _CATALOGUE


def load_json_cache(path: Path, fallback):
    if path.exists():
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            pass
    return fallback


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
    """
    Return matching product/collection title if ROR sells something related.
    Requires at least 2 meaningful word matches OR one specific word (6+ chars,
    not in the generic exclusion list) to avoid false matches.
    """
    term_lower = term.lower()

    # Words too generic to match on alone
    GENERIC = {
        "clothing", "fashion", "product", "collection", "gifts", "slogan",
        "custom", "women", "personalised", "birthday", "jumper", "sweatshirt",
        "hoodie", "shirt", "tshirt", "tshirts", "things", "ideas", "style",
        "wear", "outfits", "outfit", "ladies", "mens", "unisex", "sale",
        "cheap", "best", "great", "good", "nice", "cool", "funny", "novelty",
        "print", "design", "embroidered", "personalised", "unique", "gift",
        "with", "from", "that", "this", "your", "they", "have", "here",
        "some", "only", "just", "also", "more", "than", "over", "into",
    }

    # Extract meaningful words (4+ chars, not generic)
    words = [
        w for w in re.sub(r"[^a-z0-9 ]", " ", term_lower).split()
        if len(w) >= 4 and w not in GENERIC
    ]

    # Specific words (6+ chars, not generic) — one match is enough
    specific_words = [w for w in words if len(w) >= 6]

    if not words:
        return ""

    def _matches(title: str) -> bool:
        title_lower = re.sub(r"[^a-z0-9 ]", " ", title.lower())
        title_words = set(title_lower.split())
        # Count how many search words appear in the title
        matched = [w for w in words if w in title_lower]
        specific_matched = [w for w in specific_words if w in title_lower]
        # Pass if: 2+ word matches, OR 1 specific (6+ char) word match
        return len(matched) >= 2 or len(specific_matched) >= 1

    _SKIP_COLL = {
        "gift-vouchers", "all", "frontpage", "homepage-collection",
        "imported", "best-sellers-vs-hidden-gems", "collections",
        "sale", "christmas-sale", "year-sale", "sale-tops", "sale-accessories",
        "winter-sale", "holiday-bundle", "basics", "easter",
    }

    if _CATALOGUE:
        # Collections first
        for c in _CATALOGUE.get("collections", []):
            if c.get("handle") in _SKIP_COLL:
                continue
            if _matches(c["title"]):
                return c["title"]

        # Bestsellers
        for b in _CATALOGUE.get("bestsellers", []):
            if _matches(b["title"]):
                return b["title"]

        # All products
        for p in _CATALOGUE.get("products", []):
            p_text = p["title"] + " " + " ".join(p.get("tags", []))
            if _matches(p_text):
                return p["title"]

    # Static fallback
    for existing in ROR_EXISTING:
        if _matches(existing):
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
    """Single pytrends interest-over-time call. Returns parsed dict or {}.
    Retries once after RATE_LIMIT_WAIT seconds if a 429 is returned."""
    try:
        pt = trends_client()
        pt.build_payload([q], cat=0, timeframe=TIMEFRAME, geo=GEO)
        df = pt.interest_over_time()
    except Exception as e:
        if "429" in str(e):
            print(f"    429 — waiting {RATE_LIMIT_WAIT}s before retry")
            time.sleep(RATE_LIMIT_WAIT)
            try:
                pt = trends_client()
                pt.build_payload([q], cat=0, timeframe=TIMEFRAME, geo=GEO)
                df = pt.interest_over_time()
            except Exception:
                return {}
        else:
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
    Fetch search volume for a term.
    Uses DataForSEO if credentials are set (real UK data).
    Falls back to empty dict if not configured.
    """
    # Try DataForSEO first (real data)
    if DATAFORSEO_LOGIN and DATAFORSEO_PASSWORD:
        result = dataforseo_search_volume(term)
        if result:
            return result

    # No credentials — return empty so scraper uses seed estimates
    print(f"  No DataForSEO credentials — skipping live volume for '{term}'")
    return {}


def pytrends_related_queries(term: str) -> dict[str, list[str]]:
    """
    Rising + top + breakout related queries via pytrends.
    Breakout = Google marks the rising value as 'Breakout' (>5000% increase).
    Returns {"rising": [...], "top": [...], "breakout": [...]}.
    Retries once after RATE_LIMIT_WAIT seconds on a 429.
    """
    out = {"rising": [], "top": [], "breakout": []}

    def _do_call():
        pt = trends_client()
        pt.build_payload([term], cat=0, timeframe=TIMEFRAME, geo=GEO)
        return pt.related_queries()

    try:
        related = _do_call()
    except Exception as e:
        if "429" in str(e):
            print(f"    429 — waiting {RATE_LIMIT_WAIT}s before retry")
            time.sleep(RATE_LIMIT_WAIT)
            try:
                related = _do_call()
            except Exception as e2:
                print(f"    Related queries error for '{term}': {e2}")
                return out
        else:
            print(f"    Related queries error for '{term}': {e}")
            return out

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
    Retries up to 3 times with a 15-second wait on 429 rate-limit errors."""
    out: dict[str, list[str]] = {"rising": [], "top": []}
    MAX_RETRIES = 3
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            pt = trends_client()
            pt.build_payload([term], cat=0, timeframe="now 7-d", geo=GEO, gprop=gprop)
            related = pt.related_queries()
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
            if "429" in str(e) and attempt < MAX_RETRIES:
                print(f"    429 rate limit — waiting {RATE_LIMIT_WAIT}s then retrying (attempt {attempt}/{MAX_RETRIES})")
                time.sleep(RATE_LIMIT_WAIT)
            else:
                print(f"    Weekly trends error '{term}' (gprop={gprop or 'web'}): {e}")
                return out
    return out


def empty_open_trends(source_note: str = "") -> dict:
    return {
        "web": {"top": [], "rising": []},
        "youtube": {"top": [], "rising": []},
        "weekly_ok": False,
        "source_note": source_note,
    }


def normalise_open_trends(raw: dict, source_note: str = "") -> dict:
    """Normalise raw open-trends input without scoring, filtering or ROR matching."""
    out = empty_open_trends(source_note or raw.get("source_note", ""))
    for channel in ("web", "youtube"):
        channel_data = raw.get(channel, {}) if isinstance(raw, dict) else {}
        for bucket in ("top", "rising"):
            values = channel_data.get(bucket, []) if isinstance(channel_data, dict) else []
            out[channel][bucket] = [str(v).strip() for v in values if str(v).strip()][:10]
    out["weekly_ok"] = any(out[channel][bucket] for channel in ("web", "youtube") for bucket in ("top", "rising"))
    return out


def load_open_trends_file() -> dict | None:
    """
    Optional raw open-trends import.

    Expected shape:
    {
      "web": {"top": ["..."], "rising": ["..."]},
      "youtube": {"top": ["..."], "rising": ["..."]},
      "source_note": "Google Trends, UK, past 7 days"
    }
    """
    if not OPEN_TRENDS_FILE.exists():
        return None
    try:
        raw = json.loads(OPEN_TRENDS_FILE.read_text())
        return normalise_open_trends(raw, raw.get("source_note", "Imported from open_trends.json"))
    except Exception as e:
        print(f"  open_trends.json ignored: {e}")
        return None


def fetch_pytrends_daily_fallback() -> dict:
    """
    Free fallback only.

    pytrends does not expose unseeded UK past-week top/rising web and YouTube
    queries. This keeps the dashboard populated with today's UK trending searches
    without pretending it is the requested weekly open-trends feed.
    """
    today_top: list[str] = []
    try:
        df = trends_client().trending_searches(pn="united_kingdom")
        today_top = [str(t) for t in df.iloc[:, 0].dropna().tolist()[:10]]
        print(f"  Today's trending: {len(today_top)} topics fetched")
    except Exception as e:
        print(f"  trending_searches() failed: {e}")

    return {
        "web": {"top": today_top, "rising": []},
        "youtube": {"top": [], "rising": []},
        "weekly_ok": False,
        "source_note": "Fallback only: pytrends daily UK trending searches. Add open_trends.json or SERPAPI_KEY for true past-week open trends.",
    }


def fetch_trending_queries_uk(all_groups: list[dict], run_start: float | None = None) -> dict:
    """
    Fetch raw UK open-trends data for the dashboard and content prompt.

    This is intentionally separate from programmed ROR keyword tracking. It must
    not seed Google Trends with ROR terms, score results, or filter them through
    products. If a true past-week source is not available, the fallback is labelled
    clearly so Bethan is not asked to act on pretend weekly data.
    """
    imported = load_open_trends_file()
    if imported:
        print("  Open UK trends loaded from open_trends.json")
        return imported

    if SERPAPI_KEY:
        print("  SERPAPI_KEY found, but open weekly web/YouTube trend import is not wired yet.")
        print("  Add open_trends.json to feed raw past-week top/rising queries into the dashboard.")

    return fetch_pytrends_daily_fallback()


# ── Fetch all data ────────────────────────────────────────────────────────────

def fetch_all(cached: bool = False) -> tuple[list[dict], dict]:
    """
    Fetch or load all data. Returns (all_groups, trending_data) tuple.
    Hard cap of TIMEOUT_SECONDS — saves whatever has been collected and exits.
    """
    if cached and CACHE_FILE.exists():
        print("  Loading from cache...")
        raw = json.loads(CACHE_FILE.read_text())
        if isinstance(raw, list):
            return raw, {}
        return raw.get("groups", []), raw.get("trending", {})

    run_start    = time.monotonic()
    all_groups   = []
    total_groups = len(TERM_GROUPS)
    timed_out    = False

    def _elapsed() -> float:
        return time.monotonic() - run_start

    def _time_ok(reserve: float = 0) -> bool:
        return _elapsed() < TIMEOUT_SECONDS - reserve

    for g_idx, group in enumerate(TERM_GROUPS):
        if not _time_ok(reserve=30):
            print(f"\n⏱ {TIMEOUT_SECONDS//60}-min timeout reached — stopping after {g_idx}/{total_groups} groups")
            timed_out = True
            break

        label     = group["label"]
        term_list = [(t[0], t[1], t[2]) for t in group["terms"]]
        terms     = [t[0] for t in term_list]

        print(f"\n[{g_idx+1}/{total_groups}] {label}  (elapsed {_elapsed():.0f}s)")

        # ── 1. Trends timeseries (pytrends, 1 call per term) ──
        ts_data = {}
        for term in terms:
            if not _time_ok(reserve=60):
                print(f"  ⏱ Timeout — skipping remaining timeseries calls")
                timed_out = True
                break
            print(f"  → Trends: {term}")
            ts_data[term] = pytrends_interest_over_time(term)
            time.sleep(random.uniform(1.5, 2.5))

        # ── 2. Related queries (pytrends, includes breakout detection) ──
        related_data = {}
        for term in terms:
            if not _time_ok(reserve=60):
                print(f"  ⏱ Timeout — skipping remaining related-query calls")
                timed_out = True
                break
            print(f"  → Related queries: {term}")
            related_data[term] = pytrends_related_queries(term)
            if related_data[term].get("breakout"):
                print(f"    🚨 BREAKOUT detected in related: {related_data[term]['breakout']}")
            time.sleep(random.uniform(1.5, 2.5))

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
            live    = ts_data.get(term, {})
            avg     = live.get("avg", seed_avg)
            peak    = live.get("peak", 0)
            trend   = live.get("trend", seed_trend)
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

        if timed_out:
            break

        if g_idx < total_groups - 1 and _time_ok(reserve=30):
            pause = random.uniform(2.0, 3.5)
            print(f"  Pausing {pause:.1f}s...")
            time.sleep(pause)

    print(f"\n── Trending Queries UK  (elapsed {_elapsed():.0f}s) ──")
    trending_data = fetch_trending_queries_uk(all_groups, run_start=run_start)

    # Cache results
    CACHE_FILE.write_text(json.dumps({"groups": all_groups, "trending": trending_data}, indent=2))
    total_elapsed = _elapsed()
    print(f"\nCached to: {CACHE_FILE}  ({total_elapsed:.0f}s total)")
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


def _rank_status(rank) -> tuple[str, str]:
    if rank is None:
        return "Not top 20", "rank-bad"
    if rank <= 3:
        return f"#{rank}", "rank-good"
    if rank <= 10:
        return f"#{rank}", "rank-mid"
    return f"#{rank}", "rank-bad"


def _row_priority(row: dict) -> tuple[str, int, str]:
    impressions = int(row.get("gsc_impressions", 0) or 0)
    clicks = int(row.get("gsc_clicks", 0) or 0)
    ctr = float(row.get("gsc_ctr", 0) or 0)
    rank = row.get("ror_rank")
    score = int(row.get("priority_score", 0) or 0)

    if not score:
        score = min(int(impressions / 8), 55)
        if rank is None:
            score += 40
        elif rank == 1:
            score += 10
        elif rank <= 3:
            score += 18
        elif rank <= 10:
            score += 32
        else:
            score += 28
        if impressions >= 100 and ctr < 2.5:
            score += 10
        score += min(clicks, 12)

    if rank is None:
        label = "Fix visibility gap"
        why = "Google Search Console sees the query, but ROR is not showing in the live top 20."
    elif rank == 1:
        label = "Protect winner"
        why = "ROR already owns this result. Keep it fresh without rewriting the page heavily."
    elif rank <= 3:
        label = "Push to #1"
        why = "ROR is already near the top. Small page improvements may be enough."
    elif rank <= 10:
        label = "Move to top 3"
        why = "ROR is on page 1 but competitors are still above it."
    else:
        label = "Build support"
        why = "ROR is visible, but the page needs stronger supporting content and links."
    return label, score, why


def _sorted_rank_results(limit: int | None = None) -> list[dict]:
    rank_cache = load_json_cache(RANK_TRACKER_CACHE_FILE, {})
    results = rank_cache.get("results", [])
    sorted_results = sorted(
        results,
        key=lambda row: (
            -_row_priority(row)[1],
            -int(row.get("gsc_impressions", 0) or 0),
            row.get("ror_rank") if row.get("ror_rank") is not None else 99,
        ),
    )
    return sorted_results[:limit] if limit else sorted_results


def _target_link(row: dict) -> str:
    target_page = row.get("target_page") or row.get("ror_url") or ""
    if target_page.startswith("https://"):
        return f'<a href="{escape(target_page)}" target="_blank" rel="noopener">{escape(target_page.replace("https://", ""))}</a>'
    return escape(target_page or "No mapped page")


def _content_needed(row: dict) -> str:
    query = row.get("query", "")
    rank = row.get("ror_rank")
    if rank is None:
        return f"Generate a page intro rewrite, 4 FAQs, internal-link copy and one supporting blog for '{query}'."
    if rank == 1:
        return f"Generate one light support pack for '{query}': Pinterest pin copy, a short caption and one internal-link suggestion."
    if rank <= 3:
        return f"Generate a focused FAQ block, meta title option and image alt text ideas for '{query}'."
    if rank <= 10:
        return f"Generate a page intro rewrite, FAQ block, internal-link copy and one social/Pinterest support asset for '{query}'."
    return f"Generate a supporting blog, page intro rewrite, FAQ block and internal-link plan for '{query}'."


def _content_brief(row: dict) -> str:
    query = row.get("query", "")
    target = row.get("target_page") or row.get("ror_url") or "mapped ROR page"
    rank = row.get("ror_rank")
    rank_text = f"#{rank}" if rank is not None else "not top 20"
    competitors = ", ".join(c.get("domain", "") for c in row.get("competitors_above", [])[:4] if c.get("domain")) or "none captured"
    label, score, why = _row_priority(row)
    return (
        f"Keyword: {query}\n"
        f"Priority: {label}, score {score}\n"
        f"Mapped page: {target}\n"
        f"GSC: {row.get('gsc_impressions', 0)} impressions, {row.get('gsc_clicks', 0)} clicks, avg position {row.get('gsc_position', 'unknown')}\n"
        f"Live Google UK rank: {rank_text}\n"
        f"Competitors above ROR: {competitors}\n"
        f"Why this matters: {why}\n"
        f"Generate finished content only. Needed output: {_content_needed(row)}"
    )


def _visibility_action(row: dict) -> str:
    query = row.get("query", "")
    target = row.get("target_page", "")
    rank = row.get("ror_rank")
    competitors = row.get("competitors_above", [])
    competitor_names = ", ".join(c.get("domain", "") for c in competitors[:3] if c.get("domain"))

    if rank is None:
        return (
            f"Check why the mapped page is not showing in the top 20 for '{escape(query)}'. "
            f"Compare the page title, collection intro, H1 and first 80 words against the pages currently ranking. "
            f"If the query fits ROR, add the exact phrase naturally, add 3 internal links to {escape(target)}, "
            "and create one supporting blog or FAQ section that answers the buyer intent."
        )

    if rank == 1:
        return (
            "Protect this ranking. Do not rewrite the page heavily. Add one fresh internal link from a related blog or collection, "
            "keep the product examples current, and use this keyword in one supporting social/Pinterest asset so the page keeps getting visibility signals."
        )

    if rank <= 3:
        return (
            f"Push this from top 3 to position 1. Add a short FAQ that answers '{escape(query)}', "
            "tighten the meta title around the exact phrase, and add one product or lifestyle image alt text that matches the search intent."
        )

    if rank <= 10:
        competitor_text = f" The main pages above ROR include {escape(competitor_names)}." if competitor_names else ""
        return (
            f"Move this page towards the top 3. Rewrite the first 80 words of the mapped page so '{escape(query)}' is obvious, "
            "add 2 FAQ questions buyers would actually ask, add internal links from related product or blog pages, "
            "and make the page explain the gift/use case faster above the fold."
            f"{competitor_text}"
        )

    return (
        f"This is a page 2 ranking. Build one supporting blog around '{escape(query)}', link it back to the mapped page, "
        "then improve the mapped page title, intro and FAQ so Google has a clearer landing page for the query."
    )


def build_visibility_rank_section() -> str:
    """Return live rank evidence from Search Console plus Serper spot checks."""
    rank_cache = load_json_cache(RANK_TRACKER_CACHE_FILE, {})
    gsc_cache = load_json_cache(SEARCH_CONSOLE_CACHE_FILE, {})
    results = _sorted_rank_results()

    if not results:
        return f"""
<section class="dashboard-section visibility-section">
  <h2>Where We Rank</h2>
  <p class="section-intro">No live rank checks yet. Run <code>python rank_tracker.py --limit 100</code> after Search Console has been refreshed.</p>
</section>"""

    found = sum(1 for r in results if r.get("ror_found"))
    top3 = sum(1 for r in results if r.get("ror_rank") is not None and r.get("ror_rank") <= 3)
    page1 = sum(1 for r in results if r.get("ror_rank") is not None and r.get("ror_rank") <= 10)
    missing = sum(1 for r in results if r.get("ror_rank") is None)
    window = ""
    if rank_cache.get("source_gsc_window"):
        source = rank_cache["source_gsc_window"]
        window = f"{source.get('start_date', '')} to {source.get('end_date', '')}"
    elif gsc_cache:
        window = f"{gsc_cache.get('start_date', '')} to {gsc_cache.get('end_date', '')}"

    rows = ""
    for row in results:
        rank_label, rank_cls = _rank_status(row.get("ror_rank"))
        target_link = _target_link(row)
        competitors = row.get("competitors_above", [])
        competitor_html = "".join(
            f'<span class="competitor-chip">{escape(c.get("domain", ""))}</span>'
            for c in competitors[:4]
            if c.get("domain")
        ) or '<span class="muted-small">No competitor list captured.</span>'
        rows += f"""
<tr>
  <td class="kw-cell">{escape(row.get("query", ""))}</td>
  <td class="page-cell">{target_link}</td>
  <td class="metric-cell">{row.get("gsc_impressions", 0)}</td>
  <td class="metric-cell">{row.get("gsc_clicks", 0)}</td>
  <td class="metric-cell">{row.get("gsc_position", "—")}</td>
  <td class="metric-cell"><span class="rank-pill {rank_cls}">{rank_label}</span></td>
  <td>{competitor_html}</td>
</tr>"""

    return f"""
<section class="dashboard-section visibility-section">
  <h2>Where We Rank</h2>
  <p class="section-intro">For keywords Google already knows about us for, this shows the Search Console position and a live Google UK spot check. Window: {escape(window or "latest cached Search Console data")}.</p>
  <div class="visibility-stats">
    <div><strong>{len(results)}</strong><span>Keywords checked</span></div>
    <div><strong>{found}</strong><span>ROR found</span></div>
    <div><strong>{top3}</strong><span>Top 3</span></div>
    <div><strong>{page1}</strong><span>Page 1</span></div>
    <div><strong>{missing}</strong><span>Not top 20</span></div>
  </div>
  <div class="visibility-key">
    <span><b class="key-dot key-good"></b>Green = top 3</span>
    <span><b class="key-dot key-mid"></b>Amber = 4-10</span>
    <span><b class="key-dot key-bad"></b>Red = not top 20</span>
  </div>
  <div class="table-wrap">
    <table class="seo-table visibility-table">
      <thead>
        <tr>
          <th>Keyword</th>
          <th>Mapped ROR page</th>
          <th>Impr.</th>
          <th>Clicks</th>
          <th>GSC pos.</th>
          <th>Live rank</th>
          <th>Above ROR</th>
        </tr>
      </thead>
      <tbody>{rows}</tbody>
    </table>
  </div>
</section>"""


def build_page_seo_fix_section() -> str:
    """Group organic visibility fixes by ROR page so the site work is clearer."""
    results = _sorted_rank_results()
    if not results:
        return """
<section class="dashboard-section">
  <h2>Website & SEO Fixes</h2>
  <p class="section-intro">No page-level fixes yet because no rank cache exists.</p>
</section>"""

    by_page: dict[str, list[dict]] = {}
    for row in results:
        page = row.get("target_page") or row.get("ror_url") or "No mapped page"
        by_page.setdefault(page, []).append(row)

    page_blocks = ""
    for page, rows in sorted(by_page.items(), key=lambda item: -sum(_row_priority(r)[1] for r in item[1]))[:20]:
        rows_sorted = sorted(rows, key=lambda r: -_row_priority(r)[1])
        primary = rows_sorted[0]
        target_link = _target_link(primary)
        keywords = ", ".join(r.get("query", "") for r in rows_sorted[:5])
        ranks = ", ".join(
            f"{r.get('query', '')}: #{r.get('ror_rank')}" if r.get("ror_rank") is not None else f"{r.get('query', '')}: not top 20"
            for r in rows_sorted[:4]
        )
        label, score, why = _row_priority(primary)
        page_blocks += f"""
<article class="page-fix-card">
  <div class="action-head">
    <span class="pill pill-high">Priority {score}</span>
    <span class="pill pill-aov">{escape(label)}</span>
  </div>
  <h3>{target_link}</h3>
  <div class="fix-grid">
    <div><h4>Keywords affected</h4><p>{escape(keywords)}</p></div>
    <div><h4>Ranking evidence</h4><p>{escape(ranks)}</p></div>
    <div><h4>Why</h4><p>{escape(why)}</p></div>
  </div>
  <div class="fix-work">
    <strong>Exact page work:</strong> Rewrite the first 80 words around the primary search phrase "{escape(primary.get('query', ''))}". Add 2 to 4 buyer-question FAQs specific to this page, improve the meta title around the phrase if it is missing, add image alt text that describes the product and gift/use case, and add internal links from related products, blogs or collections.
  </div>
  <div class="fix-work">
    <strong>System-generated content needed:</strong> {escape(_content_needed(primary))}
  </div>
</article>"""

    return f"""
<section class="dashboard-section">
  <h2>Website & SEO Fixes</h2>
  <p class="section-intro">Same evidence as the keyword table, grouped by the actual ROR page that needs work.</p>
  <div class="page-fix-list">{page_blocks}</div>
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
    """Cross-reference Shopify bestsellers against trend and Search Console data."""
    if not _CATALOGUE or not _CATALOGUE.get("bestsellers"):
        return ""

    all_results  = [r for g in all_groups for r in g["results"]]
    gsc_cache = load_json_cache(SEARCH_CONSOLE_CACHE_FILE, {})
    gsc_queries = gsc_cache.get("queries", [])
    bestsellers  = [b for b in _CATALOGUE["bestsellers"]
                    if b["title"] and "personalisation" not in b["title"].lower()
                    and "back of the neck" not in b["title"].lower()][:20]

    def meaningful_words(text: str) -> set[str]:
        generic = {"the", "and", "for", "with", "personalised", "custom", "slogan", "shirt", "tshirt", "sweatshirt", "hoodie", "gift"}
        return {
            w for w in re.sub(r"[^a-z0-9 ]", " ", text.lower()).split()
            if len(w) >= 4 and w not in generic
        }

    def trend_match(title: str) -> dict | None:
        bs_words = meaningful_words(title)
        best = None
        best_overlap = 0
        for r in all_results:
            overlap = len(bs_words & meaningful_words(r["term"]))
            if overlap > best_overlap:
                best = r
                best_overlap = overlap
        return best if best_overlap >= 1 else None

    def gsc_position(title: str) -> str:
        bs_words = meaningful_words(title)
        best = None
        best_overlap = 0
        for q in gsc_queries:
            overlap = len(bs_words & meaningful_words(q.get("query", "")))
            if overlap > best_overlap:
                best = q
                best_overlap = overlap
        if not best or best_overlap < 1:
            return "—"
        return f"{float(best.get('position', 0) or 0):.2f}"

    rows = ""
    for bs in bestsellers:
        title   = bs["title"]
        revenue_value = float(bs.get("revenue", 0) or 0)
        revenue = f"£{revenue_value:,.0f}" if revenue_value else "—"
        orders  = str(bs.get("orders", "—"))
        handle  = bs.get("handle", "")

        # Link the product title if we have a handle
        if handle:
            title_cell = f'<a href="https://rockonruby.co.uk/products/{handle}" target="_blank" rel="noopener">{title}</a>'
        else:
            title_cell = title

        matched = trend_match(title)
        position = gsc_position(title)

        if matched:
            s_col  = score_color(matched["score"])
            t_icon = {"rising": "↑", "falling": "↓", "stable": "→"}.get(matched["trend"], "→")
            t_col  = {"rising": "var(--green)", "falling": "var(--red)", "stable": "var(--muted)"}.get(matched["trend"], "var(--muted)")
            demand_cell = (
                f'<span style="color:{s_col};font-weight:700">{matched["score"]}/10</span><br>'
                f'<span style="color:{t_col};font-size:.72rem">{t_icon} {matched["trend"].capitalize()} · ~{matched["avg_interest"]}/100</span>'
            )
            flag_cell = '<span class="muted-small">Matched search demand</span>'
        else:
            demand_cell = '<span style="color:var(--muted);font-size:.75rem">No trend match</span>'
            if revenue_value > 500:
                flag_cell = '<span class="act act-create">Content gap</span>'
            else:
                flag_cell = '<span class="muted-small">No gap flagged</span>'

        rows += f"""
<tr>
  <td class="bs-prod">{title_cell}</td>
  <td class="bs-rev">{revenue}</td>
  <td style="text-align:center;color:var(--muted)">{orders}</td>
  <td style="text-align:center">{demand_cell}</td>
  <td style="text-align:center;color:var(--muted)">{position}</td>
  <td style="text-align:center">{flag_cell}</td>
</tr>"""

    return f"""
<section class="bs-section">
  <h2 class="bs-header">Bestsellers</h2>
  <p class="bs-sub">Top-selling Shopify products matched against trend cache demand and Search Console query position. Revenue over £500 with no trend match is flagged as a content gap.</p>
  <div class="table-wrap">
  <table class="bs-table">
    <thead>
      <tr>
        <th>Product</th>
        <th>Revenue (90d)</th>
        <th style="text-align:center">Orders</th>
        <th style="text-align:center">Search demand</th>
        <th style="text-align:center">GSC position</th>
        <th style="text-align:center">Flag</th>
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
        trending_data = empty_open_trends("No open UK trends captured this run.")

    weekly_ok = trending_data.get("weekly_ok", False)
    source_note = trending_data.get("source_note", "")
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

    top_rows = merge_rows(web.get("top", []), yt.get("top", []))
    rising_rows = merge_rows(web.get("rising", []), yt.get("rising", []))

    def render_table(rows: list[tuple[str, str]], empty_msg: str = "No data captured this run.") -> str:
        if not rows:
            return f"<p style='color:var(--muted);font-size:.8rem'>{empty_msg}</p>"
        trs = ""
        for i, (query, src) in enumerate(rows, 1):
            src_cls = "tq-web" if src == "Web" else "tq-yt"
            trs += f"""
<tr>
  <td class="tq-num">{i}</td>
  <td class="tq-query">{escape(query)}</td>
  <td><span class="tq-src {src_cls}">{src}</span></td>
</tr>"""
        return f"""<table class="tq-table">
  <thead><tr><th>#</th><th>Query</th><th>Source</th></tr></thead>
  <tbody>{trs}
  </tbody>
</table>"""

    weekly_note = "" if weekly_ok else \
        ' &nbsp;<span style="color:var(--yellow);font-size:.75rem">(True past-week open trends unavailable in this run)</span>'
    source_html = f'<p class="trending-sub">{escape(source_note)}</p>' if source_note else ""

    return f"""
<section class="trending-section">
  <h2 class="trending-title">UK Trending Queries</h2>
  <p class="trending-sub">Raw Google trend feed &nbsp;·&nbsp; UK &nbsp;·&nbsp; Past week &nbsp;·&nbsp; Web search and YouTube search{weekly_note}</p>
  {source_html}
  <div class="trending-tables">
    <div class="trending-table-wrap">
      <h3>Top Searches UK — Past Week</h3>
      {render_table(top_rows, "No top searches captured for the past-week open trend feed.")}
    </div>
    <div class="trending-table-wrap">
      <h3>Rising Searches UK — Past Week</h3>
      {render_table(rising_rows, "No rising searches captured for the past-week open trend feed.")}
    </div>
  </div>
</section>"""


def build_trend_opportunities_section(all_groups: list[dict]) -> str:
    """Return rising keyword opportunities from trend_cache.json only."""
    all_results = [r for g in all_groups for r in g["results"]]
    rising = [
        r for r in all_results
        if r.get("trend") == "rising" and int(r.get("score", 0) or 0) >= 5
    ]
    rising.sort(key=lambda r: (-int(r.get("score", 0) or 0), -int(r.get("avg_interest", 0) or 0)))
    gaps = [r for r in rising if not r.get("ror_existing")]
    opportunities = [r for r in rising if r.get("ror_existing")]

    def render_cards(items: list[dict], empty: str) -> str:
        if not items:
            return f'<p class="section-intro">{escape(empty)}</p>'
        cards = ""
        for r in items[:18]:
            page = seo_page_map(r["term"], r.get("ror_existing", ""))
            page_html = _as_link(page) if page.startswith("rockonruby.co.uk/") else escape(page)
            cards += f"""
<article class="content-queue-card">
  <h3>{escape(r["term"])}</h3>
  <div class="fix-grid">
    <div><h4>Search demand</h4><p>Score {r.get("score", 0)}/10, rising, ~{r.get("avg_interest", 0)}/100 interest.</p></div>
    <div><h4>ROR page</h4><p>{page_html}</p></div>
    <div><h4>Next move</h4><p>{escape(seo_action(r.get("score", 0), r.get("trend", ""), r.get("ror_existing", "")))}</p></div>
  </div>
</article>"""
        return f'<div class="content-queue">{cards}</div>'

    return f"""
<section class="dashboard-section">
  <h2>Trends</h2>
  <p class="section-intro">Rising keywords from the trend cache only. No rank tracking, no Search Console data, and no repeated organic visibility table.</p>
  <h3 class="subsection-title">Gap — no ROR page yet</h3>
  {render_cards(gaps, "No rising gaps found in the current trend cache.")}
  <h3 class="subsection-title">Opportunity — ROR ranks but can improve</h3>
  {render_cards(opportunities, "No rising mapped opportunities found in the current trend cache.")}
</section>"""


def build_weekly_actions_section(all_groups: list[dict]) -> str:
    """Return top 5 weekly actions from rank_tracker_cache.json only."""
    top = _sorted_rank_results(limit=5)
    if not top:
        return """
<section class="dashboard-section">
  <h2>Weekly Actions</h2>
  <p class="section-intro">No organic visibility actions yet. Refresh Search Console and run the rank tracker.</p>
</section>"""

    def action_label(row: dict) -> str:
        rank = row.get("ror_rank")
        if rank is None:
            return "Fix"
        if rank == 1:
            return "Protect"
        if rank <= 10:
            return "Push"
        return "Build"

    def action_reason(row: dict, label: str) -> str:
        impressions = int(row.get("gsc_impressions", 0) or 0)
        rank = row.get("ror_rank")
        if label == "Protect":
            return f"ROR is already live rank #{rank} with {impressions} impressions, so keep the page fresh without a heavy rewrite."
        if label == "Push":
            return f"ROR is visible with {impressions} impressions, and a focused page update could move it closer to the top 3."
        if label == "Fix":
            return f"Search Console shows {impressions} impressions, but ROR is not in the live top 20, so Graham should check the mapped page first."
        return f"ROR has {impressions} impressions but needs stronger support content and internal links before it can climb."

    cards = ""
    for row in top:
        label = action_label(row)
        target_page = row.get("target_page") or row.get("ror_url") or "No mapped page"
        owner = "Graham" if label == "Fix" else "Bethan"
        reason = action_reason(row, label)
        page_html = _target_link(row)
        cards += f"""
<article class="action-card">
  <div class="action-head">
    <span class="pill pill-high">{escape(label)}</span>
    <span class="pill pill-aov">Owner: {escape(owner)}</span>
  </div>
  <h3>{escape(row.get('query', ''))}</h3>
  <div class="dia-grid">
    <div class="dia-box"><h4>Reason</h4><p>{escape(reason)}</p></div>
    <div class="dia-box"><h4>Mapped page</h4><p>{page_html}</p></div>
    <div class="dia-box"><h4>Owner</h4><p>{escape(owner)}</p></div>
  </div>
</article>"""

    return f"""
<section class="dashboard-section">
  <h2>Weekly Actions</h2>
  <p class="section-intro">Top 5 actions from rank tracking only. This tab is deliberately short: what to act on, why, where, and who owns it.</p>
  <div class="action-list">{cards}</div>
</section>"""


def build_calendar_section() -> str:
    """Return a simple calendar signal section from ror_focus.json."""
    seasons = FOCUS_CONFIG.get("upcoming_seasons", [])
    hero_products = FOCUS_CONFIG.get("hero_products", [])
    collections = FOCUS_CONFIG.get("current_collections", [])

    def _items(values: list[str], empty: str) -> str:
        if not values:
            return f"<li>{empty}</li>"
        return "".join(f"<li>{v}</li>" for v in values[:12])

    return f"""
<section class="dashboard-section">
  <h2>Calendar Signals</h2>
  <p class="section-intro">This is the commercial context layer. It should eventually read ClickUp content, email and production calendars, but it starts with <code>ror_focus.json</code>.</p>
  <div class="info-grid">
    <div class="info-panel">
      <h3>Upcoming seasons</h3>
      <ul class="plain-list">{_items(seasons, "No upcoming seasons configured.")}</ul>
    </div>
    <div class="info-panel">
      <h3>Hero products</h3>
      <ul class="plain-list">{_items(hero_products, "No hero products configured.")}</ul>
    </div>
    <div class="info-panel">
      <h3>Current collections</h3>
      <ul class="plain-list">{_items(collections, "No current collections configured.")}</ul>
    </div>
  </div>
</section>"""


def build_team_inputs_section() -> str:
    """Return the team input panel. Actual ingestion comes in the next phase."""
    return f"""
<section class="dashboard-section">
  <h2>Team Inputs</h2>
  <p class="section-intro">This is the human signal layer. Team notes from ClickUp will help the system find opportunities that keyword lists miss.</p>
  <div class="team-input-card">
    <h3>Team Trend &amp; Content Ideas Inbox</h3>
    <p>Add customer questions, TikTok observations, product push ideas, blog angles, reel ideas, collection/drop notes and competitor observations.</p>
    <a class="report-btn" href="{TEAM_INPUT_LIST_URL}" target="_blank" rel="noopener">Add or review team ideas in ClickUp</a>
  </div>
  <div class="info-grid">
    <div class="info-panel"><h3>Example input</h3><p>Airport outfit planning is everywhere.</p></div>
    <div class="info-panel"><h3>System read</h3><p>Connect to summer totes, caps and make-up bags.</p></div>
    <div class="info-panel"><h3>Possible action</h3><p>Create a summer travel content pack if it fits the calendar and product priorities.</p></div>
  </div>
</section>"""


def build_content_pack_section(all_groups: list[dict]) -> str:
    """Return approved content packs parsed from ror_content_draft.md."""
    if not CONTENT_FILE.exists():
        return """
<section class="dashboard-section">
  <h2>Content Packs</h2>
  <p class="section-intro">No content draft exists yet. Run <code>python content_generator.py --no-ai</code> to create outlines for review.</p>
</section>"""

    md = CONTENT_FILE.read_text(encoding="utf-8")
    packs: list[dict] = []
    for pack_match in re.finditer(
        r"^## (?!System Focus|Trend Note|How this works|Design Rules|Core Visual|Type Direction|Palette Direction)([^\n]+)\n+(.*?)(?=\n^## |\Z)",
        md,
        re.DOTALL | re.MULTILINE,
    ):
        keyword = pack_match.group(1).strip()
        body = pack_match.group(2).strip()
        if "### Approved ClickUp Task Breakdown" not in body:
            continue
        h1_match = re.search(r"\*\*H1:\*\*\s*(.+)", body)
        h1 = h1_match.group(1).strip() if h1_match else "No H1 found"
        if "In ClickUp" in body:
            status = "In ClickUp"
        elif "### Blog (Finished" in body or "Blogs generated:" in md:
            status = "Blog generated"
        else:
            status = "Outline ready"
        packs.append({"keyword": keyword, "h1": h1, "status": status})

    cards = ""
    for pack in packs:
        cards += f"""
<article class="content-queue-card">
  <div class="action-head"><span class="pill pill-aov">{escape(pack["status"])}</span></div>
  <h3>{escape(pack["keyword"])}</h3>
  <p class="muted-small">H1: {escape(pack["h1"])}</p>
  <div class="fix-grid">
    <div><h4>Formats</h4><p>Blog, Email, Reel, Stories, Carousel, TikTok, Pinterest</p></div>
    <div><h4>Status</h4><p>{escape(pack["status"])}</p></div>
    <div><h4>Source</h4><p>ror_content_draft.md approved pack</p></div>
  </div>
</article>"""

    if not cards:
        cards = '<p class="section-intro">No approved content packs found in ror_content_draft.md.</p>'

    return f"""
<section class="dashboard-section">
  <h2>Content Packs</h2>
  <p class="section-intro">Approved packs only. This tab shows what Bethan should make this week, without repeating keyword scores or rank tables.</p>
  <div class="content-queue">{cards}</div>
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

  .tabs {{ display: flex; gap: .5rem; flex-wrap: wrap; padding: 1rem 2rem;
           background: rgba(255,255,255,.03); border-bottom: 1px solid rgba(255,255,255,.06);
           position: sticky; top: 0; z-index: 10; backdrop-filter: blur(8px); }}
  .tab-btn {{ border: 1px solid rgba(255,255,255,.1); background: rgba(255,255,255,.05);
              color: var(--text); border-radius: 6px; min-height: 36px; padding: 0 .85rem;
              font-size: .82rem; font-weight: 650; cursor: pointer; }}
  .tab-btn.active {{ background: var(--pink); border-color: var(--pink); color: #fff; }}
  .tab-panel {{ display: none; }}
  .tab-panel.active {{ display: block; }}
  .dashboard-section {{ margin-bottom: 2rem; }}
  .dashboard-section h2 {{ font-size: 1.2rem; color: var(--pink); padding-bottom: .7rem;
                           border-bottom: 2px solid rgba(233,30,140,.25); margin-bottom: .7rem; }}
  .subsection-title {{ color: #fff; font-size: .95rem; margin: 1rem 0 .65rem; }}
  .section-intro {{ color: var(--muted); font-size: .86rem; margin-bottom: 1rem; }}
  .action-card {{ background: var(--card); border: 1px solid rgba(255,255,255,.08);
                  border-radius: 8px; padding: 1rem; margin-bottom: .9rem; }}
  .action-card h3 {{ font-size: 1.05rem; color: #fff; margin: .35rem 0 .8rem; }}
  .action-head {{ display: flex; flex-wrap: wrap; gap: .4rem; }}
  .action-next {{ margin-top: .85rem; padding: .75rem; border-radius: 8px; background: rgba(255,255,255,.04); border: 1px solid rgba(255,255,255,.07); font-size: .84rem; }}
  .action-buttons {{ margin-top: .65rem; display: flex; flex-wrap: wrap; gap: .35rem; }}
  .pill {{ display: inline-block; border-radius: 999px; padding: .18rem .55rem;
           font-size: .7rem; font-weight: 750; text-transform: uppercase; letter-spacing: .03em; }}
  .pill-high {{ background: rgba(233,30,140,.2); color: var(--pink); border: 1px solid rgba(233,30,140,.4); }}
  .pill-medium {{ background: rgba(116,185,255,.15); color: var(--blue); border: 1px solid rgba(116,185,255,.35); }}
  .pill-low {{ background: rgba(255,255,255,.08); color: var(--muted); border: 1px solid rgba(255,255,255,.15); }}
  .pill-aov {{ background: rgba(0,184,148,.12); color: var(--green); border: 1px solid rgba(0,184,148,.3); }}
  .dia-grid {{ display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: .7rem; }}
  .dia-box, .info-panel, .team-input-card {{ background: rgba(255,255,255,.04); border: 1px solid rgba(255,255,255,.07);
                                              border-radius: 8px; padding: .85rem; }}
  .dia-box h4, .info-panel h3, .team-input-card h3 {{ color: #fff; font-size: .82rem; margin-bottom: .35rem; }}
  .dia-box p, .info-panel p, .team-input-card p {{ color: var(--text); font-size: .82rem; }}
  .info-grid {{ display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: .8rem; }}
  .plain-list {{ list-style: none; }}
  .plain-list li {{ border-bottom: 1px solid rgba(255,255,255,.05); padding: .35rem 0; font-size: .82rem; }}
  .plain-list li:last-child {{ border-bottom: 0; }}
  .report-btn {{ display: inline-flex; align-items: center; min-height: 36px; margin-top: .8rem;
                 padding: 0 .8rem; background: var(--pink); color: #fff; border-radius: 6px;
                 text-decoration: none; font-size: .8rem; font-weight: 700; }}
  .visibility-stats {{ display: grid; grid-template-columns: repeat(5, minmax(0, 1fr)); gap: .7rem; margin: .8rem 0 1rem; }}
  .visibility-stats div {{ background: rgba(255,255,255,.04); border: 1px solid rgba(255,255,255,.07); border-radius: 8px; padding: .75rem; }}
  .visibility-stats strong {{ display: block; color: #fff; font-size: 1.35rem; line-height: 1; }}
  .visibility-stats span {{ display: block; color: var(--muted); font-size: .72rem; margin-top: .25rem; }}
  .visibility-key {{ display: flex; gap: 1rem; flex-wrap: wrap; color: var(--muted); font-size: .78rem; margin-bottom: .8rem; }}
  .key-dot {{ display: inline-block; width: .65rem; height: .65rem; border-radius: 999px; margin-right: .3rem; }}
  .key-good {{ background: var(--green); }}
  .key-mid {{ background: var(--yellow); }}
  .key-bad {{ background: var(--red); }}
  .rank-pill {{ display: inline-flex; align-items: center; justify-content: center; min-width: 54px; border-radius: 999px; padding: .2rem .45rem; font-size: .72rem; font-weight: 800; }}
  .rank-good {{ background: rgba(0,184,148,.14); color: var(--green); border: 1px solid rgba(0,184,148,.35); }}
  .rank-mid {{ background: rgba(253,203,110,.15); color: var(--yellow); border: 1px solid rgba(253,203,110,.35); }}
  .rank-bad {{ background: rgba(214,48,49,.15); color: var(--red); border: 1px solid rgba(214,48,49,.35); }}
  .priority-pill {{ display: inline-flex; align-items: center; justify-content: center; min-width: 42px; border-radius: 999px; padding: .18rem .42rem; font-size: .72rem; font-weight: 800; background: rgba(233,30,140,.16); color: var(--pink); border: 1px solid rgba(233,30,140,.35); }}
  .metric-cell {{ text-align: center; white-space: nowrap; color: var(--text); }}
  .competitor-chip {{ display: inline-block; margin: .12rem .15rem .12rem 0; padding: .15rem .4rem; border-radius: 999px; background: rgba(255,255,255,.06); color: var(--muted); font-size: .68rem; }}
  .action-cell {{ min-width: 360px; font-size: .78rem; line-height: 1.45; }}
  .muted-small {{ color: var(--muted); font-size: .72rem; }}
  .mini-btn {{ display: inline-flex; align-items: center; justify-content: center; min-height: 30px; margin: .15rem .2rem .15rem 0; padding: 0 .55rem; border-radius: 6px; border: 1px solid rgba(233,30,140,.35); background: rgba(233,30,140,.14); color: #fff; font-size: .72rem; font-weight: 750; text-decoration: none; cursor: pointer; font-family: inherit; }}
  .mini-btn:hover {{ background: rgba(233,30,140,.28); }}
  .mini-btn:disabled, .muted-action {{ opacity: .55; cursor: not-allowed; border-color: rgba(255,255,255,.15); background: rgba(255,255,255,.06); }}
  .content-queue {{ display: grid; gap: .9rem; }}
  .content-queue-card {{ background: var(--card); border: 1px solid rgba(255,255,255,.08); border-radius: 8px; padding: 1rem; }}
  .content-queue-card h3 {{ color: #fff; font-size: 1rem; margin: .45rem 0 .35rem; }}
  .page-fix-list {{ display: grid; gap: .9rem; }}
  .page-fix-card {{ background: var(--card); border: 1px solid rgba(255,255,255,.08); border-radius: 8px; padding: 1rem; }}
  .page-fix-card h3 {{ font-size: .98rem; margin: .45rem 0 .75rem; }}
  .page-fix-card h3 a {{ color: var(--blue); }}
  .fix-grid {{ display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: .7rem; }}
  .fix-grid div, .fix-work {{ background: rgba(255,255,255,.04); border: 1px solid rgba(255,255,255,.07); border-radius: 8px; padding: .75rem; }}
  .fix-grid h4 {{ color: #fff; font-size: .8rem; margin-bottom: .25rem; }}
  .fix-grid p, .fix-work {{ color: var(--text); font-size: .82rem; }}
  .fix-work {{ margin-top: .65rem; }}

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
    .tabs {{ padding-left: 1rem; padding-right: 1rem; position: static; }}
    .dia-grid, .info-grid {{ grid-template-columns: 1fr; }}
    .fix-grid {{ grid-template-columns: 1fr; }}
    .visibility-stats {{ grid-template-columns: repeat(2, minmax(0, 1fr)); }}
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

<nav class="tabs" aria-label="Report sections">
  <button class="tab-btn active" data-tab="actions">Weekly Actions</button>
  <button class="tab-btn" data-tab="rank">Where We Rank</button>
  <button class="tab-btn" data-tab="trends">Trends</button>
  <button class="tab-btn" data-tab="bestsellers">Bestsellers</button>
  <button class="tab-btn" data-tab="content">Content Packs</button>
  <button class="tab-btn" data-tab="team">Team</button>
</nav>

<main>
  <section id="tab-actions" class="tab-panel active">
    {weekly_actions_section}
  </section>
  <section id="tab-rank" class="tab-panel">
    {visibility_section}
  </section>
  <section id="tab-trends" class="tab-panel">
    {trend_opportunities_section}
  </section>
  <section id="tab-bestsellers" class="tab-panel">
    {bestseller_section}
  </section>
  <section id="tab-content" class="tab-panel">
    {content_pack_section}
  </section>
  <section id="tab-team" class="tab-panel">
    {team_inputs_section}
  </section>
</main>

<footer>
  Rock On Ruby Trend Scraper · rockonruby.co.uk · Re-run: <code>python3 scraper.py</code>
  &nbsp;·&nbsp; Use cached data: <code>python3 scraper.py --cached</code>
</footer>
<script>
  document.querySelectorAll('.tab-btn').forEach((button) => {{
    button.addEventListener('click', () => {{
      const tab = button.dataset.tab;
      document.querySelectorAll('.tab-btn').forEach((btn) => btn.classList.remove('active'));
      document.querySelectorAll('.tab-panel').forEach((panel) => panel.classList.remove('active'));
      button.classList.add('active');
      document.getElementById(`tab-${{tab}}`).classList.add('active');
    }});
  }});
  document.querySelectorAll('.copy-brief').forEach((button) => {{
    button.addEventListener('click', async () => {{
      const brief = button.dataset.brief || '';
      try {{
        await navigator.clipboard.writeText(brief);
        const original = button.textContent;
        button.textContent = 'Copied';
        setTimeout(() => button.textContent = original, 1400);
      }} catch (e) {{
        window.prompt('Copy this brief', brief);
      }}
    }});
  }});
</script>
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

    seo_section            = build_seo_section(all_groups)
    breakout_section       = build_breakout_section(all_groups)
    gaps_section           = build_gaps_section(all_groups)
    bestseller_section     = build_bestseller_demand_section(all_groups)
    weekly_actions_section = build_weekly_actions_section(all_groups)
    visibility_section     = build_visibility_rank_section()
    trend_opportunities_section = build_trend_opportunities_section(all_groups)
    team_inputs_section    = build_team_inputs_section()
    content_pack_section   = build_content_pack_section(all_groups)
    seo_css_clean          = SEO_CSS.strip()
    trending_css_clean     = TRENDING_CSS.strip()

    date_str = datetime.now().strftime("%d %B %Y, %H:%M")
    html = HTML_TEMPLATE.format(
        date=date_str, total=total, hot=hot, rising=rising,
        gaps=gaps, live=live, paa_count=paa_count,
        notice=notice, groups_html=groups_html,
        seo_section=seo_section, seo_css=seo_css_clean,
        breakout_section=breakout_section,
        gaps_section=gaps_section,
        bestseller_section=bestseller_section,
        weekly_actions_section=weekly_actions_section,
        visibility_section=visibility_section,
        trend_opportunities_section=trend_opportunities_section,
        team_inputs_section=team_inputs_section,
        content_pack_section=content_pack_section,
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
