"""
Rock On Ruby — Weather Content Generator
Fetches 7-day forecast for Bury, Manchester via Open-Meteo (free, no API key).
Applies IF rules to detect noteworthy weather stories.
Generates 1 blog + 1 email + 1 carousel if a story is found.
Skips if weather is unremarkable or ran last week.

Weather trigger rules:
  SUN/HEAT:
    - 3+ days >= 20°C → heatwave
    - 5+ days of sunshine (clear/mostly clear) → rare British summer
    - First 18°C+ day after 7-day cold stretch (< 12°C) → spring arrival

  RAIN:
    - 5+ rainy days → classic British summer
    - Heavy rain (>10mm) on 2+ days → hiding indoors
    - Rain on a UK Bank Holiday weekend (detected by date)

  CHAOS (the funny one):
    - Temp swing >= 10°C within the 7-day window → four seasons in one day
    - Any day >= 18°C AND any day <= 10°C in same week → classic British chaos

  WIND:
    - 2+ days with max wind >= 50 km/h → storm content

  DO NOTHING if:
    - Weather ran last week already
    - No trigger conditions met (grey drizzle, 12–15°C, nothing notable)
"""

import os
import re
import json
import requests
from datetime import datetime, timedelta, timezone
from pathlib import Path

import anthropic as anthropic_lib

ANTHROPIC_KEY  = os.environ.get("ANTHROPIC_API_KEY", "")
CLICKUP_KEY    = os.environ.get("CLICKUP_API_KEY", "")
INBOX_LIST_ID  = os.environ.get("CLICKUP_LIST_ID", "901217534962")

CLICKUP_BASE    = "https://api.clickup.com/api/v2"
CLICKUP_HEADERS = {"Authorization": CLICKUP_KEY, "Content-Type": "application/json"}
HISTORY_FILE    = Path(__file__).parent / "content_history.json"

BURY_LAT  = 53.5933
BURY_LON  = -2.2977

UK_BANK_HOLIDAYS_APPROX = [
    "01-01", "25-12", "26-12",
]

BRAND_CONTEXT = """
BRAND: Rock On Ruby — personalised print-on-demand clothing and accessories.
Based in Bury, Manchester. Made to order in 1-2 days.
PRODUCTS: Sweatshirts, hoodies, t-shirts, caps, tote bags, make-up bags, slogan clothing.
CUSTOMER: UK women, 30-50. Warm, funny, slightly chaotic.
WEBSITE: rockonruby.co.uk
""".strip()

HOLLY_VOICE = """
HOLLY'S VOICE RULES:
- Short paragraphs. One idea per paragraph. Three sentences max.
- Conversational. Holly is talking to her sister, not a boardroom.
- UK spelling: personalised, colour, favourite.
- Contractions always: it's, you're, we've.
- Self-deprecating, warm British humour. Never forced.
- Never swear. Never corporate. Never influencer.
- No bullet points in body copy. No em dashes. No semicolons.
- Max one exclamation mark per piece.
- Never sound like AI wrote it.
- Sign off: Love Team ROR x
""".strip()

WEATHER_PRODUCT_MAP = {
    "heatwave":     ["Personalised Year Unisex T-shirt", "Blah Blah Blah Slogan T-shirt", "Embroidered Yes I Like Pina Coladas T-shirt", "Personalised Slogan T-shirt"],
    "rare_summer":  ["Personalised Year Unisex T-shirt", "Vintage Style Denim Unisex Personalised Slogan Cap", "Personalised 'Only Here For...' Cap"],
    "spring":       ["Personalised Year Unisex T-shirt", "Always Time for a Good Time Sweatshirt", "Personalised Slogan T-shirt"],
    "rain":         ["Personalised Year Sweatshirt", "9pm Bedtime Club Sweatshirt", "Always Time for a Good Time Sweatshirt"],
    "hiding":       ["Personalised Year Sweatshirt", "Blah Blah Blah Slogan T-shirt", "9pm Bedtime Club Sweatshirt"],
    "bank_holiday": ["Personalised Year Sweatshirt", "Personalised Year Unisex T-shirt", "Personalised 'Only Here For...' Cap"],
    "chaos":        ["Personalised Year Sweatshirt", "Personalised Year Unisex T-shirt", "Always Time for a Good Time Sweatshirt"],
    "storm":        ["Personalised Year Sweatshirt", "9pm Bedtime Club Sweatshirt", "Blah Blah Blah Slogan T-shirt"],
}

CAROUSEL_STYLE = """
ROR CAROUSEL STYLE:
- Template: BOLD_STATEMENT (solid colour bg, one punchy line per slide, 8-9 slides)
- Format: "Happy [Weather Event] to..." opener, one archetype per slide, warm payoff at end
- Tone: self-deprecating British humour, first person plural, never salesy
- Sign off every caption: Team ROR x
- Max 4 hashtags, specific not spammy
- Typography: heavy all-caps display font for headlines, casual script for asides
""".strip()


# ── Forecast fetcher ──────────────────────────────────────────────────────────

def fetch_forecast() -> dict | None:
    url = "https://api.open-meteo.com/v1/forecast"
    params = {
        "latitude":  BURY_LAT,
        "longitude": BURY_LON,
        "daily": [
            "temperature_2m_max",
            "temperature_2m_min",
            "precipitation_sum",
            "windspeed_10m_max",
            "weathercode",
        ],
        "timezone":   "Europe/London",
        "forecast_days": 7,
    }
    try:
        resp = requests.get(url, params=params, timeout=15)
        if resp.ok:
            return resp.json()
        print(f"  Open-Meteo error: {resp.status_code}")
    except Exception as e:
        print(f"  Open-Meteo fetch failed: {e}")
    return None


def parse_forecast(data: dict) -> list[dict]:
    daily = data.get("daily", {})
    dates         = daily.get("time", [])
    temps_max     = daily.get("temperature_2m_max", [])
    temps_min     = daily.get("temperature_2m_min", [])
    precip        = daily.get("precipitation_sum", [])
    wind          = daily.get("windspeed_10m_max", [])
    weathercodes  = daily.get("weathercode", [])

    days = []
    for i, date in enumerate(dates):
        days.append({
            "date":      date,
            "temp_max":  temps_max[i] if i < len(temps_max) else None,
            "temp_min":  temps_min[i] if i < len(temps_min) else None,
            "precip":    precip[i] if i < len(precip) else 0,
            "wind":      wind[i] if i < len(wind) else 0,
            "code":      weathercodes[i] if i < len(weathercodes) else 0,
            "is_sunny":  weathercodes[i] in [0, 1] if i < len(weathercodes) else False,
            "is_rainy":  weathercodes[i] in [51,53,55,61,63,65,71,73,75,80,81,82,95,96,99] if i < len(weathercodes) else False,
        })
    return days


def is_bank_holiday_weekend(days: list[dict]) -> bool:
    for d in days:
        date_str = d["date"]
        try:
            dt = datetime.strptime(date_str, "%Y-%m-%d")
            mmdd = dt.strftime("%d-%m") if False else f"{dt.day:02d}-{dt.month:02d}"
            day_mmdd = f"{dt.month:02d}-{dt.day:02d}"
            if day_mmdd in UK_BANK_HOLIDAYS_APPROX:
                return True
            if dt.weekday() in (5, 6):
                for bh in UK_BANK_HOLIDAYS_APPROX:
                    m, d_num = bh.split("-")
                    bh_dt = datetime(dt.year, int(m), int(d_num))
                    if abs((bh_dt - dt).days) <= 2:
                        return True
        except Exception:
            continue
    return False


# ── Trigger detection ─────────────────────────────────────────────────────────

def detect_weather_story(days: list[dict]) -> dict | None:
    temps_max = [d["temp_max"] for d in days if d["temp_max"] is not None]
    if not temps_max:
        return None

    max_temp  = max(temps_max)
    min_temp  = min(d["temp_min"] for d in days if d["temp_min"] is not None)
    temp_swing = max_temp - min_temp

    sunny_days  = sum(1 for d in days if d["is_sunny"])
    rainy_days  = sum(1 for d in days if d["is_rainy"])
    heavy_rain  = sum(1 for d in days if (d["precip"] or 0) > 10)
    windy_days  = sum(1 for d in days if (d["wind"] or 0) >= 50)
    hot_days    = sum(1 for d in days if (d["temp_max"] or 0) >= 20)
    cold_days   = sum(1 for d in days if (d["temp_max"] or 0) <= 10)

    # Priority order — most interesting story wins
    # 1. Four seasons in one day (the funniest)
    if temp_swing >= 10 and hot_days >= 1 and cold_days >= 1:
        return {
            "story":    "chaos",
            "headline": "four seasons in one day",
            "angle":    f"The forecast this week swings from {min_temp:.0f}°C to {max_temp:.0f}°C. Classic.",
            "products": WEATHER_PRODUCT_MAP["chaos"],
        }

    # 2. Heatwave
    if hot_days >= 3:
        return {
            "story":    "heatwave",
            "headline": f"{hot_days}-day heatwave incoming",
            "angle":    f"Multiple days forecast above 20°C in Bury this week. The nation will panic.",
            "products": WEATHER_PRODUCT_MAP["heatwave"],
        }

    # 3. Storm
    if windy_days >= 2:
        return {
            "story":    "storm",
            "headline": "storm incoming",
            "angle":    f"Wind speeds hitting 50km/h+ on {windy_days} days this week.",
            "products": WEATHER_PRODUCT_MAP["storm"],
        }

    # 4. Bank holiday rain (peak British experience)
    if is_bank_holiday_weekend(days) and rainy_days >= 2:
        return {
            "story":    "bank_holiday",
            "headline": "bank holiday rain (obviously)",
            "angle":    "Bank holiday weekend + rain forecast. Britain, never change.",
            "products": WEATHER_PRODUCT_MAP["bank_holiday"],
        }

    # 5. Heavy rain
    if heavy_rain >= 2:
        return {
            "story":    "hiding",
            "headline": "hiding indoors weather",
            "angle":    f"Heavy rain forecast on {heavy_rain} days this week. Cosy clothing weather.",
            "products": WEATHER_PRODUCT_MAP["hiding"],
        }

    # 6. Relentless rain
    if rainy_days >= 5:
        return {
            "story":    "rain",
            "headline": "classic British summer",
            "angle":    f"{rainy_days} out of 7 days forecast rainy in Manchester. Nothing new there.",
            "products": WEATHER_PRODUCT_MAP["rain"],
        }

    # 7. Rare sunshine
    if sunny_days >= 5:
        return {
            "story":    "rare_summer",
            "headline": "rare British sunshine",
            "angle":    f"{sunny_days} sunny days forecast. The UK will treat this as a national event.",
            "products": WEATHER_PRODUCT_MAP["rare_summer"],
        }

    # 8. Spring arrival (first warm day after cold spell)
    if max_temp >= 18 and min_temp <= 8 and hot_days == 1:
        return {
            "story":    "spring",
            "headline": "spring has arrived (for one day)",
            "angle":    f"One glorious day forecast at {max_temp:.0f}°C before it goes cold again.",
            "products": WEATHER_PRODUCT_MAP["spring"],
        }

    return None


def weather_ran_last_week(history: dict) -> bool:
    cutoff = (datetime.now() - timedelta(days=8)).strftime("%Y-%m-%d")
    return any(
        e.get("date", "") >= cutoff
        for e in history.get("weather", [])
    )


# ── Content generation ────────────────────────────────────────────────────────

def claude_call(system: str, prompt: str, max_tokens: int = 4000) -> str:
    client = anthropic_lib.Anthropic(api_key=ANTHROPIC_KEY)
    msg = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=max_tokens,
        system=system,
        messages=[{"role": "user", "content": prompt}],
    )
    return msg.content[0].text.strip()


def generate_weather_blog(story: dict, catalogue_summary: str) -> str:
    system = f"""{BRAND_CONTEXT}

{HOLLY_VOICE}

You write funny, warm, very British blog posts for Rock On Ruby about UK weather.
The humour is self-deprecating and observational — laughing WITH the reader, not at them.
Always tie back to ROR products naturally, never forcefully.
Structure: conversational opening → weather observation (funny) → product tie-in → FAQ → CTA.
Target 700-900 words. SEO-friendly H1, H2s phrased as questions people search.
UK spelling throughout. Local references to Manchester/Bury where natural.
"""

    prompt = f"""
Write a blog post for Rock On Ruby about this week's weather story.

WEATHER STORY: {story['headline']}
ANGLE: {story['angle']}
FEATURED PRODUCTS: {', '.join(story['products'][:3])}

{catalogue_summary}

The blog should:
- Open with a funny, relatable observation about this specific weather situation
- Reference the fact we're based in Manchester (this is extremely on-brand)
- Weave in 2-3 ROR products naturally — not as a list, as part of the story
- Include an FAQ section at the bottom (4 questions, very Holly voice)
- End with a gentle CTA to rockonruby.co.uk

Make it funny. Make it feel like Holly wrote it at 10pm after checking the weather app and laughing.
""".strip()

    return claude_call(system, prompt, max_tokens=4000)


def generate_weather_email(story: dict, catalogue_summary: str) -> dict:
    system = f"""{BRAND_CONTEXT}

{HOLLY_VOICE}

You write complete Klaviyo-ready marketing emails for Rock On Ruby.
Every email is a story, not an announcement. Funny, warm, British.

OUTPUT FORMAT — return exactly this, nothing else:
SUBJECT: [subject line]
PREVIEW: [preview text]
---
[full email body starting with Hey {{{{first_name}}}},]
"""

    prompt = f"""
Write a complete Rock On Ruby marketing email based on this week's weather.

WEATHER STORY: {story['headline']}
ANGLE: {story['angle']}
FEATURED PRODUCTS: {', '.join(story['products'][:2])}

{catalogue_summary}

The email should:
- Open with a relatable weather observation (Hey first_name, ...)
- Build a funny story around the specific weather situation
- Introduce 1-2 ROR products naturally within the story
- End with a conversational CTA link
- P.S. line that's punchy and weather-related
- Love Team ROR x sign-off

Make it feel timely — like Holly spotted the forecast this morning and had to write about it.
""".strip()

    raw = claude_call(system, prompt, max_tokens=2000)

    subject = ""
    preview = ""
    subject_match = re.search(r"^SUBJECT:\s*(.+)$", raw, re.MULTILINE)
    preview_match = re.search(r"^PREVIEW:\s*(.+)$", raw, re.MULTILINE)
    if subject_match:
        subject = subject_match.group(1).strip()
    if preview_match:
        preview = preview_match.group(1).strip()

    body = re.sub(r"^SUBJECT:.*\n?", "", raw, flags=re.MULTILINE)
    body = re.sub(r"^PREVIEW:.*\n?", "", body, flags=re.MULTILINE)
    body = re.sub(r"^---\n?", "", body, flags=re.MULTILINE)
    body = body.strip()

    if not subject:
        subject = f"About this week's weather..."

    return {"subject": subject, "preview": preview, "body": body}


def generate_weather_carousel(story: dict, days: list[dict]) -> str:
    week_temps = [d["temp_max"] for d in days if d["temp_max"]]
    temp_range = f"{min(week_temps):.0f}°C–{max(week_temps):.0f}°C" if week_temps else "variable"

    system = f"""{BRAND_CONTEXT}

{CAROUSEL_STYLE}

You write Instagram carousel slide copy for Rock On Ruby.
The "Happy X to..." format: opener slide, 6-7 archetype slides (one joke each), warm payoff close.
Every slide: SHORT. Punchy. All caps headline. Optional script aside in italics.
British humour. Warm. Never mean. Always funny.
"""

    prompt = f"""
Write a complete Instagram carousel for Rock On Ruby about this week's weather.

WEATHER STORY: {story['headline']}
ANGLE: {story['angle']}
TEMPERATURE RANGE THIS WEEK: {temp_range}
FEATURED PRODUCT TIE-IN: {story['products'][0]}

Write exactly 9 slides following the "Happy [weather event] to..." format.

Return EXACTLY this format for each slide:

SLIDE 1 — COVER
HEADLINE: [opener — e.g. "HAPPY FOUR SEASONS IN ONE DAY TO..."]
ASIDE: [optional script aside]

SLIDE 2
HEADLINE: [archetype 1]
ASIDE: [optional]

(continue through slide 9)

SLIDE 9 — PAYOFF
HEADLINE: [warm funny close]
ASIDE: [optional]

CAPTION:
[full Instagram caption]

HASHTAGS:
[2-4 hashtags]

CANVA_NOTES:
[2-3 practical notes for Bethan]
""".strip()

    return claude_call(system, prompt, max_tokens=2000)


# ── ClickUp push ──────────────────────────────────────────────────────────────

def push_weather_task(name: str, description: str, tags: list[str], due_ms: int) -> bool:
    payload = {
        "name": name,
        "description": description,
        "due_date": due_ms,
        "due_date_time": True,
        "status": "generated",
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
            print(f"  + {name}")
            print(f"    {resp.json().get('url', '')}")
            return True
        print(f"  x Failed: {name} — {resp.status_code}: {resp.text[:100]}")
    except Exception as e:
        print(f"  x Error: {name} — {e}")
    return False


# ── Main entry point ──────────────────────────────────────────────────────────

def run_weather_generator(due_ms: int, history: dict, catalogue_summary: str) -> int:
    """
    Main function called from content_generator.py.
    Returns count of tasks pushed (0, 1, 2 or 3).
    """
    print("\n  -- Weather Content Generator --")

    # Skip if ran last week
    if weather_ran_last_week(history):
        print("  Ran last week — skipping.")
        return 0

    # Fetch forecast
    print("  Fetching 7-day forecast for Bury, Manchester...")
    forecast_data = fetch_forecast()
    if not forecast_data:
        print("  Forecast unavailable — skipping.")
        return 0

    days = parse_forecast(forecast_data)
    if not days:
        print("  No forecast days parsed — skipping.")
        return 0

    # Log the week's forecast
    temps = [f"{d['date']}: {d['temp_max']:.0f}°C" for d in days if d["temp_max"]]
    print(f"  Forecast: {', '.join(temps[:4])}...")

    # Detect story
    story = detect_weather_story(days)
    if not story:
        print("  No notable weather story this week — skipping.")
        return 0

    print(f"  Weather story detected: {story['headline']}")

    today = datetime.now().strftime("%d %b")
    pushed = 0

    # Blog
    print("  Writing weather blog...")
    try:
        blog = generate_weather_blog(story, catalogue_summary)
        ok = push_weather_task(
            name=f"[Weather Blog] {story['headline'].title()} — {today}",
            description=f"WEATHER TRIGGER: {story['story']}\nANGLE: {story['angle']}\nPRODUCTS: {', '.join(story['products'][:3])}\n\n---\n\n{blog}\n\n---\nLove Team ROR x",
            tags=["blog", "weather"],
            due_ms=due_ms,
        )
        if ok:
            pushed += 1
    except Exception as e:
        print(f"  x Weather blog failed: {e}")

    # Email
    print("  Writing weather email...")
    try:
        email = generate_weather_email(story, catalogue_summary)
        ok = push_weather_task(
            name=f"[Weather Email] {email['subject']} — {today}",
            description=f"SUBJECT: {email['subject']}\nPREVIEW TEXT: {email['preview']}\nWEATHER TRIGGER: {story['story']}\n\n---\n\n{email['body']}",
            tags=["email", "weather"],
            due_ms=due_ms,
        )
        if ok:
            pushed += 1
    except Exception as e:
        print(f"  x Weather email failed: {e}")

    # Carousel
    print("  Writing weather carousel...")
    try:
        carousel = generate_weather_carousel(story, days)
        ok = push_weather_task(
            name=f"[Weather Carousel] {story['headline'].title()} — {today}",
            description=f"WEATHER TRIGGER: {story['story']}\nTEMPLATURE RANGE: {min(d['temp_max'] for d in days if d['temp_max']):.0f}–{max(d['temp_max'] for d in days if d['temp_max']):.0f}°C\n\n---\n\n{carousel}",
            tags=["carousel", "weather", "social"],
            due_ms=due_ms,
        )
        if ok:
            pushed += 1
    except Exception as e:
        print(f"  x Weather carousel failed: {e}")

    # Record in history
    if pushed > 0:
        history.setdefault("weather", []).append({
            "date": datetime.now().strftime("%Y-%m-%d"),
            "story": story["story"],
            "headline": story["headline"],
            "tasks_pushed": pushed,
        })
        # Prune to last 90 days
        cutoff = (datetime.now() - timedelta(days=90)).strftime("%Y-%m-%d")
        history["weather"] = [e for e in history["weather"] if e.get("date", "") >= cutoff]

    print(f"  Weather content: {pushed}/3 tasks pushed")
    return pushed
