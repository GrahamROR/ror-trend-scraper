"""
Rock On Ruby — Content Generator
Calendar-driven. Runs every Tuesday. Generates and pushes all content to ClickUp.

Sources:
  - ClickUp Seasonal Dates, Marketing Calendar, Production Calendar
  - Shopify catalogue (refreshed Monday)
  - Open-Meteo 7-day forecast for Bury (free, no key)

Outputs per run:
  - [SEO Blog]         x4  — calendar-driven, 2-pass Holly voice + SEO
  - [Email]            x≤4 — from Marketing Calendar e-mail tasks
  - [Carousel]         x3  — Bethan-ready Canva briefs
  - [Weather Blog]     x0-1 — if weather trigger fires
  - [Weather Email]    x0-1 — if weather trigger fires
  - [Weather Carousel] x0-1 — if weather trigger fires
"""

import os
import re
import json
import sys
import requests
from datetime import datetime, timedelta, timezone
from pathlib import Path

import anthropic
from carousel_generator import run_carousel_generator
from weather_generator import run_weather_generator

OUTPUT_DIR      = Path(__file__).parent
CATALOGUE_FILE  = OUTPUT_DIR / "shopify_catalogue.json"
HISTORY_FILE    = OUTPUT_DIR / "content_history.json"

ANTHROPIC_KEY   = os.environ.get("ANTHROPIC_API_KEY", "")
CLICKUP_KEY     = os.environ.get("CLICKUP_API_KEY", "")
INBOX_LIST_ID   = os.environ.get("CLICKUP_LIST_ID", "901217534962")
MARKETING_LIST  = os.environ.get("CLICKUP_MARKETING_LIST", "901218493661")
SEASONAL_LIST   = os.environ.get("CLICKUP_SEASONAL_LIST", "901218516109")
PRODUCTION_LIST = os.environ.get("CLICKUP_PRODUCTION_LIST", "901218493701")

CLICKUP_BASE    = "https://api.clickup.com/api/v2"
CLICKUP_HEADERS = {"Authorization": CLICKUP_KEY, "Content-Type": "application/json"}

BRAND_CONTEXT = """
BRAND: Rock On Ruby — personalised print-on-demand clothing and accessories.
Based in Bury, Manchester. Made to order. Co-owned by Holly (brand voice) and Graham (strategy).
PRODUCTS: Personalised sweatshirts, hoodies, t-shirts, caps, tote bags, make-up bags, slogan clothing.
Production: full-colour print (never "DTF") and embroidery. Website: rockonruby.co.uk
CUSTOMER: UK women, 30-50. Busy. Thoughtful gift-buyer. Warm, funny, slightly chaotic.
POSITIONING: Anti-boring high street. The antidote to the Amazon last-minute lazy gift.
""".strip()

HOLLY_VOICE = """
HOLLY'S VOICE RULES — apply to every word:
- Short paragraphs. One idea per paragraph. Three sentences max.
- Conversational. Holly is talking to her sister, not a boardroom.
- Start emails with "Hey {first_name}". End all content with "Love Team ROR x"
- Humour: self-deprecating, warm, never forced.
- Never swear. UK spelling: personalised, colour, favourite.
- Contractions always: it's, you're, we've.
- Never use: elevated, curated, intentional, journey, effortless, timeless, wardrobe staple,
  treat yourself, honestly, girlboss, empower, stunning, amazing, incredible, seamless,
  game-changer, leverage, simply, just, very, really, perfect, ensure.
- No em dashes. No semicolons. No brackets for asides. No bullet points in body copy.
- No bold mid-paragraph. Max one exclamation mark per piece.
- Never sound like AI. Never start with "It is", "There are", "This is".
- No rhetorical filler questions.
""".strip()

BLOG_PASS1_SYSTEM = f"""{BRAND_CONTEXT}\n\n{HOLLY_VOICE}\n\nWrite a rough first-draft blog in Holly's voice. Chatty, warm, self-deprecating. Human first. SEO second."""

BLOG_PASS2_SYSTEM = f"""{BRAND_CONTEXT}\n\n{HOLLY_VOICE}\n\nYou are an SEO specialist for Rock On Ruby. Optimise the draft for Google and AI Overviews without losing Holly's voice.\n\nSTRUCTURE: Keep conversational opening. H2s as real search questions. H3s where useful. 700-900+ words. Include year when time-sensitive.\nKEYWORDS: Long-tail product phrases. Combine product + occasion + audience.\nLOCAL SEO: Mention Bury, Manchester. UK-wide delivery. Fast turnaround.\nDEPTH: Specific personalisation ideas. Emotional argument for personalised vs generic. Quality of full-colour print or embroidery vs cheap alternatives.\nFAQ: 4+ questions exactly as someone would type into Google. Every answer fully written in Holly's voice.\nCTA: Natural, low-pressure, Holly's voice. Never "shop now" or "click here".\nOUTPUT: Finished blog only. No commentary."""

EMAIL_SYSTEM = f"""{BRAND_CONTEXT}

{HOLLY_VOICE}

You write complete Klaviyo-ready marketing emails in Holly's voice. Every email is a story, never an announcement.

STRUCTURE:
1. Hey {{first_name}}, — land in a real moment, never announce the product
2. Story: a relatable moment that leads naturally to the product
3. Product intro — what it is, why it's good, one real customer reaction in Holly's voice
4. CTA: [CTA text](URL) — conversational, matches the story
5. P.S. — one punchy line
6. Love Team ROR x

RULES:
- Story angle must be specific — a real moment, not generic "gifting is nice"
- Social proof in Holly's voice: "We've had people message saying their mum cried" not testimonials
- Never mention discounts unless explicitly briefed
- One CTA per email. Never "Shop Now" or "Click Here"
- Read every sentence aloud. If it sounds like AI, rewrite it.

OUTPUT FORMAT — return exactly this, nothing else:
SUBJECT: [subject line — chatty, curious, no emojis]
PREVIEW: [preview text — one sentence, complements subject]
---
[full email body starting with Hey {{first_name}},]"""


def generate_email(email_task: dict, catalogue: dict) -> dict:
    cat_sum = catalogue_summary(catalogue, max_products=30)
    prompt  = f"Write a complete Rock On Ruby marketing email.\n\nEMAIL FROM CALENDAR: {email_task['name']}\nSEND DATE: {email_task['display']}\n\n{cat_sum}\n\nUse the title as your brief. Write the full email. Follow system instructions exactly."

    raw = claude_call(EMAIL_SYSTEM, prompt, max_tokens=2000)

    subj_m = re.search(r"^SUBJECT:\s*(.+)$", raw, re.MULTILINE)
    prev_m = re.search(r"^PREVIEW:\s*(.+)$", raw, re.MULTILINE)
    subject = subj_m.group(1).strip() if subj_m else re.sub(r"^Email\s*[-]\s*", "", email_task["name"], flags=re.IGNORECASE).strip()
    preview = prev_m.group(1).strip() if prev_m else ""
    body    = re.sub(r"^(SUBJECT|PREVIEW):.*\n?", "", raw, flags=re.MULTILINE)
    body    = re.sub(r"^---\n?", "", body, flags=re.MULTILINE).strip()

    return {
        "subject":      subject,
        "preview":      preview,
        "body":         body,
        "task_name":    email_task["name"],
        "due_ms":       email_task["due_ms"],
        "display_date": email_task["display"],
    }


def load_catalogue() -> dict:
    if CATALOGUE_FILE.exists():
        try:
            return json.loads(CATALOGUE_FILE.read_text())
        except Exception:
            pass
    return {}


def load_history() -> dict:
    if HISTORY_FILE.exists():
        try:
            return json.loads(HISTORY_FILE.read_text())
        except Exception:
            pass
    return {"blogs": [], "emails": [], "carousels": [], "weather": []}


def save_history(history: dict) -> None:
    cutoff = (datetime.now() - timedelta(days=90)).strftime("%Y-%m-%d")
    for key in ("blogs", "emails", "carousels", "weather"):
        history[key] = [e for e in history.get(key, []) if e.get("date", "") >= cutoff]
    HISTORY_FILE.write_text(json.dumps(history, indent=2))


def claude_call(system: str, prompt: str, max_tokens: int = 4096) -> str:
    client = anthropic.Anthropic(api_key=ANTHROPIC_KEY)
    msg = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=max_tokens,
        system=system,
        messages=[{"role": "user", "content": prompt}],
    )
    return msg.content[0].text.strip()


def next_friday_ms() -> int:
    today  = datetime.now(tz=timezone.utc)
    days   = (4 - today.weekday()) % 7 or 7
    friday = (today + timedelta(days=days)).replace(hour=17, minute=0, second=0, microsecond=0)
    return int(friday.timestamp() * 1000)


def fetch_clickup_tasks(list_id: str) -> list[dict]:
    url    = f"{CLICKUP_BASE}/list/{list_id}/task"
    params = {"include_closed": "false", "subtasks": "false", "limit": 100}
    try:
        resp = requests.get(url, headers=CLICKUP_HEADERS, params=params, timeout=15)
        if resp.ok:
            return resp.json().get("tasks", [])
        print(f"  ClickUp fetch failed {list_id}: {resp.status_code}")
    except Exception as e:
        print(f"  ClickUp fetch error {list_id}: {e}")
    return []


def get_upcoming_dates(list_id: str, weeks_ahead: int = 5) -> list[dict]:
    now    = datetime.now(tz=timezone.utc)
    cutoff = now + timedelta(weeks=weeks_ahead)
    items  = []
    for t in fetch_clickup_tasks(list_id):
        due_ms = t.get("due_date")
        if not due_ms:
            continue
        due_dt = datetime.fromtimestamp(int(due_ms) / 1000, tz=timezone.utc)
        if now <= due_dt <= cutoff:
            items.append({
                "name":    t["name"],
                "date":    due_dt.strftime("%Y-%m-%d"),
                "display": due_dt.strftime("%-d %B %Y"),
            })
    items.sort(key=lambda x: x["date"])
    return items


def get_email_tasks(weeks_ahead: int = 5) -> list[dict]:
    now      = datetime.now(tz=timezone.utc)
    tomorrow = now + timedelta(days=1)   # ignore anything already past due
    cutoff   = now + timedelta(weeks=weeks_ahead)
    items    = []
    for t in fetch_clickup_tasks(MARKETING_LIST):
        tags = [tag.get("name", "").lower() for tag in t.get("tags", [])]
        if "e-mail" not in tags:
            continue
        due_ms = t.get("due_date")
        if not due_ms:
            continue
        due_dt = datetime.fromtimestamp(int(due_ms) / 1000, tz=timezone.utc)
        if tomorrow <= due_dt <= cutoff:   # must be in the future
            items.append({
                "name":    t["name"],
                "date":    due_dt.strftime("%Y-%m-%d"),
                "display": due_dt.strftime("%-d %B %Y"),
                "due_ms":  int(due_ms),
            })
    items.sort(key=lambda x: x["date"])
    return items[:4]


def catalogue_summary(catalogue: dict, max_products: int = 60) -> str:
    lines = []
    if catalogue.get("bestsellers"):
        lines.append("TOP SELLING PRODUCTS (last 90 days):")
        for b in catalogue["bestsellers"][:10]:
            lines.append(f"  - {b['title']} ({b.get('orders','?')} orders)")
    lines.append("\nALL ACTIVE PRODUCTS:")
    for p in catalogue.get("products", [])[:max_products]:
        price = f"£{p['price']:.0f}" if p.get("price") else ""
        lines.append(f"  - {p['title']} {price} -> rockonruby.co.uk/products/{p['handle']}")
    lines.append("\nCOLLECTIONS:")
    for c in catalogue.get("collections", [])[:30]:
        lines.append(f"  - {c['title']} -> rockonruby.co.uk/collections/{c['handle']}")
    return "\n".join(lines)


def pick_blog_topics(seasonal, production, catalogue, history, count=4) -> list[dict]:
    cat_sum  = catalogue_summary(catalogue)
    today    = datetime.now().strftime("%-d %B %Y")
    seas_str = "\n".join(f"  - {d['name']} ({d['display']})" for d in seasonal)  or "  None upcoming"
    prod_str = "\n".join(f"  - {d['name']} ({d['display']})" for d in production) or "  None upcoming"
    recent   = ", ".join(e["topic"] for e in history.get("blogs", [])[-12:]) or "none"

    prompt = f"""You are a content strategist for Rock On Ruby, a UK personalised clothing brand.

TODAY: {today}

UPCOMING SEASONAL DATES (next 5 weeks):
{seas_str}

PRODUCTION MILESTONES:
{prod_str}

{cat_sum}

RECENTLY WRITTEN (do not repeat): {recent}

Pick exactly {count} blog topics that:
1. Connect to a date/milestone STILL IN THE FUTURE after {today}
2. Match specific products from the catalogue
3. Have not been written recently
4. Help UK women 30-50 buying personalised gifts or clothing
5. Do NOT use events that have already passed

For each topic return EXACTLY this format:

TOPIC: [H1 title — conversational, SEO-friendly, year if time-sensitive]
KEYWORD: [2-5 word search phrase]
SEASONAL_HOOK: [which date/milestone]
FEATURED_PRODUCTS: [2-4 product names, comma-separated]
COLLECTION_URL: [best rockonruby.co.uk URL]
STORY_ANGLE: [one sentence — relatable opening moment]
TENSION: [one sentence — reader's problem]
SHIFT: [one sentence — how ROR solves it]
BUYER_PERSONA: [one sentence — who searches this and why]

---

TOPIC: ...
(repeat for all {count})"""

    raw    = claude_call("Return only the structured output requested. Nothing else.", prompt, max_tokens=2000)
    topics = []
    for block in raw.strip().split("---"):
        block = block.strip()
        if not block or "TOPIC:" not in block:
            continue
        def ex(k):
            m = re.search(rf"^{k}:\s*(.+)$", block, re.MULTILINE)
            return m.group(1).strip() if m else ""
        topics.append({
            "title":    ex("TOPIC"),
            "keyword":  ex("KEYWORD"),
            "hook":     ex("SEASONAL_HOOK"),
            "products": ex("FEATURED_PRODUCTS"),
            "url":      ex("COLLECTION_URL"),
            "angle":    ex("STORY_ANGLE"),
            "tension":  ex("TENSION"),
            "shift":    ex("SHIFT"),
            "persona":  ex("BUYER_PERSONA"),
        })
    return topics[:count]


def generate_blog(topic: dict, catalogue: dict) -> str:
    cat_sum = catalogue_summary(catalogue, max_products=30)
    context = f"BLOG BRIEF:\nTitle: {topic['title']}\nKeyword: {topic['keyword']}\nHook: {topic['hook']}\nProducts: {topic['products']}\nURL: {topic['url']}\nAngle: {topic['angle']}\nTension: {topic['tension']}\nShift: {topic['shift']}\nPersona: {topic['persona']}\n\n{cat_sum}"

    print("    Pass 1 (voice)...")
    draft = claude_call(BLOG_PASS1_SYSTEM, f"Write a rough first draft in Holly's voice. Chatty, warm.\n\n{context}", max_tokens=3000)
    print("    Pass 2 (SEO)...")
    return claude_call(BLOG_PASS2_SYSTEM, f"Optimise this draft. Keep Holly's voice.\n\n{context}\n\nPASS 1:\n{draft}", max_tokens=6000)


def generate_email(email_task: dict, catalogue: dict) -> dict:
    cat_sum = catalogue_summary(catalogue, max_products=30)
    prompt  = f"Write a complete Rock On Ruby marketing email.\n\nEMAIL FROM CALENDAR: {email_task['name']}\nSEND DATE: {email_task['display']}\n\n{cat_sum}\n\nUse the title as your brief. Write the full email. Follow system instructions exactly."

    raw = claude_call(EMAIL_SYSTEM, prompt, max_tokens=2000)

    subj_m = re.search(r"^SUBJECT:\s*(.+)$", raw, re.MULTILINE)
    prev_m = re.search(r"^PREVIEW:\s*(.+)$", raw, re.MULTILINE)
    subj   = subj_m.group(1).strip() if subj_m else re.sub(r"^Email\s*[-]\s*", "", email_task["name"], flags=re.IGNORECASE).strip()
    prev   = prev_m.group(1).strip() if prev_m else ""
    body   = re.sub(r"^(SUBJECT|PREVIEW):.*\n?", "", raw, flags=re.MULTILINE)
    body   = re.sub(r"^---\n?", "", body, flags=re.MULTILINE).strip()

    return {"subject": subj, "preview": prev, "body": body, "task_name": email_task["name"], "due_ms": email_task["due_ms"], "display_date": email_task["display"]}


def clickup_create_task(name, description, tags, due_ms, status="generated"):
    payload = {"name": name, "description": description, "due_date": due_ms, "due_date_time": True, "status": status, "tags": tags}
    try:
        resp = requests.post(f"{CLICKUP_BASE}/list/{INBOX_LIST_ID}/task", headers=CLICKUP_HEADERS, json=payload, timeout=15)
        if resp.ok:
            print(f"  + {name}")
            print(f"    {resp.json().get('url','')}")
            return resp.json().get("id")
        print(f"  x Failed: {name} — {resp.status_code}: {resp.text[:100]}")
    except Exception as e:
        print(f"  x Error: {name} — {e}")
    return None


def push_blog_task(topic, content, due_ms):
    today = datetime.now().strftime("%d %b")
    return clickup_create_task(
        name=f"[SEO Blog] {topic['title']} — {today}",
        description=f"KEYWORD: {topic['keyword']}\nHOOK: {topic['hook']}\nPRODUCTS: {topic['products']}\nURL: {topic['url']}\n\n---\n\n{content}\n\n---\nLove Team ROR x",
        tags=["blog"], due_ms=due_ms,
    ) is not None


def push_email_task(email):
    today = datetime.now().strftime("%d %b")
    return clickup_create_task(
        name=f"[Email] {email['subject']} — {today}",
        description=f"SUBJECT: {email['subject']}\nPREVIEW: {email['preview']}\nSEND DATE: {email['display_date']}\nSOURCE: {email['task_name']}\n\n---\n\n{email['body']}",
        tags=["email"], due_ms=email["due_ms"],
    ) is not None


def main() -> int:
    print("\n-- ROR Content Generator --")
    print(f"   {datetime.now().strftime('%A %d %B %Y, %H:%M')}\n")

    if not ANTHROPIC_KEY:
        print("  ANTHROPIC_API_KEY not set — exiting."); return 1
    if not CLICKUP_KEY:
        print("  CLICKUP_API_KEY not set — exiting."); return 1

    # Guard: skip if already ran today (prevents duplicate runs from manual triggers)
    history_check = load_history()
    today_str = datetime.now().strftime("%Y-%m-%d")
    ran_today = any(e.get("date") == today_str for e in history_check.get("blogs", []))
    if ran_today:
        print(f"  Already ran today ({today_str}) — skipping to prevent duplicates.")
        print("  To force a re-run, clear today's entries from content_history.json first.")
        return 0

    catalogue = load_catalogue()
    if not catalogue:
        print("  shopify_catalogue.json not found. Run shopify_sync.py first."); return 1

    history = load_history()
    due_ms  = next_friday_ms()
    cat_sum = catalogue_summary(catalogue)

    # 1. Read calendars
    print("[1/6] Reading calendars...")
    seasonal    = get_upcoming_dates(SEASONAL_LIST,   weeks_ahead=5)
    production  = get_upcoming_dates(PRODUCTION_LIST, weeks_ahead=5)
    email_tasks = get_email_tasks(weeks_ahead=5)
    print(f"  Seasonal dates: {len(seasonal)} | Production: {len(production)} | Emails: {len(email_tasks)}")

    # 2. Pick topics
    print("\n[2/6] Picking blog topics...")
    topics = pick_blog_topics(seasonal, production, catalogue, history, count=4)
    if not topics:
        print("  No topics — check calendar and API."); return 1
    for t in topics:
        print(f"  · {t['title']}")

    # 3. Write blogs
    print("\n[3/6] Writing blogs...")
    blog_results = []
    for i, topic in enumerate(topics, 1):
        print(f"\n  Blog {i}/4: {topic['keyword']}")
        try:
            blog_results.append((topic, generate_blog(topic, catalogue)))
        except Exception as e:
            print(f"  x Failed: {e}")

    # 4. Write emails
    print("\n[4/6] Writing emails...")
    email_results = []
    if email_tasks:
        for et in email_tasks:
            print(f"  · {et['name']}")
            try:
                email_results.append(generate_email(et, catalogue))
            except Exception as e:
                print(f"  x Failed: {e}")
    else:
        print("  No email tasks due — skipping.")

    # 5. Push blogs + emails
    print("\n[5/6] Pushing blogs and emails...")
    blogs_pushed = emails_pushed = 0
    for topic, content in blog_results:
        if push_blog_task(topic, content, due_ms):
            blogs_pushed += 1
            history.setdefault("blogs", []).append({"date": datetime.now().strftime("%Y-%m-%d"), "topic": topic["keyword"], "title": topic["title"]})

    for email in email_results:
        if push_email_task(email):
            emails_pushed += 1
            history.setdefault("emails", []).append({"date": datetime.now().strftime("%Y-%m-%d"), "topic": email["task_name"], "subject": email["subject"]})

    save_history(history)

    # 6a. Carousels
    print("\n[6a/6] Writing carousels...")
    carousels_pushed = run_carousel_generator(
        topics=[t for t, _ in blog_results][:3],
        catalogue_summary_text=cat_sum,
        seasonal=seasonal,
        due_ms=due_ms,
        history=history,
    )
    save_history(history)

    # 6b. Weather
    print("\n[6b/6] Checking weather...")
    weather_pushed = run_weather_generator(due_ms=due_ms, history=history, catalogue_summary=cat_sum)
    save_history(history)

    print(f"\n-- Done --")
    print(f"  Blogs:     {blogs_pushed}/4")
    print(f"  Emails:    {emails_pushed}/{len(email_results)}")
    print(f"  Carousels: {carousels_pushed}/3")
    print(f"  Weather:   {weather_pushed}/3 (0 = no trigger this week)")

    return 0


if __name__ == "__main__":
    sys.exit(main())
