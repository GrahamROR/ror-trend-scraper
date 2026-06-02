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


def date_to_ms(date_str: str) -> int | None:
    try:
        due = datetime.strptime(date_str.strip(), "%Y-%m-%d").replace(hour=17, minute=0, second=0, microsecond=0)
        return int(due.timestamp() * 1000)
    except Exception:
        return None


def clickup_priority(value: str) -> int | None:
    priorities = {
        "urgent": 1,
        "high": 2,
        "medium": 3,
        "normal": 3,
        "low": 4,
    }
    return priorities.get(value.strip().lower())


def clean_task_type(value: str) -> str:
    return re.sub(r"[^a-z0-9-]+", "-", value.strip().lower()).strip("-")


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

    # Approved production packs only. Draft/no-AI packs use "Draft Task Breakdown"
    # and must not be pushed into ClickUp.
    for pack in re.finditer(r"## (?!System Focus|Trend Note)([^\n]+)\n+(.*?)(?=\n## |\Z)", md, re.DOTALL):
        keyword = pack.group(1).strip()
        body = pack.group(2).strip()
        task_breakdown = re.search(r"### Approved ClickUp Task Breakdown\n+(.*?)(?=\n### |\Z)", body, re.DOTALL)
        if not task_breakdown:
            continue
        for task_match in re.finditer(r"\*\*Task name:\*\*\s*(.+?)(?=\n\*\*Task name:\*\*|\Z)", task_breakdown.group(1), re.DOTALL):
            block = task_match.group(1).strip()
            lines = [line.strip() for line in block.splitlines() if line.strip()]
            name = lines[0]
            fields = {}
            for line in lines[1:]:
                m = re.match(r"\*\*(Type tag|Priority|Date created|Suggested due date|Task summary):\*\*\s*(.+)", line)
                if m:
                    fields[m.group(1).lower()] = m.group(2).strip()
            task_type = clean_task_type(fields.get("type tag", "content"))
            priority_label = fields.get("priority", "Medium")
            due_ms = date_to_ms(fields.get("suggested due date", ""))
            summary = fields.get("task summary", "")
            description = f"""Keyword: {keyword}
Type: {task_type}
Priority: {priority_label}
Date created: {fields.get('date created', '')}
Suggested due date: {fields.get('suggested due date', '')}

{summary}

Full pack context:
{body}
"""
            tasks.append({
                "name": name,
                "description": description.strip(),
                "tags": [task_type, "content-pack", "visibility"],
                "priority": priority_label,
                "due_ms": due_ms,
            })

    if tasks:
        return tasks

    # Legacy Claude content sections. These are finished Claude outputs, not no-AI draft packs.
    for m in re.finditer(r"## BLOG POST (\d+)\n+(.*?)(?=\n## |\Z)", md, re.DOTALL):
        tasks.append({
            "name":        f"[Blog] Draft {m.group(1)} — {today}",
            "description": m.group(2).strip(),
            "tags":        ["blog"],
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
                "tags":        ["social"],
            })

    # Email design prompts — one task per full prompt block
    for m in re.finditer(r"## EMAIL DESIGN PROMPT (\d+)\n+(.*?)(?=\n## |\Z)", md, re.DOTALL):
        body = m.group(2).strip()
        # Extract subject for the task name
        subj_match = re.search(r"\*\*Subject:\*\*\s*(.+)", body)
        subj = subj_match.group(1).strip() if subj_match else f"Email prompt {m.group(1)}"
        tasks.append({
            "name":        f"[Email] {subj} — {today}",
            "description": body,
            "tags":        ["email"],
        })

    # SEO blog drafts — one task per draft
    seo_blog = re.search(r"## SEO CONTENT — BLOG DRAFTS\n+(.*?)(?=\n## |\Z)", md, re.DOTALL)
    if seo_blog:
        drafts = re.split(r"\n(?=---|\*\*Keyword|\*\*H1|# )", seo_blog.group(1))
        drafts = [d.strip() for d in drafts if len(d.strip()) > 60]
        for i, d in enumerate(drafts[:5], 1):
            first_line = d.split("\n")[0][:80].strip("# ").strip()
            tasks.append({
                "name":        f"[SEO Blog] {first_line} — {today}",
                "description": d,
                "tags":        ["blog", "seo"],
            })
        if not drafts:
            tasks.append({
                "name":        f"[SEO Blog] Drafts — {today}",
                "description": seo_blog.group(1).strip(),
                "tags":        ["blog", "seo"],
            })

    # SEO product page briefs — one task covering all briefs
    prod_seo = re.search(r"## SEO CONTENT — PRODUCT PAGE BRIEFS\n+(.*?)(?=\n## |\Z)", md, re.DOTALL)
    if prod_seo:
        tasks.append({
            "name":        f"[SEO Product] Page briefs — {today}",
            "description": prod_seo.group(1).strip(),
            "tags":        ["product-page", "seo"],
        })

    # SEO collection copy — one task covering all copy
    coll_seo = re.search(r"## SEO CONTENT — COLLECTION PAGE COPY\n+(.*?)(?=\n## |\Z)", md, re.DOTALL)
    if coll_seo:
        tasks.append({
            "name":        f"[SEO Collection] Page copy — {today}",
            "description": coll_seo.group(1).strip(),
            "tags":        ["collection-page", "seo"],
        })

    return tasks


def create_task(task: dict, assignee: int | None, due_ms: int) -> bool:
    task_due = task.get("due_ms") or due_ms
    payload: dict = {
        "name":          task["name"],
        "description":   task["description"],
        "due_date":      task_due,
        "due_date_time": True,
    }
    priority_id = clickup_priority(task.get("priority", ""))
    if priority_id:
        payload["priority"] = priority_id
    if task.get("tags"):
        payload["tags"] = task["tags"]
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
