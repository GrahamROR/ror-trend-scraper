# ROR Content Creator System Plan

Created: 2026-06-01

## Goal

Build a blog-led content production system for Rock On Ruby.

The current content layer creates useful blog drafts, but the social output is too thin. The next version should turn each approved blog/calendar idea into a full production-ready content pack.

## Core Principle

The blog is the source asset.

The content system should not create isolated captions. It should start with a planned blog or SEO idea, then derive the useful content around it:

- Reels
- Stories
- Carousels
- Emails
- Trial reels
- Competitions or list-growth mechanics, only when they genuinely fit

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

## Main Files

- `content_generator.py`
- `clickup_tasks.py`
- `content_history.json`
- `ror_focus.json`
- `trend_cache.json`
