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


def no_ai_pack_for_term(r: dict, catalogue: dict) -> str:
    term = r["term"]
    existing = r.get("ror_existing", "")
    url = find_catalogue_url(existing, catalogue)
    mapping_note = page_mapping_note(term, existing)
    action = exact_visibility_action(term, existing, r.get("seo_action", ""))
    intro_draft = suggested_intro_draft(term, existing)
    production_note = production_method_note(term, existing)
    design = design_direction_for_term(term)
    priority = "High" if r.get("score", 0) >= 8 else ("Medium" if r.get("score", 0) >= 5 else "Low")
    created_date = datetime.now().strftime("%Y-%m-%d")
    due_date = (datetime.now() + timedelta(days=7)).strftime("%Y-%m-%d")
    evidence = (
        f"Trend score: {score_explanation(int(r.get('score', 0)))} "
        f"Search interest estimate: {interest_explanation(int(r.get('avg_interest', 0)))} "
        f"Trend direction: {trend_explanation(r.get('trend', 'unknown'))} "
        "Ranking data is not connected yet, so this action is inferred."
    )
    return f"""
## {term}

### Visibility Action

**Page or product:** {existing or 'Needs page mapping'}

**Target URL:** {url}

**Page mapping check:** {mapping_note}

**Target keyword:** {term}

**Priority:** {priority}

**Recommended owner:** System drafts from the evidence. Bethan checks placement and execution, Holly checks customer-facing voice, Graham checks SEO intent and page mapping.

**Date created:** {created_date}

**Suggested due date:** {due_date}

**Evidence:** {evidence}

**Problem:** {action['problem']}

**Do this:** {action['do_this']}

**Who writes this:** The system drafts this from the evidence, using the target keyword, mapped page, search intent, design rules and content structure. Bethan and Holly should not be starting from a blank page.

**How it is used:** Bethan checks the page or channel it belongs on, Holly reviews tone where needed, and Graham checks the SEO/page mapping if it is marked for review. If Claude credits are available, use the same evidence to polish the draft. If not, use the no-AI draft as the first usable version.

**Suggested copy focus:** {action['copy_focus']}

**Suggested intro draft:** {intro_draft}

**Production method note:** {production_note}

**Internal links to add:** {action['links']}

**Review note:** This no-AI pack is not approved finished content. Use it for planning, evidence review and page mapping checks only. Do not push it to ClickUp as a production task.

### Draft Task Breakdown

**Task name:** Page Copy: {term}
**Type tag:** page-copy
**Priority:** {priority}
**Date created:** {created_date}
**Suggested due date:** {due_date}
**Task summary:** Review and place the system-generated page intro or supporting page copy for "{term}" using the exact "Do this" notes, suggested intro draft and internal link guidance. Bethan checks placement, Holly reviews voice, Graham checks SEO/page mapping.

**Task name:** Blog: {term}
**Type tag:** blog
**Priority:** {priority}
**Date created:** {created_date}
**Suggested due date:** {due_date}
**Task summary:** Create or update a blog that supports "{term}", links to {existing or 'the chosen ROR page'}, includes a short FAQ section and points traffic to {url}.

**Task name:** Email: {term}
**Type tag:** email
**Priority:** {priority}
**Date created:** {created_date}
**Suggested due date:** {due_date}
**Task summary:** Turn the blog or page angle into a shopping email with one clear product block, one add-on or bundle prompt and a CTA to {url}.

**Task name:** Reel: {term}
**Type tag:** reel
**Priority:** {priority}
**Date created:** {created_date}
**Suggested due date:** {due_date}
**Task summary:** Film product close-ups, personalisation detail, packing or styling, then finish on the CTA product.

**Task name:** Stories: {term}
**Type tag:** stories
**Priority:** {priority}
**Date created:** {created_date}
**Suggested due date:** {due_date}
**Task summary:** Build 4 frames: hook, product proof, personalisation or gift detail, link sticker. Add a poll only if it helps the buying decision.

**Task name:** Carousel: {term}
**Type tag:** carousel
**Priority:** {priority}
**Date created:** {created_date}
**Suggested due date:** {due_date}
**Task summary:** Build 6 slides: hook, problem, product answer, personalisation detail, proof or use case, CTA.

**Task name:** TikTok: {term}
**Type tag:** tiktok
**Priority:** {priority}
**Date created:** {created_date}
**Suggested due date:** {due_date}
**Task summary:** Use the Reel footage, but make the first line feel more like an observation from Holly than a sales line.

**Task name:** Pinterest: {term}
**Type tag:** pinterest
**Priority:** {priority}
**Date created:** {created_date}
**Suggested due date:** {due_date}
**Task summary:** Create 3 pins with keyword-led titles, product or gift moment descriptions and the ROR URL.

### Content Execution Pack

**Visibility goal:** Help ROR become a clearer answer for "{term}" and support the mapped product or page.

**Production method:** {production_note}

**Blog:** Create or update a blog that answers the search intent, links to {existing or 'the closest matching ROR product'}, and includes a short FAQ section.

**Email:** Turn the blog angle into a shopping email with one clear product block, one supporting product or add-on, and a CTA to {url}.

**Reel:** Open with a practical hook tied to the search intent. Film product close-ups, personalisation detail, packing or styling, then finish on the CTA product.

**Stories:** Use 4 frames: hook, product proof, personalisation/gift detail, link sticker. Add a poll only if it helps the buying decision.

**Carousel:** Use 6 slides: hook, problem, product answer, personalisation detail, proof or use case, CTA.

**TikTok:** Keep it more observation-led than sales-led. Use the same Reel footage but make the first line feel like a real comment from Holly.

**Pinterest:** Create 3 pins using keyword-led titles. Include the product, gift moment and ROR URL in the description.

### Design Direction

**Moment:** {design['moment']}

**Palette:** {design['palette']}

**Type mood:** {design['type']}

**Feel:** {design['feel']}

**Avoid:** {design['avoid']}
"""


def generate_no_ai_content(all_groups: list[dict] | None = None, trending_data: dict | None = None) -> bool:
    if all_groups is None:
        try:
            all_groups, trending_data = load_cached_trend_data()
        except FileNotFoundError as e:
            print(f"\n{e}")
            return False

    history = load_history()
    catalogue = load_json_file(CATALOGUE_FILE, {})
    seo_terms = pick_seo_terms(all_groups, history, cap=6)
    ranked = sorted(all_results(all_groups), key=lambda r: (-r.get("score", 0), -r.get("avg_interest", 0)))
    selected = seo_terms or ranked[:6]

    date_str = datetime.now().strftime("%d %B %Y, %H:%M")
    design_note = DESIGN_RULES_FILE.read_text(encoding="utf-8") if DESIGN_RULES_FILE.exists() else "Design rules not found."
    packs = "\n".join(no_ai_pack_for_term(r, catalogue) for r in selected)
    trend_note = "Open UK trends not captured this run."
    if trending_data:
        web = trending_data.get("web", {})
        yt = trending_data.get("youtube", {})
        captured = web.get("top", []) + web.get("rising", []) + yt.get("top", []) + yt.get("rising", [])
        if captured:
            trend_note = "Raw trend ideas available for inspiration: " + ", ".join(captured[:10])

    md = f"""# Rock On Ruby - No-AI Visibility and Content Packs
Generated: {date_str}
Run `python3 content_generator.py --no-ai` to regenerate from cached trend data.

This file does not use Claude. It creates structured visibility actions and production packs from cached product, keyword and trend data.

Ranking data is not connected yet. Any ranking-related diagnosis is inferred until Google Search Console or live rank checking is added.

---

## System Focus

Improve organic visibility for products and pages ROR already sells, then create content only where it supports a product, page, season, keyword gap or conversion goal.

## Trend Note

{trend_note}

## How To Read The Evidence

**Trend score:** 8-10 is Green and should be prioritised when the page mapping is right. 5-7 is Amber and useful when it connects to an existing product, page or seasonal moment. 0-4 is Grey and should usually be monitored rather than actioned.

**Search interest estimate:** 70-100 is Green and means strong search interest. 30-69 is Amber and means moderate search interest that can still be useful for page optimisation. 1-29 is Grey and low interest, so only use it if it supports a commercial priority. 0 means no reliable live interest was captured.

**Trend direction:** Rising means interest is increasing compared with the earlier part of the tracking window. Stable means no clear movement. Falling means interest is dropping.

**Ranking data:** Not connected yet. Until Google Search Console or live rank checks are added, ranking-related comments are inferred and should be treated as review prompts, not proven rankings.

## Design Rules Summary

Use `design_system/ror_design_rules.md` as the source for palette, type mood and content pack visual direction.

{design_note.split('## Content Pack Design Output')[0].strip()}

---

# Visibility Actions and Production Packs

{packs}

---

Generated by ROR Content Generator no-AI mode.
"""
    CONTENT_FILE.write_text(md, encoding="utf-8")
    print(f"  No-AI content pack: {CONTENT_FILE}")
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


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Generate ROR content drafts.")
    parser.add_argument(
        "--no-ai",
        action="store_true",
        help="Generate structured visibility and content packs without calling Claude.",
    )
    args = parser.parse_args()
    if args.no_ai:
        generate_no_ai_content()
    else:
        generate_content()
