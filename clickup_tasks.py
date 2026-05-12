"""
Rock On Ruby — ClickUp Task Creator
Parses the weekly content draft and creates tasks in ClickUp for Bethan.
Called from the GitHub Actions workflow after content generation.

Required env vars:
  CLICKUP_API_KEY  — ClickUp personal API token (GitHub secret)
  CLICKUP_LIST_ID  — ClickUp list ID to create tasks in (GitHub variable)
"""

import os
import re
import sys
import requests
from datetime import datetime, timedelta
from pathlib import Path

API_KEY      = os.environ.get("CLICKUP_API_KEY", "")
LIST_ID      = os.environ.get("CLICKUP_LIST_ID", "")
CONTENT_FILE = Path(__file__).parent / "ror_content_draft.md"
BASE_URL     = "https://api.clickup.com/api/v2"
HEADERS      = {"Authorization": API_KEY, "Content-Type": "application/json"}


def next_friday_ms() -> int:
    today = datetime.utcnow()
    days  = (4 - today.weekday()) % 7 or 7
    friday = (today + timedelta(days=days)).replace(hour=17, minute=0, second=0, microsecond=0)
    return int(friday.timestamp() * 1000)


def find_bethan() -> int | None:
    try:
        resp = requests.get(f"{BASE_URL}/team", headers=HEADERS, timeout=10)
        if not resp.ok:
            return None
        for team in resp.json().get("teams", []):
            for m in team.get("members", []):
                u = m.get("user", {})
                name  = u.get("username", "").lower()
                email = u.get("email", "").lower()
                if "bethan" in name or "bethan" in email:
                    return u["id"]
    except Exception as e:
        print(f"  ClickUp: could not look up Bethan — {e}")
    return None


def parse_sections(md: str) -> list[dict]:
    tasks = []
    today = datetime.utcnow().strftime("%d %b")

    # Blog posts
    for m in re.finditer(r"## BLOG POST (\d+)\n+(.*?)(?=\n## |\Z)", md, re.DOTALL):
        tasks.append({
            "name":        f"[Blog] Draft {m.group(1)} — {today}",
            "description": m.group(2).strip(),
        })

    # Social captions — Claude numbers them; split on Caption N header patterns
    social = re.search(r"## SOCIAL CAPTIONS\n+(.*?)(?=\n## |\Z)", md, re.DOTALL)
    if social:
        captions = re.split(r"\n(?=\*\*Caption \d|\bCaption \d|\d\.\s)", social.group(1))
        captions = [c.strip() for c in captions if len(c.strip()) > 30][:5]
        for i, c in enumerate(captions, 1):
            tasks.append({
                "name":        f"[Social] Caption {i} — {today}",
                "description": c,
            })

    # Email subject lines — one task per subject/preview pair
    email = re.search(r"## EMAIL SUBJECT LINES\n+(.*?)(?=\n## |\Z)", md, re.DOTALL)
    if email:
        pairs = re.findall(
            r"\*\*Subject:\*\*\s*(.+?)\n\*\*Preview text:\*\*\s*(.+?)(?=\n\*\*Subject|\Z)",
            email.group(1), re.DOTALL,
        )
        if pairs:
            for i, (subj, preview) in enumerate(pairs[:3], 1):
                tasks.append({
                    "name": f"[Email] Subject line {i} — {today}",
                    "description": f"**Subject:** {subj.strip()}\n\n**Preview text:** {preview.strip()}",
                })
        else:
            tasks.append({
                "name":        f"[Email] Subject lines — {today}",
                "description": email.group(1).strip(),
            })

    return tasks


def create_task(task: dict, assignee: int | None, due_ms: int) -> bool:
    payload: dict = {
        "name":          task["name"],
        "description":   task["description"],
        "due_date":      due_ms,
        "due_date_time": True,
    }
    if assignee:
        payload["assignees"] = [assignee]

    try:
        resp = requests.post(
            f"{BASE_URL}/list/{LIST_ID}/task",
            headers=HEADERS,
            json=payload,
            timeout=15,
        )
        if resp.ok:
            print(f"  + {task['name']}  →  {resp.json().get('url', '')}")
            return True
        print(f"  x {task['name']}  —  {resp.status_code}: {resp.text[:120]}")
    except Exception as e:
        print(f"  x {task['name']}  —  {e}")
    return False


def main() -> int:
    if not API_KEY:
        print("\nCLICKUP_API_KEY not set — skipping ClickUp task creation.")
        return 0
    if not LIST_ID:
        print("\nCLICKUP_LIST_ID not set — skipping ClickUp task creation.")
        return 0
    if not CONTENT_FILE.exists():
        print("\nror_content_draft.md not found — skipping ClickUp task creation.")
        return 0

    print("\n-- ClickUp Task Creation --")
    md    = CONTENT_FILE.read_text(encoding="utf-8")
    tasks = parse_sections(md)
    print(f"  Parsed {len(tasks)} tasks from content draft")

    bethan = find_bethan()
    print(f"  Bethan: {'found (id=' + str(bethan) + ')' if bethan else 'not found — tasks will be unassigned'}")

    due_ms = next_friday_ms()
    days   = (4 - datetime.utcnow().weekday()) % 7 or 7
    friday = datetime.utcnow() + timedelta(days=days)
    print(f"  Due: Friday {friday.strftime('%d %b %Y')}")

    results = [create_task(t, bethan, due_ms) for t in tasks]
    print(f"  {sum(results)}/{len(results)} tasks created.")
    return 0 if all(results) else 1


if __name__ == "__main__":
    sys.exit(main())
