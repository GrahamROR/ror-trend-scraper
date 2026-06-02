"""
Rock On Ruby - Serper rank tracker

Uses Search Console opportunities to spot-check live Google UK rankings.

Run:
  SERPER_API_KEY=... .venv/bin/python rank_tracker.py

or, if SERPER_API_KEY is already exported:
  .venv/bin/python rank_tracker.py
"""

from __future__ import annotations

import argparse
import json
import os
import time
from datetime import datetime
from pathlib import Path
from urllib.parse import urlparse

import requests

OUTPUT_DIR = Path(__file__).parent
GSC_CACHE_FILE = OUTPUT_DIR / "search_console_cache.json"
RANK_CACHE_FILE = OUTPUT_DIR / "rank_tracker_cache.json"

SERPER_URL = "https://google.serper.dev/search"
ROR_DOMAIN = "rockonruby.co.uk"


def load_gsc_cache() -> dict:
    if not GSC_CACHE_FILE.exists():
        raise FileNotFoundError("search_console_cache.json not found. Run search_console.py first.")
    return json.loads(GSC_CACHE_FILE.read_text(encoding="utf-8"))


def pick_priority_keywords(gsc_cache: dict, limit: int) -> list[dict]:
    candidates: list[dict] = []
    seen: set[str] = set()

    def add(row: dict, reason: str) -> None:
        query = row.get("query", "").strip()
        if not query or query in seen:
            return
        seen.add(query)
        candidates.append(
            {
                "query": query,
                "target_page": row.get("page", ""),
                "gsc_clicks": row.get("clicks", 0),
                "gsc_impressions": row.get("impressions", 0),
                "gsc_ctr": row.get("ctr", 0),
                "gsc_position": row.get("position", 0),
                "reason": reason,
            }
        )

    opps = gsc_cache.get("opportunities", {})
    for row in opps.get("striking_distance", []):
        add(row, "GSC position 8-20 opportunity")
        if len(candidates) >= limit:
            return candidates

    for row in opps.get("high_impressions_low_ctr", []):
        add(row, "GSC high impressions, low CTR")
        if len(candidates) >= limit:
            return candidates

    for row in gsc_cache.get("query_pages", []):
        if row.get("impressions", 0) >= 50:
            add(row, "GSC fallback high-impression query/page")
        if len(candidates) >= limit:
            break

    return candidates


def result_domain(link: str) -> str:
    try:
        return urlparse(link).netloc.replace("www.", "")
    except Exception:
        return ""


def search_serper(query: str, api_key: str, num: int = 20) -> dict:
    payload = {
        "q": query,
        "gl": "uk",
        "hl": "en",
        "location": "United Kingdom",
        "num": num,
    }
    headers = {
        "X-API-KEY": api_key,
        "Content-Type": "application/json",
    }
    resp = requests.post(SERPER_URL, headers=headers, json=payload, timeout=30)
    if not resp.ok:
        try:
            body = resp.json()
        except Exception:
            body = {"raw": resp.text[:500]}
        return {
            "serper_error": {
                "status_code": resp.status_code,
                "message": body.get("error") or body.get("message") or body,
            }
        }
    return resp.json()


def analyse_serp(query_info: dict, serp: dict) -> dict:
    if serp.get("serper_error"):
        return {
            **query_info,
            "checked_at": datetime.now().isoformat(timespec="seconds"),
            "serper_error": serp["serper_error"],
            "ror_found": False,
            "ror_rank": None,
            "ror_url": "",
            "competitors_above": [],
            "top_results": [],
        }

    organic = serp.get("organic_results", [])
    if not organic:
        organic = serp.get("organic", [])
    ror_result = None
    competitors_above = []

    for result in organic:
        link = result.get("link", "")
        domain = result_domain(link)
        position = result.get("position")
        item = {
            "position": position,
            "title": result.get("title", ""),
            "link": link,
            "domain": domain,
        }
        if ROR_DOMAIN in domain:
            if ror_result is None:
                ror_result = item
        elif ror_result is None and position:
            competitors_above.append(item)

    return {
        **query_info,
        "checked_at": datetime.now().isoformat(timespec="seconds"),
        "rank_source": "serper",
        "organic_result_count": len(organic),
        "serper_response_keys": sorted(serp.keys()),
        "ror_found": ror_result is not None,
        "ror_rank": ror_result.get("position") if ror_result else None,
        "ror_url": ror_result.get("link") if ror_result else "",
        "competitors_above": competitors_above[:8],
        "top_results": [
            {
                "position": result.get("position"),
                "title": result.get("title", ""),
                "link": result.get("link", ""),
                "domain": result_domain(result.get("link", "")),
            }
            for result in organic[:10]
        ],
    }


def run_rank_tracker(limit: int, sleep_seconds: float) -> dict:
    api_key = os.environ.get("SERPER_API_KEY", "").strip().strip('"').strip("'")
    if not api_key:
        raise RuntimeError("SERPER_API_KEY is not set. Export it in Terminal before running rank_tracker.py.")

    gsc_cache = load_gsc_cache()
    keywords = pick_priority_keywords(gsc_cache, limit)
    results = []

    for i, query_info in enumerate(keywords, 1):
        query = query_info["query"]
        print(f"  {i}/{len(keywords)} Checking: {query}")
        serp = search_serper(query, api_key)
        analysed = analyse_serp(query_info, serp)
        results.append(analysed)
        if analysed.get("serper_error"):
            error = analysed["serper_error"]
            print(f"    Serper error {error.get('status_code')}: {error.get('message')}")
            if error.get("status_code") == 429:
                print("    Stopping early to avoid burning retries. Check Serper credits or wait for quota reset.")
                break
        if i < len(keywords) and sleep_seconds:
            time.sleep(sleep_seconds)

    cache = {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "source_gsc_window": {
            "site_url": gsc_cache.get("site_url"),
            "start_date": gsc_cache.get("start_date"),
            "end_date": gsc_cache.get("end_date"),
        },
        "limit": limit,
        "results": results,
    }
    RANK_CACHE_FILE.write_text(json.dumps(cache, indent=2), encoding="utf-8")
    return cache


def print_summary(cache: dict) -> None:
    print("\n-- Serper Rank Tracker --")
    print(f"Generated: {cache['generated_at']}")
    print(f"Keywords checked: {len(cache['results'])}")
    for row in cache["results"][:15]:
        if row.get("serper_error"):
            print(f"  {row['query']} | Serper error {row['serper_error'].get('status_code')}: {row['serper_error'].get('message')}")
            continue
        rank = row["ror_rank"] if row["ror_rank"] is not None else "not top 20"
        print(
            f"  {row['query']} | GSC pos {row['gsc_position']} | live rank {rank} | {row['gsc_impressions']} impressions"
        )
    print(f"\nSaved: {RANK_CACHE_FILE}")


def main() -> int:
    parser = argparse.ArgumentParser(description="Spot-check live Google UK rankings via Serper.")
    parser.add_argument("--limit", type=int, default=20, help="Number of priority GSC keywords to check. Default 20.")
    parser.add_argument("--sleep", type=float, default=0.5, help="Seconds to pause between Serper calls. Default 0.5.")
    args = parser.parse_args()

    cache = run_rank_tracker(args.limit, args.sleep)
    print_summary(cache)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
