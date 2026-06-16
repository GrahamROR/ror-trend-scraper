"""
Rock On Ruby — Content Series Generator
Finds 7 recurring content series ideas for ROR's social media, with real
example URLs sourced fresh each week via Perplexity. Pushes to ClickUp as
a parent task with 7 subtasks (one per series idea).

Anti-repetition: tracks used series concepts and example URLs in
content_history.json so each week produces genuinely new ideas.

Required env vars:
  PERPLEXITY_API_KEY
  ANTHROPIC_API_KEY
  CLICKUP_API_KEY
  CLICKUP_LIST_ID  — Generated Content Inbox
"""

import os
import json
import re
import requests
from datetime import datetime, timedelta, timezone
from pathlib import Path

PERPLEXITY_KEY  = os.environ.get("PERPLEXITY_API_KEY", "")
ANTHROPIC_KEY   = os.environ.get("ANTHROPIC_API_KEY", "")
CLICKUP_KEY     = os.environ.get("CLICKUP_API_KEY", "")
INBOX_LIST_ID   = os.environ.get("CLICKUP_LIST_ID", "901217534962")

CLICKUP_BASE    = "https://api.clickup.com/api/v2"
CLICKUP_HEADERS = {"Authorization": CLICKUP_KEY, "Content-Type": "application/json"}

OUTPUT_DIR      = Path(__file__).parent
HISTORY_FILE    = OUTPUT_DIR / "content_history.json"

# ── ROR brand brief (static) ──────────────────────────────────────────────────

ROR_BRIEF = """
BRAND: Rock On Ruby (rockonruby.co.uk)
WHAT WE SELL: Personalised print-on-demand clothing and accessories made to order.
Products include: sweatshirts, hoodies, t-shirts, caps, tote bags, make-up bags,
and slogan clothing. Production methods: DTF full-colour print and embroidery.
Based in Bury, Manchester.

WHO WE SELL TO: UK women aged 30-50. Thoughtful gift-buyers. Busy, warm, funny,
slightly chaotic. Buying for birthdays, milestone ages (30/40/50/60), Mother's Day,
Father's Day, Christmas. Sometimes buying for themselves.

BRAND VOICE: Chatty, irreverent, UK humour, no corporate language, no influencer
tone. Like Holly is texting her sister. Self-deprecating, warm, never salesy.

ADJACENT NICHES:
1. UK lifestyle/mum content creators — relatable chaos, school run, juggling life
2. High street gifting (M&S, Not On The High Street, Moonpig) — gift inspiration
3. UK small business / maker content — behind the scenes, production, team
4. UK fashion/outfit content — what I wore, capsule wardrobe, getting dressed
5. Experiential gifting — meaningful over generic, anti-Amazon, personal touches

CONTENT TEAM: Holly (on-camera, brand face), Bethan (design/social), small team.
Scrappy production. Phone camera is fine. Authentic over polished.
""".strip()


# ── History helpers ───────────────────────────────────────────────────────────

def load_history() -> dict:
    if HISTORY_FILE.exists():
        try:
            return json.loads(HISTORY_FILE.read_text())
        except Exception:
            pass
    return {}


def save_history(history: dict) -> None:
    HISTORY_FILE.write_text(json.dumps(history, indent=2))


def get_used_series(history: dict, weeks: int = 12) -> list[str]:
    """Return series concepts used in the last N weeks."""
    cutoff = (datetime.now() - timedelta(weeks=weeks)).strftime("%Y-%m-%d")
    return [
        e["concept"]
        for e in history.get("series", [])
        if e.get("date", "") >= cutoff
    ]


def get_used_urls(history: dict, weeks: int = 8) -> list[str]:
    """Return example URLs used in the last N weeks."""
    cutoff = (datetime.now() - timedelta(weeks=weeks)).strftime("%Y-%m-%d")
    urls = []
    for e in history.get("series", []):
        if e.get("date", "") >= cutoff:
            urls.extend(e.get("urls", []))
    return urls


def record_series_run(history: dict, series_list: list[dict]) -> None:
    today = datetime.now().strftime("%Y-%m-%d")
    for s in series_list:
        urls = [ex.get("url", "") for ex in s.get("examples", []) if ex.get("url")]
        history.setdefault("series", []).append({
            "date": today,
            "concept": s.get("concept", ""),
            "name": s.get("name", ""),
            "urls": urls,
        })
    # Prune to last 6 months
    cutoff = (datetime.now() - timedelta(weeks=26)).strftime("%Y-%m-%d")
    history["series"] = [
        e for e in history.get("series", [])
        if e.get("date", "") >= cutoff
    ]


# ── Perplexity search ─────────────────────────────────────────────────────────

def perplexity_search(query: str) -> str:
    """
    Send a search query to Perplexity sonar and return the response text.
    Perplexity sonar has live web access and returns sourced content.
    """
    headers = {
        "Authorization": f"Bearer {PERPLEXITY_KEY}",
        "Content-Type": "application/json",
    }
    payload = {
        "model": "sonar",
        "messages": [
            {
                "role": "system",
                "content": (
                    "You are a social media research assistant. "
                    "When asked to find content, always return direct URLs to specific posts, "
                    "reels, TikToks or YouTube Shorts — never profile pages or homepages. "
                    "Include approximate view counts or engagement stats where available. "
                    "Only return content from the last 6 months."
                ),
            },
            {"role": "user", "content": query},
        ],
        "search_recency_filter": "month",
        "return_citations": True,
    }
    try:
        resp = requests.post(
            "https://api.perplexity.ai/chat/completions",
            headers=headers,
            json=payload,
            timeout=30,
        )
        if resp.ok:
            return resp.json()["choices"][0]["message"]["content"]
        print(f"  Perplexity error {resp.status_code}: {resp.text[:120]}")
    except Exception as e:
        print(f"  Perplexity request failed: {e}")
    return ""


# ── Claude call ───────────────────────────────────────────────────────────────

def claude_call(system: str, prompt: str, max_tokens: int = 4000) -> str:
    import anthropic
    client = anthropic.Anthropic(api_key=ANTHROPIC_KEY)
    msg = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=max_tokens,
        system=system,
        messages=[{"role": "user", "content": prompt}],
    )
    return msg.content[0].text.strip()


# ── Step 1: Generate 7 series concepts ───────────────────────────────────────

def generate_series_concepts(used_concepts: list[str]) -> list[dict]:
    """
    Ask Claude to generate 7 distinct content series concepts for ROR,
    avoiding anything used recently.
    """
    used_str = "\n".join(f"  - {c}" for c in used_concepts) if used_concepts else "  None yet"

    prompt = f"""
{ROR_BRIEF}

Generate exactly 7 recurring content series ideas that Rock On Ruby could film
this week with a phone camera and a small team.

RULES:
- Each must be a RECURRING FORMAT (weekly or fortnightly), not a one-off idea
- Inspired by what's working in adjacent niches (UK lifestyle, gifting, small biz, fashion, experiential)
- Executable by Holly on camera with Bethan helping — scrappy, authentic, not over-produced
- Must connect naturally to ROR's products, brand story, or customer's life
- Vary the formats: mix behind-the-scenes, customer-led, educational, trend-response, storytelling

DO NOT suggest series similar to these recently used concepts:
{used_str}

For each series return EXACTLY this structure (no other text):

SERIES_NAME: [punchy, brandable series title]
CONCEPT: [one sentence — what the recurring format is]
NICHE_INSPIRATION: [which adjacent niche this is inspired by]
WHY_IT_WORKS: [one sentence — why this format hooks audiences]
HOW_TO_SHOOT: [2-3 sentences — specifically how ROR would film this, who's in it, where]
EPISODE_ONE: [one specific, filmable idea for the very first episode]
DIFFICULTY: [Easy / Medium / Hard]

---

(repeat for all 7)
""".strip()

    raw = claude_call(
        "You are a social media strategist for ecommerce brands. Return only the structured output requested.",
        prompt,
        max_tokens=3000,
    )

    series = []
    for block in re.split(r"\n---\n", raw):
        block = block.strip()
        if "SERIES_NAME:" not in block:
            continue

        def extract(key: str) -> str:
            m = re.search(rf"^{key}:\s*(.+)$", block, re.MULTILINE)
            return m.group(1).strip() if m else ""

        series.append({
            "name":         extract("SERIES_NAME"),
            "concept":      extract("CONCEPT"),
            "niche":        extract("NICHE_INSPIRATION"),
            "why":          extract("WHY_IT_WORKS"),
            "how":          extract("HOW_TO_SHOOT"),
            "episode_one":  extract("EPISODE_ONE"),
            "difficulty":   extract("DIFFICULTY"),
            "examples":     [],
        })

    return series[:7]


# ── Step 2: Find real examples via Perplexity ─────────────────────────────────

def find_examples_for_series(series: dict, used_urls: list[str]) -> list[dict]:
    """
    Use Perplexity to find 5 real, recent example posts of creators
    executing a similar series format. Avoids previously used URLs.
    """
    avoid_str = ""
    if used_urls:
        sample = used_urls[-20:]  # last 20 used URLs
        avoid_str = "\n\nDo NOT return any of these URLs:\n" + "\n".join(f"  - {u}" for u in sample)

    query = f"""
Find 5 specific TikTok videos, Instagram Reels, or YouTube Shorts from the last 6 months
where creators or small brands are doing something similar to this content format:

Format: {series['name']}
Description: {series['concept']}
Adjacent niche: {series['niche']}

I need:
- Direct links to specific posts (not profile pages)
- Creator or brand name
- Platform (TikTok / Instagram / YouTube)
- One line describing what the specific post is about
- Approximate view count or engagement if you can find it

Focus on UK creators or small ecommerce brands where possible.
Prioritise TikTok and YouTube links as they're more reliable than Instagram.
{avoid_str}
""".strip()

    print(f"    Searching examples: {series['name']}")
    raw = perplexity_search(query)

    if not raw:
        return []

    # Ask Claude to parse Perplexity's response into structured examples
    parse_prompt = f"""
Parse this Perplexity search result and extract up to 5 content examples.

For each example return EXACTLY this format:
CREATOR: [creator or brand name]
PLATFORM: [TikTok / Instagram / YouTube]
DESCRIPTION: [one line — what this specific post is about]
URL: [direct link to the post]
STATS: [views/likes if mentioned, or "not available"]

Return only the structured output. If fewer than 5 examples are clearly present, return what's there.

SEARCH RESULT:
{raw}
"""
    parsed = claude_call(
        "You are a precise data parser. Extract only what is explicitly present in the source text. Never invent URLs.",
        parse_prompt,
        max_tokens=1000,
    )

    examples = []
    for block in re.split(r"\n(?=CREATOR:)", parsed.strip()):
        block = block.strip()
        if "CREATOR:" not in block:
            continue

        def extract(key: str) -> str:
            m = re.search(rf"^{key}:\s*(.+)$", block, re.MULTILINE)
            return m.group(1).strip() if m else ""

        url = extract("URL")
        if not url or url in used_urls:
            continue

        examples.append({
            "creator":     extract("CREATOR"),
            "platform":    extract("PLATFORM"),
            "description": extract("DESCRIPTION"),
            "url":         url,
            "stats":       extract("STATS"),
        })

    return examples[:5]


# ── Step 3: Push to ClickUp ───────────────────────────────────────────────────

def build_subtask_description(s: dict) -> str:
    """Build the ClickUp task description for one series idea."""
    lines = [
        f"SERIES: {s['name']}",
        f"NICHE INSPIRATION: {s['niche']}",
        f"DIFFICULTY: {s['difficulty']}",
        "",
        "WHY IT WORKS:",
        s["why"],
        "",
        "HOW TO SHOOT IT:",
        s["how"],
        "",
        "EPISODE ONE — FILM THIS FIRST:",
        s["episode_one"],
        "",
        "─" * 40,
        "EXAMPLE CONTENT FROM OTHER CREATORS:",
        "",
    ]

    if s["examples"]:
        for i, ex in enumerate(s["examples"], 1):
            lines.append(f"{i}. {ex['creator']} ({ex['platform']})")
            lines.append(f"   {ex['description']}")
            lines.append(f"   {ex['url']}")
            if ex["stats"] and ex["stats"].lower() != "not available":
                lines.append(f"   Stats: {ex['stats']}")
            lines.append("")
    else:
        lines.append("No verified examples found this week.")
        lines.append("")

    return "\n".join(lines).strip()


def push_to_clickup(series_list: list[dict], due_ms: int) -> bool:
    today = datetime.now().strftime("%d %b %Y")
    week_num = datetime.now().strftime("%W")
    parent_name = f"[Content Series] 7 Series Ideas — w/c {today}"

    verified_count = sum(
        1 for s in series_list
        for ex in s.get("examples", [])
        if ex.get("url", "").startswith("http")
    )
    total_examples = sum(len(s.get("examples", [])) for s in series_list)

    parent_description = (
        f"Weekly content series ideas for Rock On Ruby social media.\n"
        f"Generated: {today}\n"
        f"Examples verified: {verified_count}/{total_examples}\n\n"
        f"7 subtasks below — one per series concept.\n"
        f"Each subtask contains the format brief, how to shoot it, episode 1 idea, "
        f"and real example URLs from other creators."
    )

    # Create parent task
    payload = {
        "name": parent_name,
        "description": parent_description,
        "due_date": due_ms,
        "due_date_time": True,
        "status": "generated",
        "tags": ["content-series", "social"],
    }

    try:
        resp = requests.post(
            f"{CLICKUP_BASE}/list/{INBOX_LIST_ID}/task",
            headers=CLICKUP_HEADERS,
            json=payload,
            timeout=15,
        )
        if not resp.ok:
            print(f"  x Parent task failed: {resp.status_code}: {resp.text[:120]}")
            return False

        parent_id = resp.json()["id"]
        parent_url = resp.json().get("url", "")
        print(f"  + Parent: {parent_name}")
        print(f"    {parent_url}")

    except Exception as e:
        print(f"  x Parent task error: {e}")
        return False

    # Create subtasks
    for i, s in enumerate(series_list, 1):
        difficulty_priority = {"Easy": 4, "Medium": 3, "Hard": 2}.get(s["difficulty"], 3)
        subtask_payload = {
            "name": f"{i}. {s['name']} [{s['difficulty']}]",
            "description": build_subtask_description(s),
            "due_date": due_ms,
            "due_date_time": True,
            "priority": difficulty_priority,
            "tags": ["content-series", s["niche"].lower().replace(" ", "-")[:20]],
        }
        try:
            sub_resp = requests.post(
                f"{CLICKUP_BASE}/task/{parent_id}/subtask",
                headers=CLICKUP_HEADERS,
                json=subtask_payload,
                timeout=15,
            )
            if sub_resp.ok:
                print(f"    - Subtask {i}: {s['name']}")
            else:
                print(f"    x Subtask {i} failed: {sub_resp.status_code}")
        except Exception as e:
            print(f"    x Subtask {i} error: {e}")

    return True


# ── Main entry point ──────────────────────────────────────────────────────────

def run_series_generator(due_ms: int, history: dict) -> bool:
    """
    Main function called from content_generator.py.
    Returns True on success.
    """
    print("\n  -- Content Series Generator --")

    if not PERPLEXITY_KEY:
        print("  PERPLEXITY_API_KEY not set — skipping series generator.")
        return False

    used_concepts = get_used_series(history, weeks=12)
    used_urls = get_used_urls(history, weeks=8)

    print(f"  Used concepts (last 12 weeks): {len(used_concepts)}")
    print(f"  Used URLs (last 8 weeks): {len(used_urls)}")

    # Step 1: Generate 7 series concepts
    print("\n  Generating series concepts...")
    series_list = generate_series_concepts(used_concepts)

    if not series_list:
        print("  No series concepts generated.")
        return False

    print(f"  Generated {len(series_list)} concepts")

    # Step 2: Find real examples for each via Perplexity
    print("\n  Finding real examples via Perplexity...")
    for s in series_list:
        s["examples"] = find_examples_for_series(s, used_urls)
        # Add newly found URLs to used list to avoid duplicates within this run
        for ex in s["examples"]:
            if ex.get("url"):
                used_urls.append(ex["url"])
        print(f"    {s['name']}: {len(s['examples'])} examples found")

    # Step 3: Push to ClickUp
    print("\n  Pushing to ClickUp...")
    ok = push_to_clickup(series_list, due_ms)

    if ok:
        record_series_run(history, series_list)
        verified = sum(1 for s in series_list for ex in s.get("examples", []) if ex.get("url", "").startswith("http"))
        total = sum(len(s.get("examples", [])) for s in series_list)
        print(f"\n  Series generator done. Examples: {verified}/{total} with URLs")

    return ok
