"""
Rock On Ruby — Content Generator
Calendar-driven blog and email writer. No external trend APIs required.

Sources:
  - ClickUp Calendars (Seasonal Dates, Marketing Calendar) via API
  - shopify_catalogue.json (refreshed Monday by shopify_sync.py)

Outputs (via clickup_tasks.py):
  - 2 x [SEO Blog] tasks  →  Generated Content Inbox
  - N x [Email] tasks     →  Generated Content Inbox (one per e-mail task due this week)

Required env vars:
  ANTHROPIC_API_KEY
  CLICKUP_API_KEY
  CLICKUP_LIST_ID        — Generated Content Inbox list ID
  CLICKUP_MARKETING_LIST — Marketing Calendar list ID (default 901218493661)
  CLICKUP_SEASONAL_LIST  — Seasonal Dates list ID (default 901218516109)
  CLICKUP_PRODUCTION_LIST — Production Calendar list ID (default 901218493701)
"""

import os
import json
import sys
import requests
from datetime import datetime, timedelta, timezone
from pathlib import Path

import anthropic
from series_generator import run_series_generator

# ── Config ────────────────────────────────────────────────────────────────────

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

# ── Brand constants ───────────────────────────────────────────────────────────

BRAND_CONTEXT = """
BRAND: Rock On Ruby — personalised print-on-demand clothing and accessories.
Based in Bury, Manchester. Made to order. Co-owned by Holly (brand voice, on-camera) and Graham (strategy).

PRODUCTS: Personalised sweatshirts, hoodies, t-shirts, caps, tote bags, make-up bags and slogan clothing.
Production methods: DTF full-colour print (call it "full-colour print", never "DTF") and embroidery.
Website: rockonruby.co.uk

CUSTOMER: UK women, 30–50. Busy. Thoughtful gift-buyer. Warm, funny, slightly chaotic.
POSITIONING: Anti-boring high street. The antidote to the Amazon last-minute lazy gift.
""".strip()

HOLLY_VOICE = """
HOLLY'S VOICE RULES — apply to every word without exception:
- Short paragraphs. One idea per paragraph. Three sentences max.
- Conversational. Holly is talking to her sister, not presenting to a boardroom.
- Start emails with "Hey [first_name]". Never apologise for making contact.
- End all content with "Love Team ROR x"
- Humour: self-deprecating, warm, never forced. If a joke doesn't land naturally, cut it.
- Never swear.
- UK spelling always: personalised, colour, favourite.
- Contractions always: it's, you're, we've — never the full form.
- Never use: elevated, curated, intentional, journey, effortless, timeless, wardrobe staple,
  perfect for any occasion, treat yourself, honestly, girlboss, empower, excited to share,
  boss babe, stunning, beautiful, amazing, incredible, seamless, nestled, delve, game-changer,
  leverage, cutting-edge, innovative, simply, just, very, really, perfect, ensure.
- Never use em dashes or en dashes. Use a comma, full stop, or rewrite.
- No semicolons. No brackets for asides.
- No bullet points in blog or email copy. Work all information into natural sentences.
- No bold text for emphasis mid-paragraph.
- Exclamation marks: maximum one per piece. Earned, not scattered.
- Never sound like AI wrote it. Read every sentence as if saying it aloud.
- Never start with "It is", "There are", "This is".
- No rhetorical filler questions ("Sound familiar?", "Want to know more?").
- Never summarise what you just said at the end of a section. Say it once, say it well, move on.
- If it could have been written by ChatGPT, rewrite it until it couldn't.
""".strip()

BLOG_PASS1_SYSTEM = f"""{BRAND_CONTEXT}

{HOLLY_VOICE}

You are writing a rough first-draft blog post for Rock On Ruby in Holly's voice.
Write chatty, warm, self-deprecating UK copy. Short paragraphs. Never corporate, formal or salesy.
Focus on making it sound human first. SEO comes in pass 2.
"""

BLOG_PASS2_SYSTEM = f"""{BRAND_CONTEXT}

{HOLLY_VOICE}

You are an SEO specialist working exclusively for Rock On Ruby.
Take a rough blog draft and optimise it fully for Google search and AI Overviews without losing Holly's voice.

STRUCTURE:
- Keep the conversational opening intact. Do not make it formal.
- Break the body into H2 sections phrased as questions real buyers search.
- Add H3 subheadings within longer sections where useful.
- Target 700–900 words minimum.
- Include the specific year in H1 and first paragraph when the topic is time-sensitive.

KEYWORDS:
- Expand product mentions into long-tail keyword phrases specific to this blog topic.
- Never use generic one-word names when a more specific phrase fits.
- Combine product phrases with the occasion, audience or use case for this exact blog.

LOCAL SEO:
- Mention Bury, Manchester naturally at least once.
- Mention UK-wide delivery or delivered across the UK at least once.
- Reference fast turnaround for time-sensitive topics.

BUYER PERSONAS:
- Include at least one specific buyer scenario relevant to this blog topic.

DEPTH:
- Give specific personalisation ideas: nicknames, birth years, in-jokes, catchphrases.
- Explain why personalised beats generic using the emotional argument, not features.
- Reference quality of Rock On Ruby full-colour print or embroidery versus cheap alternatives at least once.

FAQ SECTION:
- Add a fully written FAQ at the bottom with at least 4 questions.
- Questions phrased exactly as someone would type into Google or ask ChatGPT.
- Every answer fully written in Holly's voice. No placeholders.

CTA:
- End with a natural, low-pressure CTA to rockonruby.co.uk.
- Holly's voice. Never "shop now" or "click here".

OUTPUT: Return only the finished blog. No commentary, notes or explanations.
"""

EMAIL_SYSTEM = f"""{BRAND_CONTEXT}

{HOLLY_VOICE}

You are writing a complete Klaviyo-ready marketing email for Rock On Ruby in Holly's voice.
Write the full email — every word. No briefs, no placeholders, no structure notes. Just the email.

STRUCTURE (every email must follow this):
1. Hey {{{{first_name}}}},  (opening line — land in a real moment, never announce the product)
2. Story: a relatable moment that leads naturally to the product
3. Introduce the product or offer simply — what it is, why it's good, one real-customer reaction
4. CTA paragraph with a link formatted as: [CTA text](URL)
5. P.S. — one punchy line, often a nudge or a twist on the main message
6. Love Team ROR x

EMAIL RULES:
- One idea per paragraph. Three lines max.
- Subject line: chatty, creates curiosity, no emojis, not salesy.
- Preview text: 1 sentence, complements subject line without repeating it.
- Never mention discounts, percentages or sale language unless explicitly briefed.
- Story angle must be specific — not generic "gifting is nice". A real moment: a party, a school run, a 5pm Friday.
- Social proof: Holly's voice, not formal testimonials. "We've had people message saying their mum cried" not "customers love this product".
- CTA text: conversational, matches the story. Never "Shop Now" or "Click Here".

OUTPUT FORMAT — return exactly this, nothing else:
SUBJECT: [subject line]
PREVIEW: [preview text]
---
[full email body starting with Hey {{{{first_name}}}},]
"""

# ── Utilities ─────────────────────────────────────────────────────────────────

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
    return {"blogs": [], "emails": []}


def save_history(history: dict) -> None:
    # Prune to last 90 days
    cutoff = (datetime.now() - timedelta(days=90)).strftime("%Y-%m-%d")
    for key in ("blogs", "emails"):
        history[key] = [e for e in history.get(key, []) if e.get("date", "") >= cutoff]
    HISTORY_FILE.write_text(json.dumps(history, indent=2))


def recently_used(topic: str, history: dict, key: str, days: int = 21) -> bool:
    cutoff = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d")
    return any(
        e.get("topic", "").lower() == topic.lower() and e.get("date", "") >= cutoff
        for e in history.get(key, [])
    )


def claude_call(system: str, prompt: str, max_tokens: int = 4096) -> str:
    client = anthropic.Anthropic(api_key=ANTHROPIC_KEY)
    msg = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=max_tokens,
        system=system,
        messages=[{"role": "user", "content": prompt}],
    )
    return msg.content[0].text.strip()


def ms_to_date(ms: str | None) -> str | None:
    if not ms:
        return None
    try:
        return datetime.fromtimestamp(int(ms) / 1000, tz=timezone.utc).strftime("%Y-%m-%d")
    except Exception:
        return None


def date_to_ms(date_str: str) -> int:
    dt = datetime.strptime(date_str, "%Y-%m-%d").replace(
        hour=17, minute=0, second=0, tzinfo=timezone.utc
    )
    return int(dt.timestamp() * 1000)


def next_friday_ms() -> int:
    today = datetime.now(tz=timezone.utc)
    days = (4 - today.weekday()) % 7 or 7
    friday = (today + timedelta(days=days)).replace(hour=17, minute=0, second=0, microsecond=0)
    return int(friday.timestamp() * 1000)


# ── ClickUp calendar readers ──────────────────────────────────────────────────

def fetch_clickup_tasks(list_id: str) -> list[dict]:
    """Fetch all open tasks from a ClickUp list."""
    url = f"{CLICKUP_BASE}/list/{list_id}/task"
    params = {"include_closed": "false", "subtasks": "false", "limit": 100}
    try:
        resp = requests.get(url, headers=CLICKUP_HEADERS, params=params, timeout=15)
        if resp.ok:
            return resp.json().get("tasks", [])
        print(f"  ClickUp fetch failed {list_id}: {resp.status_code}")
    except Exception as e:
        print(f"  ClickUp fetch error {list_id}: {e}")
    return []


def get_upcoming_seasonal_dates(weeks_ahead: int = 8) -> list[dict]:
    """Return seasonal dates with due dates in the next N weeks."""
    now = datetime.now(tz=timezone.utc)
    cutoff = now + timedelta(weeks=weeks_ahead)
    tasks = fetch_clickup_tasks(SEASONAL_LIST)
    upcoming = []
    for t in tasks:
        due_ms = t.get("due_date")
        if not due_ms:
            continue
        due_dt = datetime.fromtimestamp(int(due_ms) / 1000, tz=timezone.utc)
        if now <= due_dt <= cutoff:
            upcoming.append({
                "name": t["name"],
                "date": due_dt.strftime("%Y-%m-%d"),
                "display": due_dt.strftime("%-d %B %Y"),
            })
    upcoming.sort(key=lambda x: x["date"])
    return upcoming


def get_upcoming_production_dates(weeks_ahead: int = 8) -> list[dict]:
    """Return production calendar items in the next N weeks."""
    now = datetime.now(tz=timezone.utc)
    cutoff = now + timedelta(weeks=weeks_ahead)
    tasks = fetch_clickup_tasks(PRODUCTION_LIST)
    upcoming = []
    for t in tasks:
        due_ms = t.get("due_date")
        if not due_ms:
            continue
        due_dt = datetime.fromtimestamp(int(due_ms) / 1000, tz=timezone.utc)
        if now <= due_dt <= cutoff:
            upcoming.append({
                "name": t["name"],
                "date": due_dt.strftime("%Y-%m-%d"),
                "display": due_dt.strftime("%-d %B %Y"),
            })
    upcoming.sort(key=lambda x: x["date"])
    return upcoming


def get_email_tasks_this_week() -> list[dict]:
    """Return marketing calendar tasks tagged 'e-mail' due in the next 7 days."""
    now = datetime.now(tz=timezone.utc)
    cutoff = now + timedelta(days=7)
    tasks = fetch_clickup_tasks(MARKETING_LIST)
    email_tasks = []
    for t in tasks:
        tags = [tag.get("name", "").lower() for tag in t.get("tags", [])]
        if "e-mail" not in tags:
            continue
        due_ms = t.get("due_date")
        if not due_ms:
            continue
        due_dt = datetime.fromtimestamp(int(due_ms) / 1000, tz=timezone.utc)
        if due_dt <= cutoff:
            email_tasks.append({
                "name": t["name"],
                "date": due_dt.strftime("%Y-%m-%d"),
                "display": due_dt.strftime("%-d %B %Y"),
                "due_ms": int(due_ms),
            })
    email_tasks.sort(key=lambda x: x["date"])
    return email_tasks


# ── Catalogue helpers ─────────────────────────────────────────────────────────

def catalogue_summary(catalogue: dict, max_products: int = 60) -> str:
    """Build a compact text summary of the Shopify catalogue for Claude."""
    lines = []

    bestsellers = catalogue.get("bestsellers", [])
    if bestsellers:
        lines.append("TOP SELLING PRODUCTS (last 90 days):")
        for b in bestsellers[:10]:
            lines.append(f"  - {b['title']} ({b.get('orders', '?')} orders)")

    lines.append("\nALL ACTIVE PRODUCTS:")
    for p in catalogue.get("products", [])[:max_products]:
        price = f"£{p['price']:.0f}" if p.get("price") else ""
        lines.append(f"  - {p['title']} {price} → rockonruby.co.uk/products/{p['handle']}")

    lines.append("\nCOLLECTIONS:")
    for c in catalogue.get("collections", [])[:30]:
        lines.append(f"  - {c['title']} → rockonruby.co.uk/collections/{c['handle']}")

    return "\n".join(lines)


def find_product_url(title: str, catalogue: dict) -> str:
    """Find the best matching product or collection URL for a given title."""
    title_lower = title.lower()
    for p in catalogue.get("products", []):
        if p["title"].lower() == title_lower:
            return f"rockonruby.co.uk/products/{p['handle']}"
    for p in catalogue.get("products", []):
        if title_lower in p["title"].lower() or p["title"].lower() in title_lower:
            return f"rockonruby.co.uk/products/{p['handle']}"
    for c in catalogue.get("collections", []):
        if title_lower in c["title"].lower():
            return f"rockonruby.co.uk/collections/{c['handle']}"
    return "rockonruby.co.uk"


# ── Blog generation ───────────────────────────────────────────────────────────

def pick_blog_topics(
    seasonal: list[dict],
    production: list[dict],
    catalogue: dict,
    history: dict,
    count: int = 2,
) -> list[dict]:
    """
    Ask Claude to pick the 2 best blog topics from the calendar context
    and match them to specific products. Returns a list of topic dicts.
    """
    cat_summary = catalogue_summary(catalogue)

    seasonal_lines = "\n".join(
        f"  - {d['name']} ({d['display']})" for d in seasonal
    ) or "  None upcoming"

    production_lines = "\n".join(
        f"  - {d['name']} ({d['display']})" for d in production
    ) or "  None upcoming"

    recent_blogs = [e["topic"] for e in history.get("blogs", [])[-10:]]
    recent_str = ", ".join(recent_blogs) if recent_blogs else "none"

    prompt = f"""
You are a content strategist for Rock On Ruby, a UK personalised clothing and accessories brand.

Here is what's coming up in the next 8 weeks:

SEASONAL DATES:
{seasonal_lines}

PRODUCTION MILESTONES:
{production_lines}

{cat_summary}

RECENTLY WRITTEN BLOGS (do not repeat these topics):
{recent_str}

Choose exactly {count} blog topics that:
1. Are relevant to a seasonal date or production milestone coming up in the next 8 weeks
2. Connect directly to specific Rock On Ruby products (use actual product names and URLs from the catalogue above)
3. Haven't been written recently
4. Would genuinely help UK women aged 30-50 who are buying personalised gifts or clothing for themselves

For each topic return EXACTLY this format (no other text):

TOPIC: [blog title as an H1 — conversational, SEO-friendly, includes year if time-sensitive]
KEYWORD: [primary search keyword, 2-5 words, what someone would type into Google]
SEASONAL_HOOK: [which upcoming date or milestone this connects to]
FEATURED_PRODUCTS: [2-4 specific product names from the catalogue, comma-separated]
COLLECTION_URL: [the best collection or product URL from rockonruby.co.uk to link to]
STORY_ANGLE: [one sentence — the relatable real-life moment that opens the blog]
TENSION: [one sentence — the problem the reader has]
SHIFT: [one sentence — how ROR solves it]
BUYER_PERSONA: [one sentence — who is searching for this and why]

---

TOPIC: ...
(repeat for each topic)
""".strip()

    raw = claude_call(
        "You are a precise content strategist. Return only the structured output requested, nothing else.",
        prompt,
        max_tokens=1500,
    )

    topics = []
    for block in raw.strip().split("---"):
        block = block.strip()
        if not block or "TOPIC:" not in block:
            continue
        def extract(key: str) -> str:
            import re
            m = re.search(rf"^{key}:\s*(.+)$", block, re.MULTILINE)
            return m.group(1).strip() if m else ""

        topics.append({
            "title":      extract("TOPIC"),
            "keyword":    extract("KEYWORD"),
            "hook":       extract("SEASONAL_HOOK"),
            "products":   extract("FEATURED_PRODUCTS"),
            "url":        extract("COLLECTION_URL"),
            "angle":      extract("STORY_ANGLE"),
            "tension":    extract("TENSION"),
            "shift":      extract("SHIFT"),
            "persona":    extract("BUYER_PERSONA"),
        })

    return topics[:count]


def generate_blog(topic: dict, catalogue: dict) -> str:
    """Two-pass blog generation: Pass 1 = Holly voice, Pass 2 = SEO optimised."""
    cat_summary = catalogue_summary(catalogue, max_products=30)

    context = f"""
BLOG BRIEF:
Title/H1: {topic['title']}
Primary keyword: {topic['keyword']}
Seasonal hook: {topic['hook']}
Featured products: {topic['products']}
Best collection/product URL: {topic['url']}
Story angle (opening moment): {topic['angle']}
Tension (reader's problem): {topic['tension']}
Shift (ROR's solution): {topic['shift']}
Buyer persona: {topic['persona']}

RELEVANT CATALOGUE EXCERPT:
{cat_summary}
""".strip()

    # Pass 1 — rough Holly voice draft
    print(f"    Pass 1 (Holly voice): {topic['keyword']}")
    pass1_prompt = f"""
Write a rough first draft of this blog in Holly's voice.
Chatty, warm, self-deprecating. Short paragraphs. Human first, SEO second.
Do not hold back on personality. Make it sound like Holly is talking to a mate.

{context}
""".strip()
    draft = claude_call(BLOG_PASS1_SYSTEM, pass1_prompt, max_tokens=3000)

    # Pass 2 — SEO optimised
    print(f"    Pass 2 (SEO): {topic['keyword']}")
    pass2_prompt = f"""
Take this Pass 1 blog draft and optimise it fully using your system instructions.
Keep Holly's voice intact. Do not make it corporate.

{context}

PASS 1 DRAFT:
{draft}
""".strip()
    return claude_call(BLOG_PASS2_SYSTEM, pass2_prompt, max_tokens=6000)


# ── Email generation ──────────────────────────────────────────────────────────

def generate_email(email_task: dict, catalogue: dict) -> dict:
    """Write a complete finished email from a Marketing Calendar task name."""
    cat_summary = catalogue_summary(catalogue, max_products=30)

    prompt = f"""
Write a complete Rock On Ruby marketing email based on this brief.

EMAIL TITLE FROM MARKETING CALENDAR: {email_task['name']}
SEND DATE: {email_task['display']}

{cat_summary}

Instructions:
- Use the email title as your brief. Interpret it and write the full email.
- Choose the most relevant Rock On Ruby products from the catalogue to feature.
- Write the complete email — subject line, preview text, and full body.
- Follow your system instructions exactly.
- The CTA should link to the most relevant product or collection URL from the catalogue.
""".strip()

    raw = claude_call(EMAIL_SYSTEM, prompt, max_tokens=2000)

    # Parse subject and preview from output
    import re
    subject = ""
    preview = ""
    body = raw

    subject_match = re.search(r"^SUBJECT:\s*(.+)$", raw, re.MULTILINE)
    preview_match = re.search(r"^PREVIEW:\s*(.+)$", raw, re.MULTILINE)

    if subject_match:
        subject = subject_match.group(1).strip()
    if preview_match:
        preview = preview_match.group(1).strip()

    # Strip header lines to get clean body
    body = re.sub(r"^SUBJECT:.*\n?", "", body, flags=re.MULTILINE)
    body = re.sub(r"^PREVIEW:.*\n?", "", body, flags=re.MULTILINE)
    body = re.sub(r"^---\n?", "", body, flags=re.MULTILINE)
    body = body.strip()

    # Fall back to task name as subject if not parsed
    if not subject:
        # Strip "Email - " prefix
        subject = re.sub(r"^Email\s*[-–]\s*", "", email_task["name"], flags=re.IGNORECASE).strip()

    return {
        "subject": subject,
        "preview": preview,
        "body": body,
        "task_name": email_task["name"],
        "due_ms": email_task["due_ms"],
        "display_date": email_task["display"],
    }


# ── ClickUp task creation ─────────────────────────────────────────────────────

def clickup_create_task(name: str, description: str, tags: list[str], due_ms: int, status: str = "generated") -> str | None:
    payload = {
        "name": name,
        "description": description,
        "due_date": due_ms,
        "due_date_time": True,
        "status": status,
        "tags": tags,
    }
    try:
        resp = requests.post(
            f"{CLICKUP_BASE}/list/{INBOX_LIST_ID}/task",
            headers=CLICKUP_HEADERS,
            json=payload,
            timeout=15,
        )
        if resp.ok:
            url = resp.json().get("url", "")
            print(f"  + Created: {name}")
            print(f"    {url}")
            return resp.json().get("id")
        print(f"  x Failed: {name} — {resp.status_code}: {resp.text[:120]}")
    except Exception as e:
        print(f"  x Error: {name} — {e}")
    return None


def push_blog_task(topic: dict, blog_content: str, due_ms: int) -> bool:
    today = datetime.now().strftime("%d %b")
    task_name = f"[SEO Blog] {topic['title']} — {today}"

    description = f"""KEYWORD: {topic['keyword']}
SEASONAL HOOK: {topic['hook']}
FEATURED PRODUCTS: {topic['products']}
TARGET URL: {topic['url']}

---

{blog_content}

---
Love Team ROR x"""

    task_id = clickup_create_task(
        name=task_name,
        description=description,
        tags=["blog"],
        due_ms=due_ms,
        status="generated",
    )
    return task_id is not None


def push_email_task(email: dict, due_ms: int) -> bool:
    today = datetime.now().strftime("%d %b")
    task_name = f"[Email] {email['subject']} — {today}"

    description = f"""SUBJECT: {email['subject']}
PREVIEW TEXT: {email['preview']}
SEND DATE: {email['display_date']}
SOURCE: {email['task_name']}

---

{email['body']}"""

    task_id = clickup_create_task(
        name=task_name,
        description=description,
        tags=["email"],
        due_ms=due_ms,
        status="generated",
    )
    return task_id is not None


# ── Main ──────────────────────────────────────────────────────────────────────

def main() -> int:
    print("\n-- ROR Content Generator --")
    print(f"  {datetime.now().strftime('%A %d %B %Y, %H:%M')}")

    if not ANTHROPIC_KEY:
        print("  ANTHROPIC_API_KEY not set — exiting.")
        return 1

    if not CLICKUP_KEY:
        print("  CLICKUP_API_KEY not set — exiting.")
        return 1

    catalogue = load_catalogue()
    if not catalogue:
        print("  shopify_catalogue.json not found or empty. Run shopify_sync.py first.")
        return 1

    history = load_history()
    due_ms = next_friday_ms()

    # ── Step 1: Read calendars ────────────────────────────────────────────────
    print("\n  Reading calendars...")
    seasonal   = get_upcoming_seasonal_dates(weeks_ahead=8)
    production = get_upcoming_production_dates(weeks_ahead=8)
    email_tasks = get_email_tasks_this_week()

    print(f"  Seasonal dates: {len(seasonal)}")
    for d in seasonal[:5]:
        print(f"    - {d['name']} ({d['display']})")

    print(f"  Production milestones: {len(production)}")
    for d in production[:3]:
        print(f"    - {d['name']} ({d['display']})")

    print(f"  Email tasks due this week: {len(email_tasks)}")
    for e in email_tasks:
        print(f"    - {e['name']} ({e['display']})")

    # ── Step 2: Pick and write 2 blogs ────────────────────────────────────────
    print("\n  Picking blog topics...")
    topics = pick_blog_topics(seasonal, production, catalogue, history, count=2)

    if not topics:
        print("  No blog topics generated — check calendar data and API key.")
        return 1

    blog_results = []
    for i, topic in enumerate(topics, 1):
        print(f"\n  Blog {i}/{len(topics)}: {topic['title']}")
        try:
            content = generate_blog(topic, catalogue)
            blog_results.append((topic, content))
        except Exception as e:
            print(f"  x Blog failed: {e}")

    # ── Step 3: Write emails ──────────────────────────────────────────────────
    email_results = []
    if email_tasks:
        print(f"\n  Writing {len(email_tasks)} email(s)...")
        for email_task in email_tasks:
            print(f"\n  Email: {email_task['name']}")
            try:
                email = generate_email(email_task, catalogue)
                email_results.append(email)
            except Exception as e:
                print(f"  x Email failed: {e}")
    else:
        print("\n  No email tasks due this week — skipping.")

    # ── Step 4: Push to ClickUp ───────────────────────────────────────────────
    print("\n  Pushing to ClickUp...")
    blogs_pushed = 0
    emails_pushed = 0

    for topic, content in blog_results:
        ok = push_blog_task(topic, content, due_ms)
        if ok:
            blogs_pushed += 1
            history.setdefault("blogs", []).append({
                "date": datetime.now().strftime("%Y-%m-%d"),
                "topic": topic["keyword"],
                "title": topic["title"],
            })

    for email in email_results:
        ok = push_email_task(email, email["due_ms"])
        if ok:
            emails_pushed += 1
            history.setdefault("emails", []).append({
                "date": datetime.now().strftime("%Y-%m-%d"),
                "topic": email["task_name"],
                "subject": email["subject"],
            })

    save_history(history)

    # ── Step 5: Content series ideas ─────────────────────────────────────────
    series_ok = run_series_generator(due_ms, history)
    save_history(history)

    # ── Summary ───────────────────────────────────────────────────────────────
    print(f"\n  Done.")
    print(f"  Blogs created:  {blogs_pushed}/{len(blog_results)}")
    print(f"  Emails created: {emails_pushed}/{len(email_results)}")
    print(f"  Series ideas:   {'pushed to ClickUp' if series_ok else 'skipped'}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
