"""
Rock On Ruby — Trend Scraper
Data sources:
  - Google Trends via SerpAPI (interest over time + rising queries) — no rate limiting
  - People Also Ask via SerpAPI (real questions = content/social gold)
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
from serpapi import GoogleSearch

# ── Config ───────────────────────────────────────────────────────────────────

SERPAPI_KEY      = os.environ.get("SERPAPI_KEY", "")
OUTPUT_DIR       = Path(__file__).parent
REPORT_FILE      = OUTPUT_DIR / "trend_report.html"
CACHE_FILE       = OUTPUT_DIR / "trend_cache.json"
FOCUS_FILE       = OUTPUT_DIR / "ror_focus.json"
LAYER4_CACHE     = OUTPUT_DIR / "layer4_expanded.json"

GEO      = "GB"
TIMEFRAME = "today 3-m"


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

# ── ROR existing catalogue ────────────────────────────────────────────────────

ROR_EXISTING = [
    "personalised caps", "embroidered caps", "custom caps",
    "personalised sweatshirts", "personalised hoodies",
    "slogan sweatshirts", "slogan hoodies", "slogan tees",
    "personalised tote bags", "embroidered tote bags",
    "personalised gifts", "funny gifts for women",
    "personalised gifts for mum", "personalised gifts for dad",
    "father's day gifts", "mothers day gifts",
    "bourbon biscuit", "custard cream", "jammy dodger", "party rings",
    "biscuit gifts", "biscuit themed clothing",
    "only here for the", "only here for the biscuits",
    "tea please", "coffee please",
    "bbq gifts", "condiment gifts",
    "leopard print clothing", "leopard print sweatshirt",
    "festival clothing", "festival outfit",
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
    term_lower = term.lower()
    for existing in ROR_EXISTING:
        words = [w for w in term_lower.split() if len(w) > 3]
        if words and any(w in existing for w in words):
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


# ── SerpAPI calls ─────────────────────────────────────────────────────────────

def _trends_query(q: str) -> dict:
    """Single SerpAPI Trends TIMESERIES call. Returns parsed dict or {}."""
    params = {
        "engine":    "google_trends",
        "q":         q,
        "geo":       GEO,
        "date":      TIMEFRAME,
        "data_type": "TIMESERIES",
        "api_key":   SERPAPI_KEY,
    }
    data     = GoogleSearch(params).get_dict()
    if "error" in data:
        return {}
    timeline = data.get("interest_over_time", {}).get("timeline_data", [])
    if not timeline:
        return {}
    values = []
    for point in timeline:
        vals = point.get("values", [])
        if vals:
            try:
                values.append(int(vals[0].get("extracted_value", 0)))
            except (ValueError, TypeError):
                pass
    if not values or max(values) == 0:
        return {}
    avg  = int(sum(values) / len(values))
    peak = max(values)
    half = max(1, len(values) // 2)
    fh   = sum(values[:half]) / half
    sh   = sum(values[half:]) / max(1, len(values) - half)
    trend = "rising" if sh > fh * 1.15 else ("falling" if sh < fh * 0.85 else "stable")
    return {"avg": avg, "peak": peak, "trend": trend}


def serpapi_trends_timeseries(term: str) -> dict:
    """
    Fetch interest-over-time for a term (standalone 0-100 scale).
    Falls back to stripping trailing ' uk' if the first call returns no data
    (geo=GB is already set, so 'uk' in the query string is often redundant).
    Returns {"avg": int, "peak": int, "trend": str} or {}.
    """
    try:
        result = _trends_query(term)
        if result:
            return result
        # Fallback: try without trailing " uk" or " uk 2026" suffix
        cleaned = term
        for suffix in (" uk 2026", " uk"):
            if cleaned.lower().endswith(suffix):
                cleaned = cleaned[: -len(suffix)].strip()
                break
        if cleaned != term:
            time.sleep(random.uniform(0.8, 1.4))
            result = _trends_query(cleaned)
            if result:
                return result
        return {}
    except Exception as e:
        print(f"    Trends error for '{term}': {e}")
        return {}


def serpapi_related_queries(term: str) -> dict[str, list[str]]:
    """
    Fetch rising + top + breakout related queries for a single term.
    Returns {"rising": [...], "top": [...], "breakout": [...]}.
    Breakout = search interest suddenly spiking (Google marks value as "Breakout").
    """
    params = {
        "engine":    "google_trends",
        "q":         term,
        "geo":       GEO,
        "date":      TIMEFRAME,
        "data_type": "RELATED_QUERIES",
        "api_key":   SERPAPI_KEY,
    }
    out = {"rising": [], "top": [], "breakout": []}
    try:
        data = GoogleSearch(params).get_dict()
        rq   = data.get("related_queries", {})
        for kind in ("rising", "top"):
            items = rq.get(kind, [])
            if isinstance(items, list):
                for i in items[:6]:
                    if "query" not in i:
                        continue
                    # Breakout = value is literally "Breakout" or extracted_value >= 5000
                    is_breakout = (
                        str(i.get("value", "")).lower() == "breakout"
                        or int(i.get("extracted_value", 0)) >= 5000
                    )
                    if is_breakout:
                        out["breakout"].append(i["query"])
                    elif kind == "rising":
                        out["rising"].append(i["query"])
                    else:
                        out["top"].append(i["query"])
    except Exception as e:
        print(f"    Related queries error for '{term}': {e}")
    return out


def serpapi_people_also_ask(term: str) -> list[str]:
    """Fetch People Also Ask questions for a term via Google Search."""
    params = {
        "engine":  "google",
        "q":       term,
        "gl":      "uk",
        "hl":      "en",
        "num":     10,
        "api_key": SERPAPI_KEY,
    }
    questions = []
    try:
        data = GoogleSearch(params).get_dict()
        paa  = data.get("related_questions", [])
        questions = [item["question"] for item in paa[:5] if "question" in item]
    except Exception as e:
        print(f"    PAA error for '{term}': {e}")
    return questions


# ── Fetch all data ────────────────────────────────────────────────────────────

def fetch_all(cached: bool = False) -> list[dict]:
    """
    Fetch or load all data. Returns list of group dicts ready for report.
    """
    if cached and CACHE_FILE.exists():
        print("  Loading from cache...")
        raw = json.loads(CACHE_FILE.read_text())
        return raw

    all_groups = []
    total_groups = len(TERM_GROUPS)

    for g_idx, group in enumerate(TERM_GROUPS):
        label     = group["label"]
        term_list = [(t[0], t[1], t[2]) for t in group["terms"]]
        terms     = [t[0] for t in term_list]

        print(f"\n[{g_idx+1}/{total_groups}] {label}")

        # ── 1. Trends timeseries (1 call per term — standalone 0-100 score) ──
        ts_data = {}
        for term in terms:
            print(f"  → Trends: {term}")
            ts_data[term] = serpapi_trends_timeseries(term)
            time.sleep(random.uniform(1.2, 2.0))

        # ── 2. Related queries for each term in group (includes breakout detection) ──
        related_data = {}
        for term in terms:
            print(f"  → Related queries: {term}")
            related_data[term] = serpapi_related_queries(term)
            if related_data[term].get("breakout"):
                print(f"    🚨 BREAKOUT detected in related: {related_data[term]['breakout']}")
            time.sleep(random.uniform(1.2, 2.0))

        # ── 3. PAA — only for terms scoring 6+ (keeps API usage lean) ──
        paa_data = {}
        for term, seed_avg, seed_trend in term_list:
            live      = ts_data.get(term, {})
            avg       = live.get("avg", seed_avg)
            trend     = live.get("trend", seed_trend)
            rough_score = score_term(avg, trend, term)
            if rough_score >= 6:
                print(f"  → People Also Ask: {term}")
                paa_data[term] = serpapi_people_also_ask(term)
                time.sleep(random.uniform(1.2, 2.0))

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
            pause = random.uniform(2.0, 3.5)
            print(f"  Pausing {pause:.1f}s...")
            time.sleep(pause)

    # Cache results
    CACHE_FILE.write_text(json.dumps(all_groups, indent=2))
    print(f"\nCached to: {CACHE_FILE}")
    return all_groups


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

# Maps term to a suggested ROR page/product URL slug
def seo_page_map(term: str, existing: str) -> str:
    mapping = {
        "fathers day":        "/collections/fathers-day-gifts",
        "festival":           "/collections/festival-clothing",
        "glastonbury":        "/collections/festival-clothing",
        "reading festival":   "/collections/festival-clothing",
        "beach holiday":      "/collections/personalised-tote-bags",
        "summer":             "/collections/personalised-gifts",
        "biscuit":            "/collections/biscuit-range",
        "bourbon":            "/collections/biscuit-range",
        "jammy dodger":       "/collections/biscuit-range",
        "custard cream":      "/collections/biscuit-range",
        "personalised gifts": "/collections/personalised-gifts",
        "personalised cap":   "/collections/personalised-caps",
        "embroidered cap":    "/collections/embroidered-caps",
        "sweatshirt":         "/collections/personalised-sweatshirts",
        "hoodie":             "/collections/personalised-hoodies",
        "tote":               "/collections/personalised-tote-bags",
        "bbq":                "/collections/fathers-day-gifts",
        "leopard":            "/collections/sweatshirts",
        "funny gifts":        "/collections/funny-gifts",
    }
    t = term.lower()
    for key, slug in mapping.items():
        if key in t:
            return f"rockonruby.co.uk{slug}"
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

        rows += f"""
<tr>
  <td class="kw-cell">{r['term']} <span class="src-dot">{src}</span></td>
  <td style="color:{trend_col};font-weight:600">{trend_icon} {r['trend'].capitalize()}</td>
  <td style="color:{score_col};font-weight:700;text-align:center">{r['score']}/10</td>
  <td class="page-cell">{page}</td>
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
  .act-low    { background: rgba(255,255,255,.05); color: var(--muted);
                border: 1px solid rgba(255,255,255,.1); }
"""


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
  <p>Generated {date} · Google Trends + SerpAPI · UK · 90-day window</p>
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

<main>
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

    ror_html = (
        f'<span class="ror-tag ror-has">✓ ROR sells: {r["ror_existing"]}</span>'
        if r["ror_existing"]
        else '<span class="ror-tag ror-gap">⚡ Product gap — not on rockonruby.co.uk yet</span>'
    )

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


def build_report(all_groups: list[dict]) -> None:
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

    seo_section      = build_seo_section(all_groups)
    breakout_section = build_breakout_section(all_groups)
    seo_css_clean    = SEO_CSS.strip()

    date_str = datetime.now().strftime("%d %B %Y, %H:%M")
    html = HTML_TEMPLATE.format(
        date=date_str, total=total, hot=hot, rising=rising,
        gaps=gaps, live=live, paa_count=paa_count,
        notice=notice, groups_html=groups_html,
        seo_section=seo_section, seo_css=seo_css_clean,
        breakout_section=breakout_section,
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
        print(f"Rock On Ruby — Trend Scraper (live · SerpAPI)")
        print(f"Groups: {len(TERM_GROUPS)}  ·  Terms: {total_terms}")
        print(f"Estimated API calls: ~{total_terms * 2 + 15} (Trends per term + Related + PAA)\n")

    all_groups = fetch_all(cached=cached)
    build_report(all_groups)

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
