"""
Rock On Ruby — Carousel Brief Generator
Generates Instagram carousel briefs aligned to blog topics.
Grounded in the ROR brand style guide. Pushes as [Carousel] tasks to ClickUp.
"""

import os
import re
import requests
from datetime import datetime
from pathlib import Path

import anthropic as anthropic_lib

ANTHROPIC_KEY   = os.environ.get("ANTHROPIC_API_KEY", "")
CLICKUP_KEY     = os.environ.get("CLICKUP_API_KEY", "")
INBOX_LIST_ID   = os.environ.get("CLICKUP_LIST_ID", "901217534962")
CLICKUP_BASE    = "https://api.clickup.com/api/v2"
CLICKUP_HEADERS = {"Authorization": CLICKUP_KEY, "Content-Type": "application/json"}

CAROUSEL_STYLE_GUIDE = """
ROCK ON RUBY — CAROUSEL STYLE GUIDE

COLOUR PALETTES (pick ONE per carousel):
  BRAND_RED:    Brand red + hot pink + cream/off-white (sales, summer, general brand)
  NEUTRAL_CREAM: Cream/off-white background (gift guides, quote-style posts)
  FATHERS_DAY:  Navy + dusty periwinkle blue (men's gifting)
  NATURE:       Forest/dark green + cream (wellness, outdoors)
  ENERGY:       Lime/yellow-green + white (competitions, high energy)
  COFFEE_CREAM: Warm cream + deep brown + hot pink (coffee content, cosy)

SIX CAROUSEL TEMPLATES:
  1. BOLD_STATEMENT — solid colour bg, one punchy line per slide, builds a story, ends on payoff. 8-9 slides.
  2. GIFT_GUIDE — moodboard product collage with hand-drawn arrows, circles, script labels. 6-8 slides.
  3. TREND_JACK — styled product photo with bold diagonal text overlay referencing a cultural moment. 4-6 slides.
  4. MONTHLY_PREVIEW — mocked-up calendar with product photos pinned to key dates. 5-7 slides.
  5. UGC_COMMUNITY — customer/team photos with bold speech-bubble captions. 4-6 slides.
  6. QUIZ_POLL — interactive engagement format, multiple choice, swipe-to-reveal. 5-7 slides.

CAPTION FORMULA:
  Hook → Build (list/story/timeline) → Punchline or product reveal → Soft CTA → Team ROR x → 2-4 hashtags

VOICE: Conversational. Funny. Self-deprecating British millennial humour. First person plural.
Never salesy. Never corporate. UK spelling. Max one exclamation mark.
""".strip()

CAROUSEL_SYSTEM = f"""
{CAROUSEL_STYLE_GUIDE}

You are writing a carousel brief for Bethan, Rock On Ruby's designer.
She builds this in Canva. Give her everything she needs — nothing more, nothing less.
Be specific. Be creative. Make it feel like ROR.
"""


def claude_call(system: str, prompt: str, max_tokens: int = 2500) -> str:
    client = anthropic_lib.Anthropic(api_key=ANTHROPIC_KEY)
    msg = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=max_tokens,
        system=system,
        messages=[{"role": "user", "content": prompt}],
    )
    return msg.content[0].text.strip()


def generate_carousel_brief(topic: dict, catalogue_summary: str, seasonal: list[dict]) -> dict:
    seasonal_str = ", ".join(d["name"] for d in seasonal[:5]) if seasonal else "general"

    prompt = f"""
Write a complete Instagram carousel brief for Rock On Ruby based on this blog topic.

BLOG TITLE: {topic['title']}
KEYWORD: {topic['keyword']}
SEASONAL HOOK: {topic['hook']}
FEATURED PRODUCTS: {topic['products']}
PRODUCT URL: {topic['url']}
STORY ANGLE: {topic['angle']}
UPCOMING DATES: {seasonal_str}

{catalogue_summary}

Choose the best template and colour palette from your style guide.
Write every slide. Write the full caption.

Return EXACTLY this format:

CAROUSEL_TITLE: [internal title]
TEMPLATE: [template name]
PALETTE: [palette name]
SLIDE_COUNT: [number]
FEATURED_PRODUCT: [product name and URL]

SLIDES:
SLIDE 1 — [type e.g. COVER/HOOK/STORY/PRODUCT/CTA]
HEADLINE: [ALL CAPS, short, punchy]
SUBTEXT: [conversational supporting text, optional]
VISUAL NOTE: [one line for Bethan on what image/graphic to use]

SLIDE 2 — [type]
HEADLINE: [text]
SUBTEXT: [text]
VISUAL NOTE: [note]

(continue for all slides)

CAPTION:
[full Instagram caption]

HASHTAGS:
[2-4 hashtags]

CANVA_NOTES:
[2-3 practical notes for Bethan — Magic Layers usage, font suggestions, layout tips]
""".strip()

    raw = claude_call(CAROUSEL_SYSTEM, prompt)

    def extract(key: str) -> str:
        m = re.search(rf"^{key}:\s*(.+)$", raw, re.MULTILINE)
        return m.group(1).strip() if m else ""

    slides_match   = re.search(r"^SLIDES:\n(.*?)(?=^CAPTION:)", raw, re.MULTILINE | re.DOTALL)
    caption_match  = re.search(r"^CAPTION:\n(.*?)(?=^HASHTAGS:)", raw, re.MULTILINE | re.DOTALL)
    hashtags_match = re.search(r"^HASHTAGS:\n(.*?)(?=^CANVA_NOTES:)", raw, re.MULTILINE | re.DOTALL)
    canva_match    = re.search(r"^CANVA_NOTES:\n(.*)$", raw, re.MULTILINE | re.DOTALL)

    title = extract("CAROUSEL_TITLE") or topic.get("title", "Carousel")

    return {
        "title":            title,
        "template":         extract("TEMPLATE"),
        "palette":          extract("PALETTE"),
        "slide_count":      extract("SLIDE_COUNT"),
        "featured_product": extract("FEATURED_PRODUCT"),
        "slides_raw":       slides_match.group(1).strip() if slides_match else raw,
        "caption":          caption_match.group(1).strip() if caption_match else "",
        "hashtags":         hashtags_match.group(1).strip() if hashtags_match else "",
        "canva_notes":      canva_match.group(1).strip() if canva_match else "",
        "blog_title":       topic["title"],
        "seasonal_hook":    topic["hook"],
    }


def build_task_description(brief: dict) -> str:
    return "\n".join([
        f"ALIGNED WITH BLOG: {brief['blog_title']}",
        f"SEASONAL HOOK: {brief['seasonal_hook']}",
        f"TEMPLATE: {brief['template']}",
        f"COLOUR PALETTE: {brief['palette']}",
        f"SLIDE COUNT: {brief['slide_count']}",
        f"FEATURED PRODUCT: {brief['featured_product']}",
        "",
        "─" * 40,
        "SLIDES",
        "─" * 40,
        "",
        brief["slides_raw"],
        "",
        "─" * 40,
        "CAPTION",
        "─" * 40,
        "",
        brief["caption"],
        "",
        brief["hashtags"],
        "",
        "─" * 40,
        "CANVA NOTES FOR BETHAN",
        "─" * 40,
        "",
        brief["canva_notes"],
    ])


def push_carousel_task(brief: dict, due_ms: int) -> bool:
    today = datetime.now().strftime("%d %b")
    task_name = f"[Carousel] {brief['title']} — {today}"

    payload = {
        "name":         task_name,
        "description":  build_task_description(brief),
        "due_date":     due_ms,
        "due_date_time": True,
        "status":       "generated",
        "tags":         ["carousel", "social"],
    }

    try:
        resp = requests.post(
            f"{CLICKUP_BASE}/list/{INBOX_LIST_ID}/task",
            headers=CLICKUP_HEADERS,
            json=payload,
            timeout=15,
        )
        if resp.ok:
            print(f"  + {task_name}")
            print(f"    {resp.json().get('url', '')}")
            return True
        print(f"  x Failed: {task_name} — {resp.status_code}: {resp.text[:100]}")
    except Exception as e:
        print(f"  x Error: {task_name} — {e}")
    return False


def run_carousel_generator(
    topics: list[dict],
    catalogue_summary_text: str,
    seasonal: list[dict],
    due_ms: int,
    history: dict,
) -> int:
    print("\n  -- Carousel Brief Generator --")

    if not topics:
        print("  No topics — skipping.")
        return 0

    pushed = 0
    for i, topic in enumerate(topics, 1):
        print(f"\n  Carousel {i}/{len(topics)}: {topic['title']}")
        try:
            brief = generate_carousel_brief(topic, catalogue_summary_text, seasonal)
            ok = push_carousel_task(brief, due_ms)
            if ok:
                pushed += 1
                history.setdefault("carousels", []).append({
                    "date":  datetime.now().strftime("%Y-%m-%d"),
                    "topic": topic["keyword"],
                    "title": brief["title"],
                })
        except Exception as e:
            print(f"  x Carousel {i} failed: {e}")

    return pushed
