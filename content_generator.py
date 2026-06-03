"""
Rock On Ruby - AI Content Generator
Reads trend_cache.json and content_history.json, generates content via Claude,
updates history so each run produces fresh topics. Called by the content workflow.

Content per run:
  - Layer 4 (bestsellers): 3 pieces
  - All other layers: 2 pieces each
  - SEO-driven: blog drafts for 'write blog post' keywords (capped at 10 total pieces)
  - Email section outputs a full design prompt, not just a subject line

Requires: ANTHROPIC_API_KEY environment variable
"""

import os
import json
import re
import argparse
from datetime import datetime, timedelta
from pathlib import Path
import anthropic

OUTPUT_DIR       = Path(__file__).parent
CONTENT_FILE     = OUTPUT_DIR / "ror_content_draft.md"
HISTORY_FILE     = OUTPUT_DIR / "content_history.json"
CACHE_FILE       = OUTPUT_DIR / "trend_cache.json"
FOCUS_FILE       = OUTPUT_DIR / "ror_focus.json"
CATALOGUE_FILE   = OUTPUT_DIR / "shopify_catalogue.json"
INSTAGRAM_FILE   = OUTPUT_DIR / "instagram_insights.json"
DESIGN_RULES_FILE = OUTPUT_DIR / "design_system" / "ror_design_rules.md"
RANK_CACHE_FILE = OUTPUT_DIR / "rank_tracker_cache.json"

BRAND_CONTEXT = """
BRAND: Rock On Ruby, print-on-demand personalised clothing and accessories.
Based in Bury, Manchester. Co-owned by Holly (brand voice) and Graham (strategy).

PRODUCTS: Personalised clothing and accessories using DTF print and embroidery.
DTF PRINT: Full-colour print, explained to customers as full-colour print rather than jargon.
EMBROIDERY: Used where embroidery is genuinely the right production method, especially caps and selected personalised products.
PRODUCT TYPES: Caps, sweatshirts, hoodies, tees, tote bags, make-up bags and slogan clothing.
CUSTOMER: UK women, 30-50. Busy. Thoughtful gift-buyer. Warm, funny, slightly chaotic.
POSITIONING: Anti-boring high street. The antidote to the Amazon last-minute lazy gift.
WEBSITE: rockonruby.co.uk

HOLLY'S VOICE RULES:
- Short paragraphs. One idea per paragraph.
- Conversational, talking not presenting
- Start emails with "Hey" or "Hi". Never apologise for making contact.
- End emails: "See ya!" or "Love Team ROR x"
- Humour: self-deprecating, warm, never forced
- Swearing: NEVER. Clean throughout.
- NO: elevated, curated, intentional, journey, effortless, timeless, wardrobe staple,
  perfect for any occasion, treat yourself, honestly, girlboss, empower, excited to share,
  boss babe
- NEVER sound like AI wrote it. No corporate language. No hard sell.
- Always write to ONE person, Holly's sister. Never to a crowd.

BLOG/SEO RULES:
- Lead with target keyword naturally in first sentence and H1
- Human first, search engine second
- 500 words for blog posts
- Always end with a natural CTA
- Storytelling structure: real moment to tension to shift to reason to care to gentle CTA
""".strip()


WRITING_RULES = """
WRITING RULES, apply to every piece of content without exception:

PUNCTUATION:
Never use em dashes or en dashes. Use a comma, full stop, or rewrite the sentence instead.
No ellipsis for dramatic effect (...). Only where a trailing thought genuinely needs it, and even then sparingly.
No semicolons.
Exclamation marks: maximum one per piece of content. Earned, not scattered.
No brackets for asides. Rewrite as a natural part of the sentence.

SENTENCE STRUCTURE:
Vary sentence length constantly. Short sentences land harder. Longer ones give context and rhythm and feel more like someone actually talking.
Never start three consecutive sentences with the same word.
Avoid starting sentences with 'It is', 'There are', 'This is'. These are filler openings that add nothing.
No rhetorical questions as filler (e.g. 'Sound familiar?', 'Want to know more?'). Only use a question if it genuinely adds something.
Contractions always. It's not 'it is'. It's not 'you are'. Write how people actually speak.

WORD CHOICE:
Never use: elevated, curated, intentional, journey, seamless, effortless, nestled, delve, game-changer, leverage, cutting-edge, innovative, perfect, simply, just, very, really, amazing, incredible, stunning, beautiful, ensure.
Never use corporate filler: 'at the end of the day', 'in terms of', 'moving forward', 'it goes without saying', 'needless to say'.
Never use ChatGPT giveaway phrases: 'in a world where', 'picture this', 'imagine a', "it's no secret that", 'the truth is', "let's be honest", 'look no further'.
Use the word a normal person would use in conversation, not the fancier version.

STRUCTURE:
No bullet points in blog copy or captions. Work information into natural sentences instead.
No bold text for emphasis mid-paragraph.
Paragraphs: maximum 3 sentences for captions and emails, 4 for blogs.
Never summarise what you just said at the end of a section. Say it once, say it well, move on.

TONE:
Write like Holly is WhatsApping her mate, not presenting to a boardroom.
Self-deprecating is good. Overly earnest is not.
If a joke does not land naturally, cut it. Forced humour reads as AI immediately.
UK spelling always: personalised, colour, favourite.
Read every sentence back as if saying it out loud. If it sounds like something a human would never actually say, rewrite it.

FINAL CHECK, before outputting any content, scan for:
Any em dash or en dash: replace immediately.
Any banned word from the list above: replace immediately.
Any sentence starting with a filler opening (It is / There are / This is): rewrite immediately.
Any bullet point in blog or caption copy: convert to prose immediately.
Any exclamation mark beyond the first in a piece: remove immediately.
If the content could have been written by ChatGPT, rewrite it until it could not.
""".strip()


BLOG_SEO_PASS_SYSTEM = """
You are an SEO specialist working exclusively for Rock On Ruby, a personalised print-on-demand clothing and accessories brand based in Bury, Manchester.
Your job is to take a blog draft written in Holly's voice and optimise it fully for Google search and AI Overviews without losing the brand tone.

Holly's voice is chatty, warm, self-deprecating, UK humour, conversational, never salesy and never corporate.

Apply all of the following to every blog:

STRUCTURE:
- Keep the existing conversational opening. Do not make it formal.
- Break the body into sections using H2 subheadings phrased as questions buyers actually search. Derive these from the actual topic and trend data, not generic templates.
- Add H3 subheadings within longer sections where needed.
- Aim for 600 to 800 words minimum.
- Include the specific year in the title and first paragraph when the topic is time sensitive.
- Include specific dates for seasonal moments where relevant.

KEYWORDS:
- Expand all product mentions into long-tail keyword phrases specific to the blog topic.
- Never use generic one-word product names when a more specific phrase fits.
- Combine product phrases with the occasion, audience or use case relevant to this exact blog.
- Derive keyword phrases from the actual trend data and blog topic. Never reuse phrases from another blog.

LOCAL SEO:
- Mention Bury, Manchester naturally at least once.
- Mention UK-wide shipping or delivered across the UK at least once.
- Reference fast turnaround for late shoppers where relevant to the topic.

BUYER PERSONAS:
- Include at least one specific buyer scenario relevant to the actual blog topic.
- Derive personas from who would genuinely search for this topic.
- Never copy personas from an unrelated blog.

DEPTH:
- Give specific examples of personalisation ideas relevant to the blog topic, such as nicknames, in-jokes, birth years, catchphrases or inside references.
- Explain why personalised beats generic using the emotional argument, not only product features.
- Reference the quality of Rock On Ruby DTF full-colour print or embroidery versus cheap alternatives at least once. Choose the method that fits the product and do not imply every product is embroidered.
- Expand product descriptions to be specific and detailed.

FAQ SECTION:
- Add a fully written FAQ section at the bottom with at least 4 questions.
- Questions must come from the actual trend data, People Also Ask results and the specific blog topic.
- Phrase every question exactly as someone would type it into Google or ask ChatGPT.
- Include occasion date questions only when the blog is genuinely time sensitive.
- Every answer must be fully written in Holly's voice.
- No placeholders, no notes and no draft-your-answer-here wording.

CTA:
- End with a natural, low-pressure call to action pointing to rockonruby.co.uk.
- Keep it in Holly's voice. Never use corporate calls to action like shop now or click here.

OUTPUT:
- Return only the finished blog post.
- Mark all headings clearly as H1, H2 or H3.
- Do not add commentary, notes or explanations outside the blog content.
""".strip()


# ── History tracking ──────────────────────────────────────────────────────────

def load_history() -> dict:
    if HISTORY_FILE.exists():
        try:
            return json.loads(HISTORY_FILE.read_text())
        except Exception:
            pass
    return {"generated": []}


def save_history(history: dict, new_terms: list[str], content_types: list[str]) -> None:
    today = datetime.now().strftime("%Y-%m-%d")
    for term in new_terms:
        history["generated"].append({
            "date":          today,
            "keyword":       term,
            "content_types": content_types,
        })
    # Keep only last 60 days
    cutoff = (datetime.now() - timedelta(days=60)).strftime("%Y-%m-%d")
    history["generated"] = [e for e in history["generated"] if e["date"] >= cutoff]
    HISTORY_FILE.write_text(json.dumps(history, indent=2))


def recently_used(term: str, history: dict, days: int = 14) -> bool:
    cutoff = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d")
    return any(
        e["keyword"] == term and e["date"] >= cutoff
        for e in history["generated"]
    )


# ── Term selection ────────────────────────────────────────────────────────────

def load_cached_trend_data() -> tuple[list[dict], dict]:
    if not CACHE_FILE.exists():
        raise FileNotFoundError("trend_cache.json not found, run scraper first.")
    raw = json.loads(CACHE_FILE.read_text())
    if isinstance(raw, dict) and "groups" in raw:
        return raw["groups"], raw.get("trending", {})
    return raw, {}


def load_json_file(path: Path, fallback):
    if path.exists():
        try:
            return json.loads(path.read_text())
        except Exception:
            pass
    return fallback


def all_results(all_groups: list[dict]) -> list[dict]:
    return [r for g in all_groups for r in g.get("results", [])]


def find_cached_term(all_groups: list[dict], keyword: str) -> dict | None:
    wanted = keyword.strip().lower()
    if not wanted:
        return None
    for r in all_results(all_groups):
        term = r.get("term", "").strip().lower()
        if term == wanted:
            return r
    for r in all_results(all_groups):
        term = r.get("term", "").strip().lower()
        if wanted in term or term in wanted:
            return r
    return None


def find_rank_term(keyword: str) -> dict | None:
    wanted = keyword.strip().lower()
    cache = load_json_file(RANK_CACHE_FILE, {})
    for row in cache.get("results", []):
        query = row.get("query", "").strip()
        if not query:
            continue
        q_lower = query.lower()
        if q_lower != wanted and wanted not in q_lower and q_lower not in wanted:
            continue
        rank = row.get("ror_rank")
        priority = row.get("priority_score", 6)
        return {
            "term": query,
            "avg_interest": min(int(row.get("gsc_impressions", 0) or 0), 100),
            "peak_interest": min(int(row.get("gsc_impressions", 0) or 0), 100),
            "trend": "stable",
            "rising_queries": [],
            "top_queries": [],
            "breakout_queries": [],
            "paa": [],
            "ror_existing": row.get("target_page") or row.get("ror_url") or "",
            "suggestions": [
                f"Live Google UK rank: #{rank}" if rank is not None else "Live Google UK rank: not top 20",
                f"Search Console impressions: {row.get('gsc_impressions', 0)}",
                f"Priority score: {priority}",
            ],
            "score": 8 if priority >= 70 else 6,
            "seo_action": "Generate finished page copy, FAQ and supporting content from rank evidence",
            "layer": 98,
            "data_source": "search-console-rank",
        }
    return None

def pick_terms_by_layer(all_groups: list[dict], history: dict) -> dict[int, list[dict]]:
    """
    Returns {layer: [result, ...]} with fresh terms per layer.
    Layer 4 gets 3 slots; all others get 2.
    High-scoring (>=8) terms may repeat even if recently used.
    """
    by_layer: dict[int, list[dict]] = {}
    for g in all_groups:
        layer = g.get("layer", 3)
        for r in g["results"]:
            by_layer.setdefault(layer, []).append(r)

    selected: dict[int, list[dict]] = {}
    for layer, results in by_layer.items():
        slots = 3 if layer == 4 else 2
        # Sort: high score first, rising trend preferred
        ranked = sorted(
            results,
            key=lambda r: (-r["score"], -(1 if r["trend"] == "rising" else 0), -r["avg_interest"])
        )
        # Pick fresh terms first; allow repeats only if score >= 8
        chosen = []
        for r in ranked:
            if len(chosen) >= slots:
                break
            if not recently_used(r["term"], history) or r["score"] >= 8:
                chosen.append(r)
        # If not enough fresh terms, fill with highest scorers regardless
        if len(chosen) < slots:
            for r in ranked:
                if r not in chosen:
                    chosen.append(r)
                if len(chosen) >= slots:
                    break
        selected[layer] = chosen[:slots]

    return selected


def pick_seo_terms(all_groups: list[dict], history: dict, cap: int = 10) -> list[dict]:
    """
    Returns terms flagged for SEO content creation (blog/product/collection),
    filtered by history, capped at `cap` total.
    """
    seo_actions = {"write blog", "create new product", "update collection"}
    results = []
    for g in all_groups:
        for r in g["results"]:
            action = r.get("seo_action", "").lower()
            if any(a in action for a in seo_actions):
                if not recently_used(r["term"], history, days=21) or r["score"] >= 8:
                    results.append(r)
    ranked = sorted(results, key=lambda r: (-r["score"], -r["avg_interest"]))
    return ranked[:cap]


def pick_blog_terms(layer_terms: dict[int, list[dict]], seo_terms: list[dict], cap: int = 2) -> list[dict]:
    """Pick the source blog topics. These become the assets email/social content derives from."""
    picked: list[dict] = []
    seen: set[str] = set()
    for r in seo_terms:
        if "blog" in r.get("seo_action", "").lower() and r["term"] not in seen:
            picked.append(r)
            seen.add(r["term"])
        if len(picked) >= cap:
            return picked
    candidates = (
        [r for r in layer_terms.get(4, [])]
        + [r for layer, rs in layer_terms.items() if layer != 4 for r in rs]
    )
    for r in sorted(candidates, key=lambda item: (-item.get("score", 0), -item.get("avg_interest", 0))):
        if r["term"] not in seen:
            picked.append(r)
            seen.add(r["term"])
        if len(picked) >= cap:
            break
    return picked


def claude_text(client: anthropic.Anthropic, system: str, prompt: str, max_tokens: int = 4096) -> str:
    message = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=max_tokens,
        system=system,
        messages=[{"role": "user", "content": prompt}],
    )
    return message.content[0].text.strip()


def blog_evidence_block(r: dict, all_groups: list[dict], catalogue: dict, trending_data: dict | None) -> str:
    existing = r.get("ror_existing", "")
    url = find_catalogue_url(existing, catalogue)
    related = ", ".join(r.get("rising_queries", [])[:6]) or "none captured"
    top = ", ".join(r.get("top_queries", [])[:6]) or "none captured"
    paa = "\n".join(f"- {q}" for q in r.get("paa", [])[:8]) or "none captured"
    products = []
    words = {w for w in normalise_text(r["term"]).split() if len(w) > 3}
    for product in catalogue.get("products", []):
        title = product.get("title", "")
        if any(w in normalise_text(title) for w in words):
            products.append(f"- {title} to {product.get('url', 'rockonruby.co.uk')}")
        if len(products) >= 6:
            break
    product_lines = "\n".join(products) or "No exact product matches found. Use the mapped page and bestsellers cautiously."
    open_trends = "none captured"
    if trending_data:
        web = trending_data.get("web", {})
        yt = trending_data.get("youtube", {})
        captured = web.get("top", []) + web.get("rising", []) + yt.get("top", []) + yt.get("rising", [])
        if captured:
            open_trends = ", ".join(captured[:10])
    return f"""
BLOG TOPIC EVIDENCE:
Primary keyword: {r['term']}
Mapped ROR page/product: {existing or 'needs page mapping'}
Mapped URL: {url}
Trend score: {r.get('score', 0)}/10
Search interest estimate: {r.get('avg_interest', 0)}/100
Trend direction: {r.get('trend', 'unknown')}
Related rising queries: {related}
Top related queries: {top}
People Also Ask:
{paa}

Relevant products or URLs:
{product_lines}

Open UK trend inspiration:
{open_trends}
""".strip()


def generate_two_pass_blogs(
    client: anthropic.Anthropic,
    blog_terms: list[dict],
    all_groups: list[dict],
    catalogue: dict,
    trending_data: dict | None,
) -> dict[str, str]:
    finished: dict[str, str] = {}
    design_rules = DESIGN_RULES_FILE.read_text(encoding="utf-8") if DESIGN_RULES_FILE.exists() else ""
    pass1_system = (
        "You are writing rough first-draft blog copy for Rock On Ruby in Holly's voice. "
        "Write chatty, warm, self-deprecating UK copy with short paragraphs. Never sound corporate, formal or salesy.\n\n"
        f"{WRITING_RULES}\n\n{design_rules}"
    )
    pass2_system = f"{BLOG_SEO_PASS_SYSTEM}\n\n{WRITING_RULES}\n\n{design_rules}"

    for r in blog_terms:
        evidence = blog_evidence_block(r, all_groups, catalogue, trending_data)
        print(f"  Blog pass 1: {r['term']}")
        rough_prompt = f"""
Create Pass 1, a rough conversational blog draft in Holly's voice using this evidence.

Do not optimise heavily yet. Focus on making it sound like Holly: chatty, warm, self-deprecating, UK humour, short paragraphs, never corporate and never salesy.

{evidence}
""".strip()
        rough = claude_text(client, pass1_system, rough_prompt, max_tokens=4096)

        print(f"  Blog pass 2 SEO: {r['term']}")
        seo_prompt = f"""
Take this Pass 1 blog draft and optimise it fully using the system instructions.

Use the evidence below to create search-specific H2/H3 headings, long-tail keyword phrases, buyer personas, local SEO, product detail, FAQ questions and a natural CTA.

IMPORTANT: Save only the finished Pass 2 blog. Discard Pass 1.

{evidence}

PASS 1 DRAFT:
{rough}
""".strip()
        finished[r["term"]] = claude_text(client, pass2_system, seo_prompt, max_tokens=8192)
    return finished


# ── Blog generation from approved outlines ────────────────────────────────────

def load_approved_outlines() -> list[dict]:
    """
    Read ror_content_draft.md and extract blog outlines from approved packs.
    A pack is approved if it contains '### Approved ClickUp Task Breakdown'.
    Returns a list of dicts with term + outline data.
    """
    if not CONTENT_FILE.exists():
        print("ror_content_draft.md not found. Run --no-ai first.")
        return []

    md = CONTENT_FILE.read_text(encoding="utf-8")
    approved = []

    for pack_match in re.finditer(
        r"^## (?!System Focus|Trend Note|How this works|Design Rules)([^\n]+)\n+(.*?)(?=\n^## |\Z)",
        md, re.DOTALL | re.MULTILINE
    ):
        keyword = pack_match.group(1).strip()
        body = pack_match.group(2).strip()

        # Only process approved packs
        if "### Approved ClickUp Task Breakdown" not in body:
            continue

        # Extract the blog outline block
        outline_match = re.search(
            r"### Blog Outline.*?\n+(.*?)(?=\n### |\Z)",
            body, re.DOTALL
        )
        outline_text = outline_match.group(1).strip() if outline_match else ""

        # Extract H1
        h1_match = re.search(r"\*\*H1:\*\*\s*(.+)", outline_text)
        h1 = h1_match.group(1).strip() if h1_match else keyword.title()

        # Extract H2s
        h2s = re.findall(r"- H2:\s*(.+)", outline_text)

        # Extract FAQ questions
        faq_section = re.search(
            r"\*\*FAQ section questions:\*\*\n+(.*?)(?=\n\*\*|\Z)",
            outline_text, re.DOTALL
        )
        faq_questions = []
        if faq_section:
            faq_questions = [
                line.lstrip("- ").strip()
                for line in faq_section.group(1).strip().splitlines()
                if line.strip().startswith("-")
            ]

        # Extract story beats
        before_match = re.search(r"- Before.*?:\s*(.+)", outline_text)
        tension_match = re.search(r"- Tension.*?:\s*(.+)", outline_text)
        shift_match = re.search(r"- Shift.*?:\s*(.+)", outline_text)
        care_match = re.search(r"- Reason to care:\s*(.+)", outline_text)
        cta_match = re.search(r"\*\*CTA:\*\*\s*(.+?)→\s*(.+)", outline_text)
        url_match = re.search(r"\*\*CTA:\*\*.*?→\s*(.+)", outline_text)

        approved.append({
            "term": keyword,
            "h1": h1,
            "h2s": h2s[:3],
            "faq_questions": faq_questions[:5],
            "before": before_match.group(1).strip() if before_match else "",
            "tension": tension_match.group(1).strip() if tension_match else "",
            "shift": shift_match.group(1).strip() if shift_match else "",
            "care": care_match.group(1).strip() if care_match else "",
            "cta_url": url_match.group(1).strip() if url_match else "rockonruby.co.uk",
            "outline_text": outline_text,
            "body": body,
        })

    return approved


def update_pack_with_blog(md: str, keyword: str, finished_blog: str) -> str:
    """
    Replace the blog outline section in a content pack with the finished
    two-pass blog, and update the blog subtask description in the
    Approved ClickUp Task Breakdown to contain the finished blog.
    Returns the updated markdown string.
    """
    # Replace the blog outline block with the finished blog
    def replace_outline(match):
        pre = match.group(1)
        return f"{pre}\n### Blog (Finished — Two-Pass SEO)\n\n{finished_blog}\n"

    md = re.sub(
        r"(## " + re.escape(keyword) + r".*?### Blog Outline.*?\n)(.+?)(?=\n### Content Execution Pack)",
        replace_outline,
        md,
        flags=re.DOTALL
    )

    # Update the blog subtask in the ClickUp breakdown
    def replace_blog_subtask(match):
        block = match.group(0)
        # Find the blog task summary and replace it
        block = re.sub(
            r"(\*\*Task name:\*\* Blog: " + re.escape(keyword) + r".*?\*\*Task summary:\*\*\s*)(.+?)(?=\n\n\*\*Task name:\*\*|\Z)",
            lambda m: m.group(1) + "Finished blog below. Copy this directly into Shopify as a new blog post. Check the H1, H2s and FAQ are intact before publishing.\n\n" + finished_blog,
            block,
            flags=re.DOTALL
        )
        return block

    md = re.sub(
        r"### Approved ClickUp Task Breakdown.+?(?=\n---|\Z)",
        replace_blog_subtask,
        md,
        flags=re.DOTALL
    )

    return md


def run_generate_blogs() -> int:
    """
    Main handler for --generate-blogs flag.

    Flow:
    1. Read approved outlines from ror_content_draft.md
    2. Load trend cache to build evidence blocks for each term
    3. Run two-pass blog generation (Pass 1: Holly voice, Pass 2: SEO)
    4. Update ror_content_draft.md — replace outlines with finished blogs
    5. Update ClickUp blog subtask descriptions with finished blog content
    6. Save updated ror_content_draft.md

    Token cost: 2 Claude API calls per approved pack (Pass 1 + Pass 2).
    """
    api_key = os.environ.get("ANTHROPIC_API_KEY", "")
    if not api_key:
        print("ANTHROPIC_API_KEY not set — cannot generate blogs.")
        print("Set it with: export ANTHROPIC_API_KEY=your_key")
        return 1

    approved = load_approved_outlines()
    if not approved:
        print("No approved packs found in ror_content_draft.md.")
        print("Run --no-ai first, check the output, then run --generate-blogs.")
        return 0

    print(f"\n-- Blog Generation --")
    print(f"Approved packs: {len(approved)}")
    print(f"API calls needed: {len(approved) * 2} (Pass 1 + Pass 2 per pack)")

    # Load trend cache for evidence blocks
    try:
        all_groups, trending_data = load_cached_trend_data()
    except FileNotFoundError:
        all_groups, trending_data = [], {}
        print("trend_cache.json not found — blogs will use outline data only.")

    catalogue = load_json_file(CATALOGUE_FILE, {})

    client = anthropic.Anthropic(api_key=api_key)

    # Build result dicts that generate_two_pass_blogs() expects
    term_results = []
    for outline in approved:
        # Try to find the full cached result for this term
        cached = find_cached_term(all_groups, outline["term"])
        if cached:
            term_results.append(cached)
        else:
            # Build a minimal result dict from the outline
            term_results.append({
                "term": outline["term"],
                "avg_interest": 35,
                "peak_interest": 35,
                "trend": "rising",
                "rising_queries": [],
                "top_queries": [],
                "breakout_queries": [],
                "paa": outline.get("faq_questions", []),
                "ror_existing": outline.get("cta_url", "").replace("rockonruby.co.uk", "").strip("/") or "",
                "suggestions": [],
                "score": 7,
                "seo_action": "write blog post",
                "layer": 4,
                "data_source": "outline",
            })

    # Run two-pass blog generation
    print("\nGenerating blogs...")
    finished_blogs = generate_two_pass_blogs(
        client, term_results, all_groups, catalogue, trending_data
    )

    if not finished_blogs:
        print("No blogs generated — check API key and network.")
        return 1

    # Update ror_content_draft.md with finished blogs
    md = CONTENT_FILE.read_text(encoding="utf-8")

    for term, blog in finished_blogs.items():
        print(f" Updating pack: {term}")
        md = update_pack_with_blog(md, term, blog)

    # Add a header note so it's clear blogs have been generated
    timestamp = datetime.now().strftime("%d %B %Y, %H:%M")
    md = md.replace(
        "# Rock On Ruby — Content Packs",
        f"# Rock On Ruby — Content Packs\n\n> Blogs generated: {timestamp}"
    )

    CONTENT_FILE.write_text(md, encoding="utf-8")
    print(f"\nUpdated: {CONTENT_FILE}")
    print(f"Blogs generated: {len(finished_blogs)}")
    print(f"\nNext step: review ror_content_draft.md then run:")
    print(f"  python3 clickup_tasks.py")

    return 0


# ── No-AI visibility and content packs ────────────────────────────────────────

def normalise_text(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", value.lower()).strip()


def find_catalogue_url(label: str, catalogue: dict) -> str:
    if not label:
        return "rockonruby.co.uk"
    label_norm = normalise_text(label)
    for collection in catalogue.get("collections", []):
        if normalise_text(collection.get("title", "")) == label_norm:
            return collection.get("url", "rockonruby.co.uk")
    for product in catalogue.get("products", []):
        title_norm = normalise_text(product.get("title", ""))
        if label_norm and (label_norm in title_norm or title_norm in label_norm):
            return product.get("url", "rockonruby.co.uk")
    return "rockonruby.co.uk"


def page_mapping_note(term: str, existing: str) -> str:
    term_l = term.lower()
    existing_l = existing.lower()
    if not existing:
        return "No mapped page yet. Create or choose the correct target before assigning this task."
    weak = False
    reasons = []
    if "birthday" in term_l and "christmas" in existing_l:
        weak = True
        reasons.append("birthday search mapped to a Christmas page")
    if "hoodie" in term_l and "slogan" in existing_l:
        weak = True
        reasons.append("hoodie search mapped to a broad slogan page")
    if "year" in term_l and "accessories" in existing_l:
        weak = True
        reasons.append("year clothing search mapped to accessories")
    if weak:
        return "Needs review: current inferred mapping may be wrong because " + ", ".join(reasons) + "."
    return "Current inferred mapping looks usable, but ranking data is not connected yet."


def score_explanation(score: int) -> str:
    if score >= 8:
        return f"{score}/10, Green, strong opportunity. Prioritise this if the page mapping is correct."
    if score >= 5:
        return f"{score}/10, Amber, useful opportunity. Worth action when it connects to an existing product, page or seasonal moment."
    return f"{score}/10, Grey, low priority. Monitor unless it supports a high-value page or product."


def interest_explanation(interest: int) -> str:
    if interest >= 70:
        return f"{interest}/100, Green, high search interest."
    if interest >= 30:
        return f"{interest}/100, Amber, moderate search interest. Useful for product/page optimisation."
    if interest > 0:
        return f"{interest}/100, Grey, low search interest. Use only if commercially useful."
    return "0/100, no reliable live interest captured."


def trend_explanation(trend: str) -> str:
    if trend == "rising":
        return "Rising, Green, interest is increasing compared with the earlier part of the tracking window."
    if trend == "falling":
        return "Falling, Red, interest is dropping compared with the earlier part of the tracking window."
    return "Stable, Grey, no clear increase or drop detected."


def shopper_phrase(term: str) -> str:
    words = term.lower()
    replacements = {
        " uk": "",
        "custom ": "a custom ",
        "personalised ": "a personalised ",
    }
    phrase = words
    for old, new in replacements.items():
        phrase = phrase.replace(old, new)
    if not phrase.startswith(("a ", "an ")):
        phrase = "a " + phrase
    return phrase


def design_direction_for_term(term: str) -> dict:
    text = term.lower()
    if any(w in text for w in ["father", "dad", "bbq", "grill"]):
        return {
            "moment": "Father's Day",
            "palette": "beige, black, navy, army green, orange and dark teal",
            "type": "Prohibition or Futura Condensed for badge energy, Sharp Grotesk for supporting copy",
            "feel": "practical, bold, giftable and dry-funny",
            "avoid": "pink-heavy styling, soft florals, sentimental stock-photo cues and tiny unreadable product shots",
        }
    if any(w in text for w in ["christmas", "stocking", "festive"]):
        return {
            "moment": "Christmas",
            "palette": "cream, black, bright red, dark red, forest green, army green and gold",
            "type": "Druk or Sharp Grotesk for gift-guide headers, Cooper Black for warmer nostalgic moments",
            "feel": "shoppable, warm, clear and gift-guide friendly",
            "avoid": "busy layouts where product names, prices or personalisation details get lost",
        }
    if any(w in text for w in ["festival", "glastonbury", "reading", "summer", "holiday"]):
        return {
            "moment": "Festival and summer",
            "palette": "beige, black, bright orange, bright blue, pink, bright yellow and teal",
            "type": "Druk for loud hooks, Sharp Grotesk for product and CTA copy",
            "feel": "loud, fun, useful and a bit chaotic in a controlled way",
            "avoid": "blurry mood shots where the product cannot be inspected",
        }
    if any(w in text for w in ["birthday", "year", "40th", "30th", "50th", "21st", "18th"]):
        return {
            "moment": "Birthday and milestone gifting",
            "palette": "beige, black, bright red, pink, navy, burgundy and gold",
            "type": "Old English or varsity-inspired type for year moments, Sharp Grotesk for clear gift copy",
            "feel": "personal, celebratory, clear and gift-ready",
            "avoid": "childish birthday styling or copy that feels too generic",
        }
    if any(w in text for w in ["mother", "mum"]):
        return {
            "moment": "Mother's Day and gifts for mum",
            "palette": "beige, cream, black, pink, bright red, baby pink and butter",
            "type": "Sharp Grotesk for clarity, Cooper Black for warmer retro moments",
            "feel": "warm, thoughtful, personal and not twee",
            "avoid": "overly soft greetings-card styling",
        }
    return {
        "moment": "Evergreen ROR gifting",
        "palette": "beige, black, pink, bright red and one product-led accent colour",
        "type": "Sharp Grotesk for clear shopping information, Druk for big hooks",
        "feel": "bold, useful, anti-boring and easy to shop",
        "avoid": "generic lifestyle styling, corporate minimalism and hard-to-read product shots",
    }


def exact_visibility_action(term: str, existing: str, seo_action: str) -> dict:
    term_l = term.lower()
    existing_label = existing or "No matching ROR page found"
    if not existing:
        return {
            "problem": "ROR does not have a clearly mapped page for this search.",
            "do_this": "Create a supporting blog first, then decide whether it deserves a collection, product page or seasonal landing section.",
            "copy_focus": f"The first section should explain why {term} matters to an ROR customer, then point to the closest product or collection.",
            "links": "Link to the closest product collection, bestselling personalised products and any seasonal gift page that fits.",
        }
    if "birthday" in term_l or "year" in term_l or any(n in term_l for n in ["18th", "21st", "30th", "40th", "50th"]):
        return {
            "problem": f"The mapped page is likely too broad. It needs to make birthday and milestone gift intent obvious for '{term}'.",
            "do_this": "Rewrite the first 80 words around birthday gifting. Mention personalised birthday sweatshirts, milestone birthdays, birth years, 18th, 21st, 30th, 40th and 50th gifts where relevant, gift-ready wording and UK delivery.",
            "copy_focus": "Open with the gift moment, then explain the personalisation choice, then show why it feels more thoughtful than a generic present.",
            "links": "Add links from birthday blogs, personalised gifts, gifts for her, gifts for mum and relevant milestone gift posts to this page.",
        }
    if "father" in term_l or "dad" in term_l or "bbq" in term_l:
        return {
            "problem": f"The mapped page needs a clearer Father's Day or dad-gifting angle for '{term}'.",
            "do_this": "Add a short dad-gifting intro, a FAQ about delivery and personalisation, and a product row that makes bundles obvious.",
            "copy_focus": "Use practical gift language. Mention caps, sweatshirts, BBQ humour, last-minute gifting and add-on products where they fit.",
            "links": "Add links from Father's Day gift guide, BBQ/festival content and best-selling cap pages.",
        }
    if "festival" in term_l or "glastonbury" in term_l or "summer" in term_l:
        return {
            "problem": f"The mapped page needs to connect the product to summer or festival use, not just generic clothing.",
            "do_this": "Add a seasonal content block that frames caps, totes or sweatshirts as useful for packing, groups, outfits or gifting.",
            "copy_focus": "Talk about what the product does in the real moment: packing, wearing, gifting, matching or surviving a chaotic day out.",
            "links": "Add links from summer, festival, travel and personalised accessory content to the target page.",
        }
    return {
        "problem": f"The page may not be clearly answering the search intent for '{term}'.",
        "do_this": f"Update the intro, one FAQ and internal links so the page uses '{term}' naturally and gives shoppers a clearer reason to buy.",
        "copy_focus": "Start with the customer need, mention the product type, explain personalisation or gift value, then link to the best matching products.",
        "links": "Add internal links from related blogs, gift collections and product pages that already get traffic.",
    }


def suggested_intro_draft(term: str, existing: str) -> str:
    term_l = term.lower()
    product = existing if existing and "christmas" not in existing.lower() else "The right ROR product or collection"
    phrase = shopper_phrase(term)
    if "birthday" in term_l or "year" in term_l or any(n in term_l for n in ["18th", "21st", "30th", "40th", "50th"]):
        return (
            f"Looking for {phrase} that feels more thoughtful than another panic-bought candle? "
            f"{product} is made for milestone birthdays, birth-year gifts and people who say they don't want a fuss, "
            "then absolutely do. Choose the colour, add the personalisation and make it feel like it was made for them, because it was."
        )
    if "father" in term_l or "dad" in term_l or "bbq" in term_l:
        return (
            f"If you're searching for {phrase}, start with something he might actually wear. "
            f"{product} gives Father's Day gifting a bit more personality without making it too sentimental. "
            "Add a cap, sweatshirt or personalised extra to build a gift that feels useful, funny and not like a last-minute garage run."
        )
    if "festival" in term_l or "glastonbury" in term_l or "summer" in term_l:
        return (
            f"{term} searches are really about finding something useful, wearable and a bit more fun than the usual panic packing. "
            f"{product} can support that with personalised caps, totes or layers that work for groups, travel days and festival photos. "
            "Keep the product easy to shop and show the personalisation clearly."
        )
    return (
        f"If someone lands here after searching for {term}, the page needs to show them why {product} is the right ROR answer. "
        "Start with the real buying moment, explain the personalisation or gift value, then make the next step obvious with a clear product link."
    )


def production_method_note(term: str, existing: str) -> str:
    text = f"{term} {existing}".lower()
    if any(word in text for word in ["cap", "embroidered", "embroidery"]):
        return "Likely embroidery if the target product is a cap or embroidered product. Check the exact product before mentioning embroidery."
    if any(word in text for word in ["sweatshirt", "hoodie", "t-shirt", "tee", "jumper", "tote", "bag"]):
        return "Likely DTF full-colour print for many clothing or accessory products, unless the exact product is listed as embroidered. Say full-colour print for customers rather than DTF jargon."
    return "Check the exact product production method before mentioning print or embroidery. ROR uses both DTF full-colour print and embroidery."


# ── Blog outline builder (no AI, derived from keyword + PAA data) ─────────────

def build_blog_outline(r: dict) -> dict:
    """
    Build a structured blog outline from keyword + PAA data.
    This becomes the source of truth for all derivative formats.
    No Claude tokens used — pure data derivation.
    """
    term = r["term"]
    term_display = term.title()
    existing = r.get("ror_existing", "")
    paa = r.get("paa", [])
    rising = r.get("rising_queries", [])
    trend = r.get("trend", "stable")
    score = r.get("score", 5)

    # ── H1 ───────────────────────────────────────────────────────────────────
    h1 = f"{term_display}: The Gift That Actually Feels Personal"
    if any(w in term.lower() for w in ["father", "dad"]):
        h1 = f"The Best {term_display} Ideas That Aren't Another Bottle of Wine"
    elif any(w in term.lower() for w in ["festival", "glastonbury", "summer"]):
        h1 = f"{term_display}: What to Wear, Pack and Gift This Season"
    elif any(w in term.lower() for w in ["birthday", "year", "40th", "30th", "50th", "21st", "18th"]):
        h1 = f"{term_display} Ideas That Feel More Thoughtful Than a Last-Minute Panic Buy"
    elif any(w in term.lower() for w in ["christmas", "festive"]):
        h1 = f"{term_display} That People Actually Want to Wear"
    elif "slogan" in term.lower() or "sweatshirt" in term.lower():
        h1 = f"The {term_display} Edit: Funny, Personal and Anything But Boring"

    # ── Story structure ───────────────────────────────────────────────────────
    # Before: the problem/situation the reader is in
    before_map = {
        "father": "You've left it later than you meant to and 'something nice' is doing a lot of heavy lifting right now.",
        "dad": "You've left it later than you meant to and 'something nice' is doing a lot of heavy lifting right now.",
        "festival": "You've got a ticket, a vague plan and absolutely no idea what to actually pack.",
        "glastonbury": "The lineup is sorted. The tent is borrowed. The outfit situation is still very much not sorted.",
        "birthday": "Another birthday, another scented candle they'll use once and forget about.",
        "year": "Finding a gift tied to a birth year that isn't a mug or a keyring is harder than it sounds.",
        "christmas": "You want something that feels thoughtful but you've got about forty people to sort out.",
        "slogan": "The high street version looks exactly like everyone else's. That's not really the point.",
        "sweatshirt": "A good sweatshirt should say something. Most of them say nothing.",
        "personalised": "Personalised doesn't have to mean a name slapped on a generic product.",
    }
    before = next(
        (v for k, v in before_map.items() if k in term.lower()),
        f"Finding a {term} that doesn't look like it came from a conveyor belt is harder than it should be."
    )

    # Tension: the friction moment
    tension_map = {
        "father": "Father's Day is one of those occasions where 'practical' and 'thoughtful' feel like opposites.",
        "festival": "Festival packing is genuinely stressful. The wrong bag ruins the whole thing.",
        "birthday": "Milestone birthdays feel like they deserve something more considered than a candle and a card.",
        "christmas": "The pressure to get it right is real, and the options on the high street don't help.",
        "slogan": "The ones that are actually funny are impossible to find. The rest are just... beige.",
        "personalised": "Most personalised gifts feel like an afterthought. The personalisation is the point, but it rarely is.",
    }
    tension = next(
        (v for k, v in tension_map.items() if k in term.lower()),
        f"The problem is most {term} options look fine but feel forgettable."
    )

    # Shift: the turn
    shift = (
        f"Rock On Ruby makes {term.lower()} that start with the personalisation, "
        "not as a label stuck on at the end."
    )

    # Reason to care: emotional hook
    care = (
        "Because the right gift says 'I actually thought about you', "
        "and that feeling is worth more than any price point."
    )

    # ── H2s from PAA + rising queries ─────────────────────────────────────────
    h2_sources = paa[:3] + [q for q in rising[:4] if q not in paa]
    h2s = []

    for q in h2_sources[:3]:
        # Clean PAA questions into proper H2 phrasing
        q_clean = q.strip().rstrip("?")
        if not q_clean:
            continue
        # Capitalise naturally
        h2s.append(q_clean[0].upper() + q_clean[1:] + "?")

    # Fallback H2s if PAA/rising is empty
    if len(h2s) < 3:
        fallbacks = [
            f"What makes a good {term.lower()} gift?",
            f"How do you personalise a {term.lower().replace(' uk', '')}?",
            f"Where can you get a {term.lower().replace(' uk', '')} made in the UK?",
            f"How quickly can Rock On Ruby make a {term.lower().replace(' uk', '')}?",
        ]
        for fb in fallbacks:
            if fb not in h2s:
                h2s.append(fb)
            if len(h2s) >= 3:
                break

    # ── FAQ questions ─────────────────────────────────────────────────────────
    faq_questions = paa[:5] if paa else [
        f"How long does delivery take for a personalised {term.lower().replace(' uk', '')}?",
        f"Can I choose the colour for a {term.lower().replace(' uk', '')}?",
        f"Do you ship {term.lower().replace(' uk', '')} across the UK?",
        f"What personalisation options do you offer?",
        f"Is Rock On Ruby based in the UK?",
    ]

    # ── CTA ───────────────────────────────────────────────────────────────────
    cta_url = f"rockonruby.co.uk" if not existing else \
        (existing if existing.startswith("http") else f"rockonruby.co.uk")
    cta_text = f"Shop {term_display.replace(' Uk', '').strip()} at Rock On Ruby"

    # ── Social hook (first line of reel/caption) ──────────────────────────────
    hook_map = {
        "father": f"If your dad says he doesn't want anything, he's lying.",
        "festival": f"Your festival outfit is sorted. Your feet are not. Let's fix that.",
        "birthday": f"Another year. Another chance to get it right this time.",
        "christmas": f"It's not too late. But it will be.",
        "slogan": f"The slogan you actually want on a sweatshirt doesn't exist yet. Until now.",
        "personalised": f"Personalised gifts are either brilliant or embarrassing. No in-between.",
    }
    social_hook = next(
        (v for k, v in hook_map.items() if k in term.lower()),
        f"You've been searching for a {term.lower().replace(' uk', '')}. Here's why you'll find it here."
    )

    # ── Email subject options ─────────────────────────────────────────────────
    email_subjects = [
        f"We made the {term.lower().replace(' uk', '')} you've been looking for",
        f"This is the {term.lower().replace(' uk', '')} sorted, then",
        f"The {term.lower().replace(' uk', '')} situation is handled",
    ]

    # ── Pinterest titles ──────────────────────────────────────────────────────
    pinterest_titles = [
        f"{term_display.replace(' Uk', '').strip()} | Rock On Ruby UK",
        f"Personalised {term_display.replace(' Uk', '').strip()} Ideas | UK Gifting",
        f"Best {term_display.replace(' Uk', '').strip()} 2026 | Made in the UK",
    ]

    return {
        "term": term,
        "h1": h1,
        "h2s": h2s[:3],
        "faq_questions": faq_questions[:5],
        "before": before,
        "tension": tension,
        "shift": shift,
        "care": care,
        "cta_url": cta_url,
        "cta_text": cta_text,
        "social_hook": social_hook,
        "email_subjects": email_subjects,
        "pinterest_titles": pinterest_titles,
        "existing": existing,
        "score": score,
        "trend": trend,
    }


def no_ai_pack_for_term(r: dict, catalogue: dict, outline: dict | None = None) -> str:
    """
    Generate a full content pack for a term.
    If outline is provided, every format derives from the blog story.
    If not, falls back to keyword-only generation (legacy behaviour).
    """
    term = r["term"]
    existing = r.get("ror_existing", "")
    url = find_catalogue_url(existing, catalogue)
    mapping_note = page_mapping_note(term, existing)
    action = exact_visibility_action(term, existing, r.get("seo_action", ""))
    production_note = production_method_note(term, existing)
    design = design_direction_for_term(term)
    priority = "High" if r.get("score", 0) >= 8 else ("Medium" if r.get("score", 0) >= 5 else "Low")
    created_date = datetime.now().strftime("%Y-%m-%d")
    due_date = (datetime.now() + timedelta(days=7)).strftime("%Y-%m-%d")

    evidence = (
        f"Trend score: {score_explanation(int(r.get('score', 0)))} "
        f"Search interest estimate: {interest_explanation(int(r.get('avg_interest', 0)))} "
        f"Trend direction: {trend_explanation(r.get('trend', 'unknown'))}"
    )

    # ── Use outline if available, otherwise build it now ──────────────────────
    if outline is None:
        outline = build_blog_outline(r)

    h1 = outline["h1"]
    h2s = outline["h2s"]
    faq_questions = outline["faq_questions"]
    before = outline["before"]
    tension = outline["tension"]
    shift = outline["shift"]
    care = outline["care"]
    cta_text = outline["cta_text"]
    social_hook = outline["social_hook"]
    email_subjects = outline["email_subjects"]
    pinterest_titles = outline["pinterest_titles"]

    # ── Blog outline ──────────────────────────────────────────────────────────
    h2_lines = "\n".join(f"  - H2: {h2}" for h2 in h2s)
    faq_lines = "\n".join(f"  - {q}" for q in faq_questions)

    blog_outline_text = f"""
**H1:** {h1}

**Story structure:**
- Before (situation): {before}
- Tension (friction): {tension}
- Shift (turn): {shift}
- Reason to care: {care}

**H2 sections:**
{h2_lines}

**FAQ section questions:**
{faq_lines}

**CTA:** {cta_text} → {url}
**Production method note:** {production_note}
**Internal links to add:** {action['links']}
""".strip()

    # ── Email brief (derived from blog story) ─────────────────────────────────
    email_brief = f"""
**Subject line options:**
1. {email_subjects[0]}
2. {email_subjects[1]}
3. {email_subjects[2]}

**Preview text:** Because some gifts actually feel personal.

**Story angle (opening):** {before} {tension}

**Email structure:**
- Open with "Hey [name]" — {before}
- Section 1: The shift — {shift}
- Section 2: Product detail — reference {existing or 'the closest ROR product'}, mention personalisation options, production method ({production_note.split('.')[0].lower()}), and UK delivery
- Section 3: The reason to care — {care}
- CTA button: "{cta_text}" → {url}
- Optional PS: "P.S. If you need it by [date], order by [date]. We'll sort the rest."

**Holly's voice notes:**
- Write to one person, like Holly's messaging her sister
- Self-deprecating where it fits naturally — never forced
- Short paragraphs, one idea each, read it back out loud before sending

**Design direction:**
- Palette: {design['palette']}
- Type: {design['type']}
- Feel: {design['feel']}
- Avoid: {design['avoid']}
""".strip()

    # ── Reel brief (opens with blog hook, derived from story) ─────────────────
    reel_brief = f"""
**Hook (first line, on screen and spoken):** {social_hook}

**Story this reel tells:** {before} → {shift}

**Shot sequence:**
1. Hook line on screen (text overlay, 2 seconds max)
2. Product close-up — show the personalisation detail clearly, not just the garment
3. The making moment — embroidery needle, print coming off the machine, or hands packing the order
4. The reveal — finished product, gift-ready, styled simply
5. CTA end card — "{cta_text}" with URL

**Caption (use below the reel):**
{social_hook}

{shift}

Because {care.lower()}

{url}

**Hashtags:** #rockonruby #{term.replace(' ', '').replace('uk', 'UK')} #personalisedgifts #ukgifting #madeinuk

**Visual note:** Film in natural light. No studio setup needed. Real product, real hands, real packaging.
""".strip()

    # ── Stories brief (4 frames, conversion focus) ────────────────────────────
    stories_brief = f"""
**Frame 1 — Hook:**
Text overlay: "{social_hook}"
Background: product flat lay or close-up of personalisation detail

**Frame 2 — The problem:**
Text overlay: "{tension}"
Background: product in context (lifestyle, not studio)

**Frame 3 — The answer:**
Text overlay: "{shift}"
Include: product name, personalisation options, production method note
Add poll if useful: "Would you go for [option A] or [option B]?"

**Frame 4 — Conversion:**
Text overlay: "{cta_text}"
Add link sticker → {url}
Background: product packaged, gift-ready

**Voice:** Holly's, warm and direct. No sales language. No "tap the link below" — just the sticker.
""".strip()

    # ── Carousel brief (6 slides, H2s as slide topics) ───────────────────────
    slide_topics = h2s[:3] + [
        "The personalisation options",
        "Why Rock On Ruby instead of the high street",
        f"Shop {term.replace(' uk', '').replace(' UK', '').strip().title()} at Rock On Ruby",
    ]
    slide_lines = "\n".join(
        f"  Slide {i+1}: {topic}" for i, topic in enumerate(slide_topics[:6])
    )

    carousel_brief = f"""
**Hook slide (slide 1):** {social_hook}

**Slide structure:**
{slide_lines}

**Copy style:** Each slide is one clear thought. Short sentences. Holly's voice. No corporate language.

**Final slide CTA:** "{cta_text}" → {url}

**Design direction:**
- Palette: {design['palette']}
- Type: {design['type']}
- Feel: {design['feel']}
- Avoid: {design['avoid']}
""".strip()

    # ── TikTok brief (observation-led, same footage as reel) ─────────────────
    tiktok_brief = f"""
**Opening line (observation, not sales):** {social_hook}

**TikTok angle:** Same footage as the Reel. Different first line — more like Holly noticing something than Holly selling something.

**Alternative opening options:**
- "Genuinely cannot believe how hard it is to find a {term.lower().replace(' uk', '')} that isn't beige."
- "We made {term.lower().replace(' uk', '')} that don't look like everyone else's. Apparently that's rare."
- "POV: you need a {term.lower().replace(' uk', '')} that actually means something."

**Caption:** Keep it short. One observation, one line about the product, URL. No hashtag wall — 3 maximum.

**Sound:** trending audio or natural sound from the making process. No voiceover unless Holly is on camera.
""".strip()

    # ── Pinterest brief (keyword-led titles from H1/H2s) ─────────────────────
    pinterest_brief = f"""
**Pin 1:**
Title: {pinterest_titles[0]}
Description: {before} {shift} Shop at {url}
Image: product flat lay, clean background, personalisation visible

**Pin 2:**
Title: {pinterest_titles[1]}
Description: {tension} Rock On Ruby makes {term.lower().replace(' uk', '')} in Bury, Manchester, shipped across the UK.
Image: lifestyle shot or styled product in context

**Pin 3:**
Title: {pinterest_titles[2]}
Description: {care} Find yours at {url}
Image: gift packaging or product detail shot

**SEO note:** Pinterest treats pin titles as search keywords. Use the exact phrase "{term.replace(' uk', ' UK').strip()}" in at least one title.

**Design direction:**
- Palette: {design['palette']}
- Type: {design['type']}
- Feel: {design['feel']}
- Avoid: {design['avoid']}
""".strip()

    # ── Page copy brief (derived from H1 + story) ─────────────────────────────
    page_copy_brief = f"""
**Target keyword:** {term}
**Target URL:** {url}
**Page mapping check:** {mapping_note}

**Problem:** {action['problem']}
**Do this:** {action['do_this']}

**Rewrite the first 80 words of the page using this structure:**
"{before} {shift} {care} [Product name] at Rock On Ruby — made to order in Bury, Manchester, shipped across the UK."

**H1 for the page (if it can be changed):** {h1}

**Add these FAQ questions to the page:**
{faq_lines}

**Internal links to add:** {action['links']}
""".strip()

    # ── Approved ClickUp task breakdown ───────────────────────────────────────
    # This section uses the heading "Approved ClickUp Task Breakdown" which
    # clickup_tasks.py looks for. Only packs that reach this section get pushed.
    task_breakdown = f"""
### Approved ClickUp Task Breakdown

**Task name:** Blog: {term}
**Type tag:** blog
**Priority:** {priority}
**Date created:** {created_date}
**Suggested due date:** {due_date}
**Task summary:** Write the SEO blog using the outline below. H1, H2s, FAQ and CTA are pre-written — your job is to write the connecting copy in Holly's voice and make it feel like a real story, not a keyword list.

Blog outline:
{blog_outline_text}

**Task name:** Page Copy: {term}
**Type tag:** page-copy
**Priority:** {priority}
**Date created:** {created_date}
**Suggested due date:** {due_date}
**Task summary:** Update the mapped page using the brief below. This is a copy edit, not a rebuild — change the first 80 words, add the FAQ, add internal links.

{page_copy_brief}

**Task name:** Email: {term}
**Type tag:** email
**Priority:** {priority}
**Date created:** {created_date}
**Suggested due date:** {due_date}
**Task summary:** Write the full email using this brief. The story is the same one as the blog — don't start fresh, carry the angle forward.

{email_brief}

**Task name:** Reel: {term}
**Type tag:** reel
**Priority:** {priority}
**Date created:** {created_date}
**Suggested due date:** {due_date}
**Task summary:** Film and edit the reel using this brief. Hook, product close-up, making moment, reveal, CTA. 30-45 seconds.

{reel_brief}

**Task name:** Stories: {term}
**Type tag:** stories
**Priority:** {priority}
**Date created:** {created_date}
**Suggested due date:** {due_date}
**Task summary:** Build the 4 story frames using this brief. Same story as the blog and reel — different format.

{stories_brief}

**Task name:** Carousel: {term}
**Type tag:** carousel
**Priority:** {priority}
**Date created:** {created_date}
**Suggested due date:** {due_date}
**Task summary:** Design the carousel using this brief. Slides map to the blog H2s — same story, broken into slides.

{carousel_brief}

**Task name:** TikTok: {term}
**Type tag:** tiktok
**Priority:** {priority}
**Date created:** {created_date}
**Suggested due date:** {due_date}
**Task summary:** Use the same footage as the reel. Change the opening line to feel more like an observation. Brief below.

{tiktok_brief}

**Task name:** Pinterest: {term}
**Type tag:** pinterest
**Priority:** {priority}
**Date created:** {created_date}
**Suggested due date:** {due_date}
**Task summary:** Create 3 pins using keyword-led titles from the H1 and H2s. Brief below.

{pinterest_brief}
""".strip()

    return f"""
## {term}

### Evidence
{evidence}

### Blog Outline (source of truth for all formats)
{blog_outline_text}

### Content Execution Pack

**Visibility goal:** Make ROR the clearest answer for "{term}" across Google, email and social — in the same week.

**Production method:** {production_note}

### Format Briefs

#### Blog
{blog_outline_text}

#### Email
{email_brief}

#### Reel
{reel_brief}

#### Stories
{stories_brief}

#### Carousel
{carousel_brief}

#### TikTok
{tiktok_brief}

#### Pinterest
{pinterest_brief}

#### Page Copy
{page_copy_brief}

{task_breakdown}
""".strip()

def generate_no_ai_content(all_groups: list[dict] | None = None, trending_data: dict | None = None) -> bool:
    """
    Generate content packs where the blog outline is built first,
    and every other format (email, reel, stories, carousel, TikTok,
    Pinterest, page copy) derives from that same story.
    No Claude tokens used.
    """
    if all_groups is None:
        try:
            all_groups, trending_data = load_cached_trend_data()
        except FileNotFoundError as e:
            print(f"\n{e}")
            return False

    history = load_history()
    catalogue = load_json_file(CATALOGUE_FILE, {})
    seo_terms = pick_seo_terms(all_groups, history, cap=6)
    ranked = sorted(
        all_results(all_groups),
        key=lambda r: (-r.get("score", 0), -r.get("avg_interest", 0))
    )
    selected = seo_terms or ranked[:6]

    date_str = datetime.now().strftime("%d %B %Y, %H:%M")
    design_note = DESIGN_RULES_FILE.read_text(encoding="utf-8") if DESIGN_RULES_FILE.exists() else ""

    # ── Step 1: Build blog outlines first for all selected terms ──────────────
    print(f" Building blog outlines for {len(selected)} terms...")
    outlines: dict[str, dict] = {}
    for r in selected:
        outlines[r["term"]] = build_blog_outline(r)
        print(f"  Outline: {r['term']}")

    # ── Step 2: Build full content packs, each derived from its outline ───────
    print(f" Building content packs...")
    packs = "\n\n---\n\n".join(
        no_ai_pack_for_term(r, catalogue, outline=outlines[r["term"]])
        for r in selected
    )

    # ── Trend note ────────────────────────────────────────────────────────────
    trend_note = "Open UK trends not captured this run."
    if trending_data:
        web = trending_data.get("web", {})
        yt = trending_data.get("youtube", {})
        captured = (
            web.get("top", []) + web.get("rising", [])
            + yt.get("top", []) + yt.get("rising", [])
        )
        if captured:
            trend_note = "Raw trend ideas: " + ", ".join(captured[:10])

    # ── Write the markdown file ───────────────────────────────────────────────
    md = f"""# Rock On Ruby — Content Packs
Generated: {date_str}

---

## How this works

The blog outline is built first for each keyword. Every other format — email, reel, stories, carousel, TikTok, Pinterest and page copy — is derived from that same story. Same message, different format. Same keyword in every piece.

Approved packs are pushed to ClickUp as a parent task with 8 subtasks. Bethan gets everything she needs in each subtask — no blank page, no guessing, no briefing calls.

{trend_note}

---

## Design Rules Summary

{design_note.split('## Content Pack Design Output')[0].strip() if design_note else 'See design_system/ror_design_rules.md'}

---

# Content Packs

{packs}

---

Generated by ROR Content Generator — no-AI mode.
Run `python3 content_generator.py --no-ai` to regenerate.
"""

    CONTENT_FILE.write_text(md, encoding="utf-8")
    print(f" Content packs written: {CONTENT_FILE}")

    # Track history
    save_history(history, [r["term"] for r in selected], ["blog", "email", "reel", "stories", "carousel", "tiktok", "pinterest", "page-copy"])

    return True

# ── Prompt builder ────────────────────────────────────────────────────────────

def build_prompt(layer_terms: dict[int, list[dict]], seo_terms: list[dict], all_groups: list[dict],
                 catalogue: dict | None = None, instagram: dict | None = None,
                 trending_data: dict | None = None, finished_blogs: dict[str, str] | None = None) -> str:
    today = datetime.now().strftime("%d %B %Y")
    design_rules = DESIGN_RULES_FILE.read_text(encoding="utf-8") if DESIGN_RULES_FILE.exists() else ""

    # Flatten all selected terms for context
    all_selected = [r for terms in layer_terms.values() for r in terms]
    term_lines = []
    for r in all_selected:
        paa_str = f" | PAA: {'; '.join(r['paa'][:2])}" if r.get("paa") else ""
        rq_str  = f" | Rising: {', '.join(r['rising_queries'][:2])}" if r.get("rising_queries") else ""
        bo_str  = f" | BREAKOUT: {', '.join(r['breakout_queries'])}" if r.get("breakout_queries") else ""
        term_lines.append(
            f"- '{r['term']}', avg {r['avg_interest']}/100, {r['trend']}, "
            f"score {r['score']}/10, layer {r.get('layer',3)}, gap={not bool(r['ror_existing'])}"
            f"{rq_str}{paa_str}{bo_str}"
        )

    # PAA questions
    all_paa = [(r["term"], q) for g in all_groups for r in g["results"] for q in r.get("paa", [])]

    blog_terms = pick_blog_terms(layer_terms, seo_terms, cap=2)

    # Social terms
    social_terms = all_selected[:2]

    # Email terms
    email_terms = sorted(all_selected, key=lambda r: -r["score"])[:2]

    # Product description terms
    prod_terms = [r for r in all_selected if r.get("ror_existing")][:2]

    # SEO content breakdown
    blog_seo    = [r for r in seo_terms if "blog" in r.get("seo_action", "").lower()][:3]
    product_seo = [r for r in seo_terms if "product page" in r.get("seo_action", "").lower()][:3]
    collect_seo = [r for r in seo_terms if "collection" in r.get("seo_action", "").lower()][:3]

    # Build blog post section. In Claude mode, finished two-pass blogs become the source assets.
    blog_sections = ""
    if finished_blogs:
        blog_sections = "\n## FINISHED TWO-PASS BLOGS\n\nUse these finished blogs as source assets for email, social, Reel, Stories, Carousel, TikTok and Pinterest content. Do not rewrite the blogs unless explicitly asked.\n"
        for term, blog in finished_blogs.items():
            blog_sections += f"\n### Finished blog: {term}\n\n{blog}\n"
    else:
        for i, r in enumerate(blog_terms, 1):
            blog_sections += f"""
## BLOG POST {i}

Write a 600-800 word blog post targeting the keyword '{r['term']}'.
- H1 must contain the keyword naturally
- Include H2 headings phrased as buyer search questions
- Include H3 headings in longer sections where useful
- Include a fully written FAQ section with at least 4 questions
- Mention Bury, Manchester naturally
- Mention UK-wide shipping or delivered across the UK
- Include specific personalisation examples and quality details
- Storytelling structure: real moment to tension to shift to reason to care to CTA
- Holly's voice throughout, warm, funny, Manchester woman running a business
- End CTA links to rockonruby.co.uk
- Written for Google and AI search, answer the topic completely and naturally
"""

    # Build social captions section
    social_section = f"""
## SOCIAL CAPTIONS

Write 2 social media captions (Instagram/TikTok format) targeting: {', '.join("'" + r['term'] + "'" for r in social_terms)}.
If finished blogs are supplied above, derive the captions from the blog angles and product context.
Each caption must:
- Open with a strong hook (first line = the scroll-stopper)
- Be 3-6 lines total, sound like Holly texting her mate
- Add one final production line starting "Visual note:" after the caption
- 3-5 hashtags at the very end only
"""

    # Build email design prompt section
    email_section = ""
    for i, r in enumerate(email_terms, 1):
        email_section += f"""
## EMAIL DESIGN PROMPT {i}

For the keyword '{r['term']}', produce a full email design prompt that Bethan can paste into Claude to write the complete email.
If finished blogs are supplied above, derive the email story angle from the relevant finished blog.
Format EXACTLY as follows:

**Subject:** [subject line, punchy, Holly's voice, no corporate language]
**Preview text:** [45 characters max, completes the subject naturally]

**Story angle:** [2 sentences, the real moment or observation that opens the email]
**Tension/friction:** [what's the problem or decision the reader faces]
**Shift:** [the before to after]
**Reason to care:** [why does this matter emotionally to her]

**Email structure:**
- Opening (Hey [name]), [2-sentence instruction for opening]
- Section 1, [what this section does and says]
- Section 2, [what this section does and says]
- CTA, [exact button text] linking to [URL path on rockonruby.co.uk]
- PS, [optional PS idea]

**Holly's voice notes for this email:** [3 specific voice reminders relevant to this topic]

**Image suggestions:** [2-3 specific image ideas that would work for this email]

**Ready-to-paste Claude prompt:**
"You are writing an email for Rock On Ruby in Holly's voice. [Complete prompt that gives Claude everything it needs to write the full email from scratch, including the story angle, voice rules, CTA, and any specific product details.]"
"""

    # Build product descriptions section
    prod_section = ""
    if prod_terms:
        prod_section = f"""
## PRODUCT DESCRIPTIONS

For each product below write a 60-word description in Holly's voice, warm, funny, specific.
Lead with the product benefit, not features:
{chr(10).join(f"- '{r['term']}' to {r['ror_existing']}" for r in prod_terms)}
"""

    # Build SEO content section
    seo_section = ""
    if blog_seo:
        seo_section += f"""
## SEO CONTENT, BLOG DRAFTS

For each keyword below write a full 600-800 word blog post draft unless that keyword already has a finished two-pass blog above:
{chr(10).join(f"- '{r['term']}' (score {r['score']}/10, {r['trend']})" for r in blog_seo)}

Each post:
- H1 includes keyword naturally
- H2 headings are buyer search questions
- H3 headings appear in longer sections where useful
- Includes a fully written FAQ section with at least 4 questions
- Mentions Bury, Manchester naturally
- Mentions UK-wide shipping or delivered across the UK
- 600-800 words, Holly's voice, storytelling structure
- Ends with CTA to rockonruby.co.uk
- Optimised for Google and AI search (answer the question fully)
"""

    if product_seo:
        seo_section += f"""
## SEO CONTENT, PRODUCT PAGE BRIEFS

For each keyword write a product page brief (title, 80-word description, meta title, meta description):
{chr(10).join(f"- '{r['term']}'" for r in product_seo)}
"""

    if collect_seo:
        seo_section += f"""
## SEO CONTENT, COLLECTION PAGE COPY

For each keyword write updated collection page copy (150 words) + 2 image reference suggestions:
{chr(10).join(f"- '{r['term']}'" for r in collect_seo)}
"""

    # PAA answers
    paa_section = ""
    if all_paa:
        paa_section = f"""
## PAA ANSWERS

For each People Also Ask question write a 60-word answer optimised for Google AI Overviews and ChatGPT.
Answer in the first sentence, then add context. Mention Rock On Ruby naturally if relevant.
{chr(10).join(f'- {q}' for _, q in all_paa[:6])}
"""

    # ── Shopify catalogue context ──────────────────────────────────────────────
    _skip_bs = {"personalisation", "option-set", "mystery bag", "back of the neck", "2nd line"}
    catalogue_ctx = ""
    if catalogue:
        # Top bestsellers with real URLs
        top_sellers = [b for b in catalogue.get("bestsellers", [])[:12]
                       if not any(s in b["title"].lower() for s in _skip_bs)][:6]
        if top_sellers:
            seller_lines = "\n".join(
                f"  - {b['title']} (£{b['revenue']:,.0f} revenue, {b['orders']} orders)"
                for b in top_sellers
            )
            catalogue_ctx += f"\nTOP BESTSELLERS, link to these wherever relevant:\n{seller_lines}\n"

        # Relevant collections matched against today's selected terms
        all_words = set()
        for r in all_selected:
            all_words.update(w for w in r["term"].lower().split() if len(w) > 3)
        matched_collections = [
            c for c in catalogue.get("collections", [])
            if any(w in c["title"].lower() for w in all_words)
        ][:10]
        if matched_collections:
            coll_lines = "\n".join(f"  - {c['title']} to {c['url']}" for c in matched_collections)
            catalogue_ctx += f"\nMATCHING ROR COLLECTION URLS (use exact URLs in all CTAs and internal links):\n{coll_lines}\n"

        # Relevant products for today's terms
        matched_products = []
        for p in catalogue.get("products", []):
            p_lower = p["title"].lower()
            if any(w in p_lower for w in all_words):
                matched_products.append(p)
            if len(matched_products) >= 8:
                break
        if matched_products:
            prod_lines = "\n".join(
                f"  - {p['title']} to {p['url']}" + (f" (£{p['price']:.0f})" if p.get("price") else "")
                for p in matched_products
            )
            catalogue_ctx += f"\nMATCHING ROR PRODUCTS (use real URLs, not guessed slugs):\n{prod_lines}\n"

    # ── Instagram insights context ─────────────────────────────────────────────
    instagram_ctx = ""
    if instagram and instagram.get("recent_posts"):
        posts = [p for p in instagram["recent_posts"] if p.get("topic")][-5:]
        if posts:
            post_lines = "\n".join(
                f"  - {p['topic']} ({p.get('content_type', '')}): {p.get('engagement', '')} engagement"
                + (f", {p['notes']}" if p.get("notes") else "")
                for p in posts
            )
            top_formats  = ", ".join(instagram.get("top_formats", []))
            trending_own = ", ".join(instagram.get("trending_topics_on_our_account", []))
            not_working  = "; ".join(instagram.get("what_is_not_working", []))
            instagram_ctx = f"""
INSTAGRAM PERFORMANCE (align content with what's working on our account):
Recent posts:
{post_lines}
Top performing formats: {top_formats}
Trending on our account right now: {trending_own}
What is NOT working: {not_working}
"""

    # Build the trending queries block
    if trending_data:
        web = trending_data.get("web", {})
        yt  = trending_data.get("youtube", {})
        source_note = trending_data.get("source_note", "")
        web_top    = "\n".join(f"{i}. {q} [Web]" for i, q in enumerate(web.get("top", [])[:10], 1)) or "none captured"
        yt_top     = "\n".join(f"{i}. {q} [YouTube]" for i, q in enumerate(yt.get("top", [])[:10], 1)) or "none captured"
        web_rising = "\n".join(f"{i}. {q} [Web]" for i, q in enumerate(web.get("rising", [])[:10], 1)) or "none captured"
        yt_rising  = "\n".join(f"{i}. {q} [YouTube]" for i, q in enumerate(yt.get("rising", [])[:10], 1)) or "none captured"
        trending_block = f"""
UK TRENDING QUERIES, PAST 7 DAYS, RAW GOOGLE DATA:
Use these only as inspiration. Do not filter, score, rewrite or force them into content.
Where a loose ROR product connection exists, use it naturally. Where no connection exists, ignore it.
Source note: {source_note or "not supplied"}

Top Searches UK, Past Week:
{web_top}
{yt_top}

Rising Searches UK, Past Week:
{web_rising}
{yt_rising}"""
    else:
        trending_block = "\nUK TRENDING QUERIES, PAST 7 DAYS: not available this run."

    opportunity_section = f"""
## WEEKLY OPPORTUNITY NOTES

Scan the UK Trending Queries above. For each query where a connection to an ROR product exists, however loose, write one line for Bethan.
Format: [trending query] is trending, [specific, concrete suggestion tied to an ROR product or content angle].
Examples: "World Cup is trending, consider year tops in football colours this week"
          "Great British Bake Off is trending, push the biscuit range on Stories this week"
Only write a note where a real connection exists. Do not force it.
Output as a numbered list. If no connections exist, write: No strong trending connections this week.
"""

    return f"""
{BRAND_CONTEXT}
{WRITING_RULES}
{design_rules}
{catalogue_ctx}
{instagram_ctx}
---
TODAY'S DATE: {today}

TOP TRENDING TERMS THIS RUN:
{chr(10).join(term_lines)}
{trending_block}

---
Generate the following content for Rock On Ruby. Return EXACTLY the sections below,
each starting with the exact markdown heading shown. No preamble, no commentary after.

For every content idea, include a short "Design direction:" production note using the ROR design rules above. Pick palette, type mood and visual treatment to fit the product, season and audience. For example, Father's Day should not default to soft pink styling if navy, army green, orange, beige and black would fit better.
When finished two-pass blogs are supplied, treat them as the source assets. Email, social and production packs should flow from the finished blog angle, not from a disconnected caption idea.
{opportunity_section}
{blog_sections}
{social_section}
{email_section}
{prod_section}
{seo_section}
{paa_section}
""".strip()


# ── Main generator ────────────────────────────────────────────────────────────

def generate_content(all_groups: list[dict] | None = None, trending_data: dict | None = None) -> bool:
    api_key = os.environ.get("ANTHROPIC_API_KEY", "")
    if not api_key:
        print("\nANTHROPIC_API_KEY not set, skipping content generation.")
        return False

    # Load cache if not passed directly
    if all_groups is None:
        try:
            all_groups, trending_data = load_cached_trend_data()
        except FileNotFoundError as e:
            print(f"\n{e}")
            return False

    history   = load_history()
    catalogue = load_json_file(CATALOGUE_FILE, {})
    instagram = load_json_file(INSTAGRAM_FILE, {})

    layer_terms = pick_terms_by_layer(all_groups, history)
    seo_terms   = pick_seo_terms(all_groups, history)
    forced_keyword = os.environ.get("CONTENT_KEYWORD", "").strip()
    forced_term = find_cached_term(all_groups, forced_keyword) if forced_keyword else None
    if forced_keyword and not forced_term:
        forced_term = find_rank_term(forced_keyword)
    if forced_keyword and forced_term:
        seo_terms = [forced_term] + [r for r in seo_terms if r.get("term") != forced_term.get("term")]
        layer_terms.setdefault(99, [])
        if all(r.get("term") != forced_term.get("term") for r in layer_terms[99]):
            layer_terms[99].insert(0, forced_term)
    elif forced_keyword:
        print(f"  Requested keyword not found in cached trend data: {forced_keyword}")

    print("\n-- Content Generation (Claude API) --")
    all_selected = [r for terms in layer_terms.values() for r in terms]
    print(f"  Terms selected: {', '.join(r['term'] for r in all_selected)}")
    if forced_keyword:
        print(f"  Requested keyword: {forced_keyword}")
    print(f"  SEO terms: {len(seo_terms)}")

    client = anthropic.Anthropic(api_key=api_key)
    blog_terms = pick_blog_terms(layer_terms, seo_terms, cap=2)
    finished_blogs: dict[str, str] = {}
    try:
        if blog_terms:
            print(f"  Two-pass blogs: {', '.join(r['term'] for r in blog_terms)}")
            finished_blogs = generate_two_pass_blogs(client, blog_terms, all_groups, catalogue, trending_data)
    except Exception as e:
        print(f"  Two-pass blog generation failed: {e}")
        return False

    prompt = build_prompt(layer_terms, seo_terms, all_groups, catalogue, instagram, trending_data, finished_blogs)
    print("  Calling Claude API...")
    try:
        message = client.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=8192,
            system=(
                "You are a copywriter for Rock On Ruby, a print-on-demand personalised clothing brand "
                "based in Bury, Manchester. You write in Holly's voice, warm, funny, straight-talking, "
                "never corporate. Follow the brand guide exactly.\n\n"
                f"{WRITING_RULES}"
            ),
            messages=[{"role": "user", "content": prompt}],
        )
        content_text = message.content[0].text
    except Exception as e:
        print(f"  Claude API error: {e}")
        return False

    # Save history
    used_terms  = [r["term"] for r in all_selected] + [r["term"] for r in seo_terms]
    used_types  = ["blog", "two-pass-blog", "social", "email", "product", "seo"]
    save_history(history, used_terms, used_types)

    # Build markdown file
    date_str = datetime.now().strftime("%d %B %Y, %H:%M")
    layer4_terms = [r["term"] for r in layer_terms.get(4, [])]
    top_terms    = [r["term"] for r in all_selected[:5]]
    md = f"""# Rock On Ruby - Content Drafts
Generated: {date_str}
Run `python3 content_generator.py` to regenerate with cached trend data.

---

> **Layer 4 (bestsellers) terms this run:** {', '.join(layer4_terms) or 'none'}
> **Top terms this run:** {', '.join(top_terms)}
> **SEO content pieces:** {len(seo_terms)}

---

## FINISHED TWO-PASS BLOGS

{chr(10).join(f"### {term}{chr(10)}{blog}" for term, blog in finished_blogs.items()) if finished_blogs else "No two-pass blogs generated this run."}

---

{content_text}

---
*Generated by ROR Content Generator · rockonruby.co.uk*
"""

    CONTENT_FILE.write_text(md, encoding="utf-8")
    print(f"  Content draft: {CONTENT_FILE}")
    return True


def main() -> int:
    parser = argparse.ArgumentParser(
        description="ROR Content Generator",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Workflow:
  Step 1:  python3 content_generator.py --no-ai
           Generates blog outlines and content pack briefs from cached data.
           No API calls. No token cost. Review ror_content_draft.md output.

  Step 2:  python3 content_generator.py --generate-blogs
           Runs approved outlines through the two-pass blog system.
           Pass 1: Holly voice draft. Pass 2: SEO optimisation.
           2 API calls per approved pack. Updates ror_content_draft.md.

  Step 3:  python3 clickup_tasks.py
           Pushes approved packs to ClickUp as parent task + 8 subtasks.
           Each subtask contains a complete brief including the finished blog.

  Full Claude mode (all in one, uses more tokens):
           python3 content_generator.py
        """
    )
    parser.add_argument(
        "--no-ai",
        action="store_true",
        help="Generate blog outlines and content pack briefs only. No API calls."
    )
    parser.add_argument(
        "--generate-blogs",
        action="store_true",
        help="Run approved outlines through two-pass blog generation. Requires ANTHROPIC_API_KEY."
    )
    parser.add_argument(
        "--cached",
        action="store_true",
        help="Use cached trend data instead of fetching live data."
    )

    args = parser.parse_args()

    if args.no_ai:
        print("\n-- ROR Content Generator (no-AI mode) --")
        ok = generate_no_ai_content()
        if ok:
            print("\nDone. Review ror_content_draft.md then run:")
            print("  python3 content_generator.py --generate-blogs")
        return 0 if ok else 1

    if args.generate_blogs:
        return run_generate_blogs()

    # ── Full Claude mode ──────────────────────────────────────────────────────
    api_key = os.environ.get("ANTHROPIC_API_KEY", "")
    if not api_key:
        print("ANTHROPIC_API_KEY not set.")
        print("For zero token cost run: python3 content_generator.py --no-ai")
        return 1

    print("\n-- ROR Content Generator (full Claude mode) --")

    try:
        all_groups, trending_data = load_cached_trend_data()
    except FileNotFoundError as e:
        print(f"\n{e}")
        return 1

    history = load_history()
    catalogue = load_json_file(CATALOGUE_FILE, {})
    instagram = load_json_file(INSTAGRAM_FILE, {})

    layer_terms = pick_terms_by_layer(all_groups, history)
    seo_terms = pick_seo_terms(all_groups, history)
    blog_terms = pick_blog_terms(layer_terms, seo_terms)

    client = anthropic.Anthropic(api_key=api_key)

    # Pass 1 + Pass 2 blogs first
    finished_blogs = generate_two_pass_blogs(
        client, blog_terms, all_groups, catalogue, trending_data
    )

    # Build full prompt with finished blogs as source assets
    prompt = build_prompt(
        layer_terms, seo_terms, all_groups,
        catalogue=catalogue,
        instagram=instagram,
        trending_data=trending_data,
        finished_blogs=finished_blogs,
    )

    design_rules = DESIGN_RULES_FILE.read_text(encoding="utf-8") if DESIGN_RULES_FILE.exists() else ""

    system = (
        f"{BRAND_CONTEXT}\n\n{WRITING_RULES}\n\n"
        f"Today is {datetime.now().strftime('%d %B %Y')}.\n\n"
        f"{design_rules}"
    )

    print("\nGenerating full content pack via Claude...")
    content = claude_text(client, system, prompt, max_tokens=8192)

    date_str = datetime.now().strftime("%d %B %Y, %H:%M")
    md = f"# Rock On Ruby — Content Pack\nGenerated: {date_str}\n\n---\n\n{content}"

    CONTENT_FILE.write_text(md, encoding="utf-8")
    print(f"\nContent pack: {CONTENT_FILE}")

    save_history(history, [r["term"] for terms in layer_terms.values() for r in terms], ["full"])

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
