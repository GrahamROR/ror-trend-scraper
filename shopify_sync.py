"""
Rock On Ruby — Shopify Catalogue Sync
Fetches live collections, products, and bestsellers from Shopify Admin API.
Saves shopify_catalogue.json — used by scraper.py and content_generator.py
to map trends to real product URLs and write content with actual links.

Requires:
  SHOPIFY_ACCESS_TOKEN — Admin API token (GitHub secret)
  SHOPIFY_STORE_DOMAIN — optional, defaults to rockonruby.myshopify.com
"""

import os
import json
import re
import requests
from datetime import datetime, timedelta
from pathlib import Path

DOMAIN         = os.environ.get("SHOPIFY_STORE_DOMAIN", "rockonruby.myshopify.com")
TOKEN          = os.environ.get("SHOPIFY_ACCESS_TOKEN", "")
OUTPUT_DIR     = Path(__file__).parent
CATALOGUE_FILE = OUTPUT_DIR / "shopify_catalogue.json"
BASE           = f"https://{DOMAIN}/admin/api/2024-01"
HEADERS        = {"X-Shopify-Access-Token": TOKEN, "Content-Type": "application/json"}
SITE           = "rockonruby.co.uk"

# Product types to skip — these are personalisation add-ons, not real products
_SKIP_TYPES    = {"personalisation", "gift box", "personalisation add-on"}
_SKIP_HANDLE   = re.compile(r"^option-set-|^add-|additional-personalisation")
_SKIP_TITLE    = re.compile(r"^(add |4\. |2nd line|add back|add date|add image|add initials|add personalisation|add spotify|checkbox$)", re.I)


def _paginate(url: str, key: str, params: dict | None = None) -> list:
    """Paginate a Shopify REST endpoint following Link headers."""
    results = []
    p = dict(params or {})
    p.setdefault("limit", 250)
    while url:
        resp = requests.get(url, headers=HEADERS, params=p, timeout=20)
        if not resp.ok:
            print(f"  Shopify {resp.status_code}: {resp.text[:100]}")
            break
        results.extend(resp.json().get(key, []))
        url = None
        p = {}
        link = resp.headers.get("Link", "")
        if 'rel="next"' in link:
            for part in link.split(","):
                if 'rel="next"' in part:
                    url = part.strip().split(";")[0].strip("<> ")
                    break
    return results


def _is_real_product(p: dict) -> bool:
    ptype  = (p.get("product_type") or "").lower().strip()
    handle = p.get("handle", "")
    title  = p.get("title", "")
    if ptype in _SKIP_TYPES:
        return False
    if _SKIP_HANDLE.search(handle):
        return False
    if _SKIP_TITLE.search(title):
        return False
    return True


def fetch_collections() -> list[dict]:
    print("  Fetching collections...")
    custom = _paginate(f"{BASE}/custom_collections.json", "custom_collections",
                       {"published_status": "published"})
    smart  = _paginate(f"{BASE}/smart_collections.json",  "smart_collections",
                       {"published_status": "published"})
    out = []
    for c in custom + smart:
        out.append({
            "title":  c["title"],
            "handle": c["handle"],
            "url":    f"{SITE}/collections/{c['handle']}",
        })
    out.sort(key=lambda x: x["title"])
    print(f"  → {len(out)} collections")
    return out


def fetch_products(max_products: int = 500) -> list[dict]:
    print("  Fetching products...")
    raw = _paginate(f"{BASE}/products.json", "products",
                    {"status": "active", "limit": 250})
    out = []
    for p in raw:
        if not _is_real_product(p):
            continue
        tags = [t.strip() for t in (p.get("tags") or "").split(",") if t.strip()]
        price = None
        try:
            price = float(p["variants"][0]["price"])
        except (KeyError, IndexError, ValueError):
            pass
        out.append({
            "title":        p["title"],
            "handle":       p["handle"],
            "url":          f"{SITE}/products/{p['handle']}",
            "product_type": p.get("product_type", ""),
            "tags":         tags,
            "price":        price,
        })
        if len(out) >= max_products:
            break
    print(f"  → {len(out)} real products (from {len(raw)} total)")
    return out


def fetch_bestsellers(days: int = 90) -> list[dict]:
    print(f"  Fetching bestsellers (last {days} days)...")
    since = (datetime.utcnow() - timedelta(days=days)).strftime("%Y-%m-%dT%H:%M:%SZ")
    orders = _paginate(
        f"{BASE}/orders.json", "orders",
        {"status": "any", "financial_status": "paid",
         "created_at_min": since, "fields": "line_items", "limit": 250},
    )
    tally: dict[int, dict] = {}
    for order in orders:
        for item in order.get("line_items", []):
            pid   = item.get("product_id")
            title = item.get("title", "")
            if not pid:
                continue
            if _SKIP_TITLE.search(title):
                continue
            qty   = item.get("quantity", 1)
            price = float(item.get("price", 0))
            if pid not in tally:
                tally[pid] = {"title": title, "handle": "", "orders": 0, "revenue": 0.0}
            tally[pid]["orders"]  += 1
            tally[pid]["revenue"] += price * qty

    ranked = sorted(tally.values(), key=lambda x: -x["revenue"])[:20]
    for b in ranked:
        b["revenue"] = round(b["revenue"], 2)
    print(f"  → {len(ranked)} bestsellers identified from {len(orders)} orders")
    return ranked


def main() -> None:
    if not TOKEN:
        print("SHOPIFY_ACCESS_TOKEN not set — skipping Shopify sync.")
        return

    print("-- Shopify Catalogue Sync --")
    collections = fetch_collections()
    products    = fetch_products()
    bestsellers = fetch_bestsellers()

    catalogue = {
        "synced_at":   datetime.utcnow().isoformat(),
        "collections": collections,
        "products":    products,
        "bestsellers": bestsellers,
    }
    CATALOGUE_FILE.write_text(json.dumps(catalogue, indent=2))
    print(f"  Catalogue → {CATALOGUE_FILE}")
    print(f"  ({len(collections)} collections · {len(products)} products · {len(bestsellers)} bestsellers)")


if __name__ == "__main__":
    main()
