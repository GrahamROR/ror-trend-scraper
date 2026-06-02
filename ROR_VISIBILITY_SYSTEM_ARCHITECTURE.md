# ROR Organic Visibility and Content Execution System

Created: 2026-06-02

## Core Objective

The system exists to improve Rock On Ruby organic visibility and turn the resulting work into tasks the team can execute.

It should answer five questions before it creates content:

1. What do we sell on rockonruby.co.uk?
2. Which pages and products should rank for which searches?
3. Where do those pages and keywords rank now?
4. What is weak, missing or unclear?
5. What exact work should the team do next?

Trends, calendars and creative ideas are supporting inputs. They help timing, hooks and content angles, but they should not be the main decision engine.

## System Shape

```text
Products and pages
  -> Keyword targets
  -> Ranking and visibility data
  -> Gap diagnosis
  -> Exact action cards
  -> Content execution packs
  -> Finished content
  -> Approved ClickUp delivery
```

## Dashboard Tabs

### Action Plan

The first tab should show the work to do this week.

Every action must include:

- Page or product
- Target keyword
- Current evidence
- Problem
- Exact change to make
- Suggested copy or structure
- Internal links to add
- Content support needed
- Priority
- Owner
- ClickUp draft status

Avoid vague wording such as "improve collection copy" unless the card also says exactly what to improve and gives a suggested structure or draft.

### Search Visibility

This tab should show where ROR is visible already and where it is weak.

Required future inputs:

- Google Search Console clicks
- Google Search Console impressions
- Google Search Console average position
- Query to page mapping
- Live rank checks for priority keywords, using SerpApi, DataForSEO or a similar source

Until this data is connected, the dashboard must clearly label ranking data as not connected.

### Products and Pages

This tab should answer what ROR sells and which page is supposed to rank.

It should include:

- Shopify product
- Shopify collection
- Product URL or collection URL
- Primary keyword
- Secondary keywords
- Current page role
- Missing page flags
- Weak page flags
- Suggested internal links

### Keyword Gaps

This tab should show keywords people search for where ROR has weak or missing coverage.

Gap types:

- Missing product page
- Missing collection page
- Existing page does not target the keyword clearly
- Existing page targets too many unrelated keywords
- Blog needed to support a product or collection
- FAQ needed because the query is question-led
- Internal links missing
- Backlink or authority gap

### Content Packs

Content is the execution layer for visibility work.

A content pack should start from one approved visibility opportunity, blog topic, product priority or calendar moment. It should not create isolated captions.

Possible outputs:

- Blog
- Email
- Reel
- Story sequence
- Carousel
- TikTok
- Pinterest pins
- Optional competition or list-growth mechanic

Not every idea needs every format. The system should choose only the formats that naturally fit.

### Calendar

The calendar should show commercial timing.

Inputs:

- Annual gifting moments
- Collection drops
- Email calendar
- Content calendar
- Production calendar
- Launch notes

The calendar should help the system decide when an action matters, not create work for the sake of filling dates.

### Trends

Trends stay in the system as inspiration and timing signals.

They should include:

- Raw UK web top searches
- Raw UK web rising searches
- Raw UK YouTube top searches
- Raw UK YouTube rising searches
- ROR programmed keyword tracking

Open trends must not be mixed with ROR keyword tracking. If a trend has a natural product connection, use it. If not, ignore it.

### Team Ideas

Team input should come from ClickUp, not JSON files.

Useful inputs:

- Customer questions
- TikTok or Instagram observations
- Product ideas
- Launch notes
- Competitor observations
- Repeated support questions
- Creative angles

Team ideas are signals. They do not override search visibility data.

## Exact Action Card Format

Use this format for every recommendation:

```text
ACTION TITLE
Rewrite Personalised Sweatshirts collection intro for birthday search intent

PAGE OR PRODUCT
Personalised Sweatshirts collection

TARGET KEYWORD
personalised birthday sweatshirt

EVIDENCE
Ranking position 12 once ranking data is connected. Current inferred issue until then.

PROBLEM
The page reads like a general personalised clothing page. It does not clearly answer birthday gift searches.

DO THIS
Rewrite the first 80 words so they mention personalised birthday sweatshirt, milestone birthdays, birth year sweatshirts, 30th, 40th and 50th birthday gifts, gift-ready wording and UK delivery.

SUGGESTED COPY
Draft copy or outline goes here.

INTERNAL LINKS TO ADD
Link from relevant blogs, gift collections and birthday pages to the target page.

CONTENT SUPPORT
Create one supporting blog, one Reel and one Pinterest pin set if the keyword has enough value.

OWNER
Bethan, Holly or Graham.

PRIORITY
High, medium or low.

CLICKUP STATUS
Draft, review, approved, sent to ClickUp, done.
```

## Ranking Data Plan

The current scraper does not know where ROR ranks on Google.

To answer ranking questions properly, add:

1. Google Search Console, for real ROR queries, clicks, impressions and average position.
2. SerpApi or DataForSEO, for live rank checks on priority keywords.
3. Keyword to page mapping, so the system knows which URL should rank.

Without this data, the system can still create inferred actions, but they must be labelled as inferred.

## Content Pack Architecture

Keep the existing blog and email approach, but expand each approved idea into a production pack.

The team should not be asked to write content from scratch. The system should create the first usable draft from the evidence, then Bethan and Holly check, lightly edit where needed and place it in the right channel. Graham checks SEO intent and page mapping when an action is marked for review.

Blogs are the source asset. In Claude mode, each selected blog should be generated in two passes: first a rough Holly-voice draft, then an SEO specialist pass that adds H1, H2, H3, long-tail keywords, local SEO, buyer scenarios, product depth, FAQs and a natural CTA. The finished Pass 2 blog then becomes the basis for email, social and production tasks.

Production wording must be accurate. Rock On Ruby uses both DTF full-colour print and embroidery. Customer-facing copy should usually say full-colour print rather than DTF. Do not imply every product is embroidered.

Each pack should include:

- Visibility goal
- Product or collection
- Target keyword
- Seasonal or trend angle
- Blog draft or blog brief
- Email copy or email prompt
- Reel concept, hook, script and shot list
- Stories frame plan
- Carousel slide plan
- TikTok adaptation
- Pinterest titles and descriptions
- Design direction
- CTA links
- ClickUp task breakdown

## Design Direction Layer

The design layer comes from `design_system/colors_and_type.css` and `design_system/ror_design_rules.md`.

Each content pack should include:

- Palette
- Typography mood
- Layout treatment
- Photography or video notes
- Canva notes
- Avoid notes

Example:

Father's Day should lean into beige, black, navy, army green and orange. It should feel practical, bold and giftable, not soft or twee.

## ClickUp Flow

ClickUp is for finished content and approved tasks only. Nothing half-baked should be pushed to ClickUp.

Flow:

```text
Generated evidence
  -> Draft inside repo/dashboard
  -> Review
  -> Finished content
  -> Approved ClickUp task
  -> Done or skipped
```

Static GitHub Pages can show draft/review buttons, but real button behaviour needs a workflow trigger, API endpoint or small app layer. Until then, the system should only create ClickUp-ready exports for approved finished content.

Every content task sent to ClickUp must include:

- Task name starting with the asset type, for example Blog, Reel, Email, Stories, Carousel, TikTok or Pinterest.
- Type tag matching the asset type.
- Priority.
- Date created.
- Due date.
- Keyword or visibility opportunity.
- Product or target page.
- Clear execution summary.
- Full production context.

Task wording should say review, approve, place, schedule or publish the system-generated content. It should not imply Bethan needs to write the content from scratch.

Draft or no-AI planning packs must not use the `Approved ClickUp Task Breakdown` heading. That heading is reserved for finished content that is safe to push into ClickUp.

## Build Order

1. Add design architecture to the repo.
2. Add no-AI content pack generation.
3. Reframe dashboard tabs around visibility.
4. Replace generic weekly actions with exact action cards.
5. Expand content packs into blog, email, Reel, Stories, Carousel, TikTok and Pinterest.
6. Add ranking data inputs.
7. Add ClickUp draft and review flow.
