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

BRAND_CONTEXT = """
BRAND: Rock On Ruby, print-on-demand personalised clothing and accessories.
Based in Bury, Manchester. Co-owned by Holly (brand voice) and Graham (strategy).

PRODUCTS: Personalised embroidered caps, sweatshirts, hoodies, tees, tote bags, slogan clothing.
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


# ── Prompt builder ────────────────────────────────────────────────────────────

def build_prompt(layer_terms: dict[int, list[dict]], seo_terms: list[dict], all_groups: list[dict],
                 catalogue: dict | None = None, instagram: dict | None = None,
                 trending_data: dict | None = None) -> str:
    today = datetime.now().strftime("%d %B %Y")

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

    # Blog post targets (layer 4 first, then others)
    blog_terms = (
        [r for r in layer_terms.get(4, [])][:2]
        + [r for layer, rs in layer_terms.items() if layer != 4 for r in rs][:2]
    )[:2]

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

    # Build blog post section
    blog_sections = ""
    for i, r in enumerate(blog_terms, 1):
        blog_sections += f"""
## BLOG POST {i}

Write a 500-word blog post targeting the keyword '{r['term']}'.
- H1 must contain the keyword naturally
- Storytelling structure: real moment to tension to shift to reason to care to CTA
- Holly's voice throughout, warm, funny, Manchester woman running a business
- End CTA links to rockonruby.co.uk
- Written for Google and AI search, answer the topic completely and naturally
"""

    # Build social captions section
    social_section = f"""
## SOCIAL CAPTIONS

Write 2 social media captions (Instagram/TikTok format) targeting: {', '.join("'" + r['term'] + "'" for r in social_terms)}.
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

For each keyword below write a full 500-word blog post draft:
{chr(10).join(f"- '{r['term']}' (score {r['score']}/10, {r['trend']})" for r in blog_seo)}

Each post:
- H1 includes keyword naturally
- 500 words, Holly's voice, storytelling structure
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
        if not CACHE_FILE.exists():
            print("\ntrend_cache.json not found, run scraper first.")
            return False
        raw = json.loads(CACHE_FILE.read_text())
        if isinstance(raw, dict) and "groups" in raw:
            all_groups    = raw["groups"]
            trending_data = raw.get("trending", {})
        else:
            all_groups = raw

    history   = load_history()
    catalogue = {}
    instagram = {}
    if CATALOGUE_FILE.exists():
        try:
            catalogue = json.loads(CATALOGUE_FILE.read_text())
        except Exception:
            pass
    if INSTAGRAM_FILE.exists():
        try:
            instagram = json.loads(INSTAGRAM_FILE.read_text())
        except Exception:
            pass

    layer_terms = pick_terms_by_layer(all_groups, history)
    seo_terms   = pick_seo_terms(all_groups, history)
    prompt      = build_prompt(layer_terms, seo_terms, all_groups, catalogue, instagram, trending_data)

    print("\n-- Content Generation (Claude API) --")
    all_selected = [r for terms in layer_terms.values() for r in terms]
    print(f"  Terms selected: {', '.join(r['term'] for r in all_selected)}")
    print(f"  SEO terms: {len(seo_terms)}")

    client = anthropic.Anthropic(api_key=api_key)
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
    used_types  = ["blog", "social", "email", "product", "seo"]
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

{content_text}

---
*Generated by ROR Content Generator · rockonruby.co.uk*
"""

    CONTENT_FILE.write_text(md, encoding="utf-8")
    print(f"  Content draft: {CONTENT_FILE}")
    return True


if __name__ == "__main__":
    generate_content()
