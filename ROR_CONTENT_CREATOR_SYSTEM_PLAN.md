# ROR Content Creator System Plan

Created: 2026-06-01

## Goal

Build a blog-led content production system for Rock On Ruby.

The current content layer creates useful blog drafts, but the social output is too thin. The next version should turn each approved blog/calendar idea into a full production-ready content pack.

This plan now sits underneath `ROR_VISIBILITY_SYSTEM_ARCHITECTURE.md`. Content should be created because it supports a visibility gap, product priority, page improvement, seasonal moment or collection launch. It should not create disconnected captions for the sake of filling channels.

## Core Principle

The blog is the source asset.

The content system should not create isolated captions. It should start with a planned blog or SEO idea, then derive the useful content around it:

- Reels
- Stories
- Carousels
- Emails
- Trial reels
- Competitions or list-growth mechanics, only when they genuinely fit

The system writes the first usable version from the evidence. Bethan and Holly should receive content to review, approve, schedule or publish, not a blank task asking them to write from scratch.

ClickUp is for finished content and approved tasks only. Draft planning packs, no-AI evidence packs and unapproved ideas must stay in the repo/dashboard review flow.

Product wording must be accurate. ROR uses both DTF full-colour print and embroidery. Customer-facing content should usually say full-colour print rather than DTF, and should only mention embroidery when the exact product is embroidered.

## Blog Generation

Finished blogs use a two-pass Claude workflow.

Pass 1 creates a rough conversational blog draft from the evidence in Holly's voice. It should be chatty, warm, self-deprecating, UK humour, short paragraphs, never corporate and never salesy.

Pass 2 immediately feeds that rough draft back into Claude as an SEO specialist for Rock On Ruby. Pass 2 must preserve Holly's tone while adding:

- H1, H2 and H3 structure
- H2 headings phrased as buyer search questions
- 600 to 800 words minimum
- Specific year and seasonal dates where relevant
- Long-tail keyword phrases from the actual topic
- Bury, Manchester
- UK-wide shipping or delivered across the UK
- Buyer scenarios specific to the topic
- Personalisation examples
- Quality comparison against cheap alternatives
- Fully written FAQ section with at least 4 topic-specific questions
- Natural low-pressure CTA to rockonruby.co.uk

Only Pass 2 is saved to the markdown file and ClickUp. Pass 1 is discarded.

Email, Reel, Stories, Carousel, TikTok and Pinterest content should derive from the finished Pass 2 blog, not from separate disconnected prompts.

## Required Inputs

- Annual gifting calendar
- ROR collection/drop calendar
- Approved SEO/blog topic
- Product or collection links
- AOV/conversion goal
- Trend notes from the ROR Intelligence System
- Team input notes from ClickUp
- Existing content history, so angles are not repeated

## Team Input Layer

The team should be able to add useful observations without touching repo files.

Starting point:

- ClickUp list: Team Trend & Content Ideas Inbox
- URL: https://app.clickup.com/90121649956/v/l/li/901218496536

Team notes can become content signals when they connect to:

- A seasonal moment
- An existing ROR product
- A planned launch/drop
- A repeated customer question
- A trending topic
- A website/product clarity gap

The Content Creator System should use these notes to add human context to campaign packs, not to force every idea into content.

## Production Pack Output

Each approved content idea should produce a campaign pack with only the formats that make sense.

### Blog

- H1/title
- SEO title
- Meta description
- Full draft
- Internal links
- CTA
- Product or collection links

### Reel

- Reel concept
- Hook
- On-screen title
- Full script
- Shot list
- B-roll list
- Product/props needed
- Caption
- CTA
- Cover text

### Stories

- Frame-by-frame plan
- Poll/question/sticker suggestions where useful
- Link sticker destination
- Visual notes
- Copy for each frame

### Carousel

- Slide titles
- Slide-by-slide copy
- Design notes
- Caption
- CTA

### Email

- Subject line
- Preview text
- Story angle
- Section-by-section copy or prompt
- CTA and links

### Optional Growth Mechanics

Only include these when they make sense:

- Competition idea
- Email list growth mechanic
- UGC prompt
- Trial reel/testing idea

### Design Direction

- Palette from `design_system/ror_design_rules.md`
- Type mood
- Layout treatment
- Shot notes
- Canva notes
- Avoid notes

For example, a Father's Day content pack should lean into beige, black, navy, army green, orange and dark teal rather than defaulting to the softer pink-led brand palette.

## Decision Rule

Not every blog needs every format.

The system should choose outputs based on:

- Season
- Product relevance
- Audience fit
- AOV or conversion opportunity
- Available creative effort
- Whether the format naturally works

## Target Flow

```text
Intelligence System
  -> Calendar priority
  -> Blog/SEO idea
  -> Team/context notes
  -> Campaign angle
  -> Production pack
  -> ClickUp tasks Bethan can execute
```

## Likely Code Changes

- Update `content_generator.py` so social/email/carousel output is derived from blog-led campaign packs.
- Add a content calendar input layer.
- Add a campaign pack prompt template.
- Add format-selection logic so Claude does not produce every asset every time.
- Update `clickup_tasks.py` so tasks include scripts, shot lists, assets, links and clear production instructions.
- Extend `content_history.json` to track angles, not just keywords.

## ClickUp Task Naming

When content is pushed to ClickUp, each asset must become its own task with a clear type-led name:

- Blog: [keyword or campaign]
- Email: [keyword or campaign]
- Reel: [keyword or campaign]
- Stories: [keyword or campaign]
- Carousel: [keyword or campaign]
- TikTok: [keyword or campaign]
- Pinterest: [keyword or campaign]

Each task should include a matching type tag, priority, date created, suggested due date, keyword, target page and execution summary.

Only approved finished content should use the `Approved ClickUp Task Breakdown` export format. Draft task breakdowns must not be parsed into ClickUp.

## Main Files

- `content_generator.py`
- `clickup_tasks.py`
- `content_history.json`
- `ror_focus.json`
- `trend_cache.json`
