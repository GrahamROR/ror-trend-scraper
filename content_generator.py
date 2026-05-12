"""
Rock On Ruby — AI Content Generator
Called automatically at the end of each scraper run.

Reads trend data from the cache, sends to Claude API, and writes a markdown
file (ror_content_draft.md) that Bethan can copy from directly.

Requires: ANTHROPIC_API_KEY environment variable
"""

import os
import json
from datetime import datetime
from pathlib import Path
import anthropic

OUTPUT_DIR   = Path(__file__).parent
CONTENT_FILE = OUTPUT_DIR / "ror_content_draft.md"

BRAND_CONTEXT = """
BRAND: Rock On Ruby — print-on-demand personalised clothing and accessories.
Based in Bury, Manchester. Co-owned by Holly (brand voice) and Graham (strategy).

PRODUCTS: Personalised embroidered caps, sweatshirts, hoodies, tees, tote bags, slogan clothing.
CUSTOMER: UK women, 30–50. Busy. Thoughtful gift-buyer. Warm, funny, slightly chaotic.
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
- Always write to ONE person — Holly's sister. Never to a crowd.

BLOG/SEO RULES:
- Lead with target keyword naturally in first sentence and H1
- Human first, search engine second
- 500 words for blog posts
- Always end with a natural CTA
- Storytelling structure: real moment → tension → shift → reason to care → gentle CTA
""".strip()


def pick_top_terms(all_groups: list[dict], n: int = 8) -> list[dict]:
    """Return the top-n terms by score, weighted toward rising ones."""
    all_results = [r for g in all_groups for r in g["results"]]
    rising_first = sorted(
        all_results,
        key=lambda r: (-(r["score"]), -(1 if r["trend"] == "rising" else 0), -r["avg_interest"])
    )
    return rising_first[:n]


def build_prompt(top_terms: list[dict], all_groups: list[dict]) -> str:
    """Build the Claude prompt with full trend context."""
    term_lines = []
    for r in top_terms:
        paa_str = ""
        if r.get("paa"):
            paa_str = f" | PAA: {'; '.join(r['paa'][:3])}"
        rq_str = ""
        if r.get("rising_queries"):
            rq_str = f" | Rising searches: {', '.join(r['rising_queries'][:3])}"
        term_lines.append(
            f"- '{r['term']}' — avg {r['avg_interest']}/100, {r['trend']}, "
            f"score {r['score']}/10, gap={not bool(r['ror_existing'])}{rq_str}{paa_str}"
        )

    # Get all PAA questions for context
    all_paa = []
    for g in all_groups:
        for r in g["results"]:
            for q in r.get("paa", []):
                all_paa.append((r["term"], q))

    paa_block = "\n".join(f"  [{t}] {q}" for t, q in all_paa[:20]) if all_paa else "  None captured this run."

    # Pick top 2 for blog posts (rising + meaningful avg)
    blog_candidates = [r for r in top_terms if r["trend"] == "rising"][:2]
    if len(blog_candidates) < 2:
        blog_candidates = top_terms[:2]

    blog_1_term = blog_candidates[0]["term"] if blog_candidates else top_terms[0]["term"]
    blog_2_term = blog_candidates[1]["term"] if len(blog_candidates) > 1 else top_terms[1]["term"]

    return f"""
{BRAND_CONTEXT}

---
TODAY'S DATE: {datetime.now().strftime('%d %B %Y')}

TOP TRENDING TERMS THIS WEEK (from Google Trends UK, 90-day window):
{chr(10).join(term_lines)}

ALL PEOPLE ALSO ASK QUESTIONS CAPTURED:
{paa_block}

---
Generate the following content for Rock On Ruby. Return EXACTLY the sections below,
each starting with the exact markdown heading shown. No preamble, no commentary after.

## BLOG POST 1

Write a 500-word blog post targeting the keyword '{blog_1_term}'.
- H1 must contain the keyword naturally
- Storytelling structure: real moment → tension → shift → reason to care → CTA
- Holly's voice throughout — warm, funny, Manchester woman running a business
- End CTA links to rockonruby.co.uk (write it as [rockonruby.co.uk](https://rockonruby.co.uk))
- Written for Google and AI search — answer the topic completely and naturally

## BLOG POST 2

Write a 500-word blog post targeting the keyword '{blog_2_term}'.
- Same rules as above

## SOCIAL CAPTIONS

Write 5 social media captions (Instagram/TikTok format).
Each caption must:
- Open with a strong hook (first line = the scroll-stopper)
- Be 3-6 lines total
- Sound like Holly texting her mate, not a brand account
- Tie to one of the top trending terms
- Include a suggested visual note in [brackets] at the end
- Never use hashtags inline — put 3-5 at the very end of each

## EMAIL SUBJECT LINES

Write 3 email subject lines tied to what's rising.
Format each as:
**Subject:** [subject line]
**Preview text:** [45-word preview]

## PRODUCT DESCRIPTIONS

For each of these trending search terms that maps to an existing ROR product,
write a 60-word product description in Holly's voice:
- fathers day gifts uk → personalised cap or sweatshirt
- glastonbury 2026 → festival cap
- beach holiday uk → personalised tote bag
- personalised gifts uk → personalised cap

Each description: warm, funny, specific. Leads with the product benefit, not features.

## PAA ANSWERS

For each People Also Ask question below, write a 60-word answer optimised for
Google AI Overviews and ChatGPT. Be direct, answer the question in the first sentence,
then add context. Mention Rock On Ruby naturally if relevant (don't force it).

{chr(10).join(f'- {q}' for _, q in all_paa[:8]) if all_paa else '- No PAA questions captured this run — skip this section.'}
""".strip()


def generate_content(all_groups: list[dict]) -> bool:
    """
    Call Claude API and write content draft markdown.
    Returns True on success, False if key missing or API error.
    """
    api_key = os.environ.get("ANTHROPIC_API_KEY", "")
    if not api_key:
        print("\n⚠️  ANTHROPIC_API_KEY not set — skipping content generation.")
        print("   Set it with: export ANTHROPIC_API_KEY=your_key_here")
        print("   Then re-run: python3 scraper.py --cached")
        return False

    print("\n── Content Generation (Claude API) ──")
    top_terms = pick_top_terms(all_groups)
    prompt    = build_prompt(top_terms, all_groups)

    client = anthropic.Anthropic(api_key=api_key)

    print("  Calling Claude API...")
    try:
        message = client.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=8192,
            system=(
                "You are a copywriter for Rock On Ruby, a print-on-demand personalised clothing brand "
                "based in Bury, Manchester. You write in Holly's voice — warm, funny, straight-talking, "
                "never corporate. Follow the brand guide exactly."
            ),
            messages=[{"role": "user", "content": prompt}],
        )
        content_text = message.content[0].text
    except Exception as e:
        print(f"  Claude API error: {e}")
        return False

    # Build the markdown file
    date_str = datetime.now().strftime("%d %B %Y, %H:%M")
    md = f"""# Rock On Ruby — Content Drafts
Generated: {date_str}
Run `python3 scraper.py` to regenerate with fresh trend data.

---

> **Top trending terms this run:** {', '.join(r['term'] for r in top_terms[:5])}

---

{content_text}

---
*Generated by ROR Trend Scraper · rockonruby.co.uk*
"""

    CONTENT_FILE.write_text(md, encoding="utf-8")
    print(f"  Content draft → {CONTENT_FILE}")
    return True
