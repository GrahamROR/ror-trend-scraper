# ROR Intelligence System Plan

Created: 2026-05-27

## Goal

Turn the current trend scraper into a weekly organic visibility and commercial intelligence system.

The controlling architecture now lives in `ROR_VISIBILITY_SYSTEM_ARCHITECTURE.md`. That document should be treated as the main source of truth.

The system should not just show data. It should show:

- Data: what Google, Shopify, Instagram, website content and search demand are showing.
- Interpretation: what that probably means for Rock On Ruby.
- Action: what Bethan, Holly or Graham should do next.

Actions must be specific enough to execute. For example, "improve collection copy" is not acceptable unless the system also explains what to change, where to put it, what keyword it supports, what links to add and what content should support it.

## First Priority

Fix the raw UK trending data layer.

The dashboard currently mixes general UK trends with related queries from programmed ROR keywords. These are useful, but they are not the same thing.

Target structure:

```json
{
  "open_trends": {
    "web": {
      "top": [],
      "rising": []
    },
    "youtube": {
      "top": [],
      "rising": []
    }
  },
  "programmed_keywords": {
    "groups": []
  }
}
```

Open trends should be raw, clearly labelled, and not used to filter dashboard data. Claude can use them as inspiration only.

## Team Input Layer

Start with a Level 2 input system using ClickUp as the accessible team inbox.

The team should not need to edit JSON files. They should be able to add ideas from ClickUp mobile, desktop, voice notes or eventually a form.

Created ClickUp list:

- Team Trend & Content Ideas Inbox
- https://app.clickup.com/90121649956/v/l/li/901218496536

Inputs can include:

- Trend ideas
- TikTok/Instagram observations
- Customer questions
- Blog angles
- Reel ideas
- Story/poll ideas
- Product push ideas
- Collection/drop notes
- Competitor observations
- Repeated customer service questions

The dashboard should eventually include links/buttons for:

- Add trend idea
- Add customer question
- Add content angle
- Add collection/drop note

Later, the scraper should fetch open team input tasks from ClickUp and include them in the opportunity engine.

Team inputs should not override data. They should act as extra signals alongside products, calendar, trends, website gaps and content history.

## Key Decision

Choose the data source for open trends.

Options:

- SerpApi or similar managed source: more reliable, likely better for commercial decision-making.
- pytrends: free, but brittle and may return empty or partial data.

Recommendation: use a stable source for open UK trends, while keeping pytrends for programmed ROR keyword tracking.

## Dashboard Direction

Move the dashboard towards:

```text
DATA
What was found.

INTERPRETATION
What it means for ROR.

ACTION
What to do next.
```

Bethan should not need to interpret a wall of trend cards.

## Content Layer Direction

Add two safeguards:

- Duplication guard: avoid repeating blog topics, caption angles, email angles and SEO recommendations.
- Content QA: scan generated copy for banned punctuation, banned phrases, repeated openings and obvious AI tone.

## Likely Code Changes

- Split open trend fetching from programmed keyword fetching.
- Update `trend_cache.json` shape while keeping backwards compatibility.
- Update dashboard renderer to show open trends separately.
- Add dashboard links/buttons for team input submission.
- Add a ClickUp/team input ingestion layer.
- Update Claude prompt builder to pass open trends as inspiration.
- Add content linting before saving or pushing content tasks to ClickUp.

## Main Files

- `scraper.py`
- `content_generator.py`
- `clickup_tasks.py`
- `ror_focus.json`
- `trend_cache.json`
- `content_history.json`
