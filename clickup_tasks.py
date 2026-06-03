"""
Rock On Ruby — ClickUp Task Creator
Parses the weekly content draft and creates tasks in ClickUp for Bethan.
Called from the GitHub Actions workflow after content generation.

Required env vars:
  CLICKUP_API_KEY  — ClickUp personal API token (GitHub secret)
  CLICKUP_LIST_ID_2 — ClickUp list ID to create tasks in (GitHub variable)
  CLICKUP_LIST_ID   — fallback ClickUp list ID, kept for older setups
"""

import os
import re
import sys
import requests
from datetime import datetime, timedelta
from pathlib import Path

API_KEY      = os.environ.get("CLICKUP_API_KEY", "")
LIST_ID      = os.environ.get("CLICKUP_LIST_ID_2") or os.environ.get("CLICKUP_LIST_ID", "")
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
    """
    Parse content packs into parent tasks with subtasks.
    Only processes packs with '### Approved ClickUp Task Breakdown'.
    Each pack becomes one parent task + 8 subtasks.
    """
    packs = []

    for pack_match in re.finditer(
        r"^## (?!System Focus|Trend Note|How this works|Design Rules)([^\n]+)\n+(.*?)(?=\n^## |\Z)",
        md, re.DOTALL | re.MULTILINE
    ):
        keyword = pack_match.group(1).strip()
        body = pack_match.group(2).strip()

        # Only push approved packs
        task_breakdown = re.search(
            r"### Approved ClickUp Task Breakdown\n+(.*?)(?=\n### |\Z)",
            body, re.DOTALL
        )
        if not task_breakdown:
            continue

        breakdown_text = task_breakdown.group(1).strip()

        # Extract evidence/context for parent task description
        evidence_match = re.search(r"### Evidence\n+(.*?)(?=\n### |\Z)", body, re.DOTALL)
        evidence_text = evidence_match.group(1).strip() if evidence_match else ""

        outline_match = re.search(r"### Blog Outline.*?\n+(.*?)(?=\n### |\Z)", body, re.DOTALL)
        outline_text = outline_match.group(1).strip() if outline_match else ""

        # Parse subtasks from the breakdown block
        subtasks = []
        for task_match in re.finditer(
            r"\*\*Task name:\*\*\s*(.+?)(?=\n\*\*Task name:\*\*|\Z)",
            breakdown_text, re.DOTALL
        ):
            block = task_match.group(1).strip()
            lines = block.splitlines()
            name = lines[0].strip()

            fields = {}
            content_lines = []
            in_content = False

            for line in lines[1:]:
                m = re.match(
                    r"\*\*(Type tag|Priority|Date created|Suggested due date|Task summary):\*\*\s*(.+)",
                    line.strip()
                )
                if m:
                    fields[m.group(1).lower()] = m.group(2).strip()
                    in_content = False
                elif line.strip() == "" and not in_content:
                    in_content = True
                else:
                    content_lines.append(line)

            task_type = clean_task_type(fields.get("type tag", "content"))
            priority_label = fields.get("priority", "Medium")
            due_ms = date_to_ms(fields.get("suggested due date", ""))
            summary = fields.get("task summary", "")
            extra_content = "\n".join(content_lines).strip()

            description = f"""KEYWORD: {keyword}
TYPE: {task_type}
PRIORITY: {priority_label}

WHAT TO DO:
{summary}

BRIEF:
{extra_content}

---
BLOG OUTLINE (source of truth for tone and story):
{outline_text}
""".strip()

            subtasks.append({
                "name": name,
                "description": description,
                "tags": [task_type, "content-pack"],
                "priority": priority_label,
                "due_ms": due_ms,
            })

        if subtasks:
            parent_description = f"""CONTENT PACK: {keyword}

EVIDENCE:
{evidence_text}

BLOG OUTLINE (source of truth — all formats tell this same story):
{outline_text}

SUBTASKS: {len(subtasks)} tasks created below.
Blog → Page Copy → Email → Reel → Stories → Carousel → TikTok → Pinterest

Each subtask contains a complete brief. Bethan should be able to execute each one without a briefing call.
""".strip()

            packs.append({
                "parent_name": f"Content Pack: {keyword}",
                "parent_description": parent_description,
                "tags": ["content-pack", "visibility"],
                "priority": subtasks[0]["priority"] if subtasks else "Medium",
                "due_ms": subtasks[0]["due_ms"] if subtasks else None,
                "subtasks": subtasks,
            })

    return packs

def create_task(task: dict, assignee: int | None, due_ms: int) -> str | None:
    """Create a ClickUp task and return its ID, or None on failure."""
    task_due = task.get("due_ms") or due_ms

    payload: dict = {
        "name": task["name"],
        "description": task["description"],
        "due_date": task_due,
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
            task_id = resp.json().get("id", "")
            task_url = resp.json().get("url", "")
            print(f"  + Parent: {task['name']} → {task_url}")
            return task_id
        print(f"  x Parent failed: {task['name']} — {resp.status_code}: {resp.text[:120]}")
    except Exception as e:
        print(f"  x Parent failed: {task['name']} — {e}")
    return None


def create_subtask(subtask: dict, parent_id: str, assignee: int | None, due_ms: int) -> bool:
    """Create a ClickUp subtask under a parent task."""
    task_due = subtask.get("due_ms") or due_ms

    payload: dict = {
        "name": subtask["name"],
        "description": subtask["description"],
        "due_date": task_due,
        "due_date_time": True,
    }

    priority_id = clickup_priority(subtask.get("priority", ""))
    if priority_id:
        payload["priority"] = priority_id

    if subtask.get("tags"):
        payload["tags"] = subtask["tags"]

    if assignee:
        payload["assignees"] = [assignee]

    try:
        resp = requests.post(
            f"{BASE_URL}/task/{parent_id}/subtask",
            headers=HEADERS,
            json=payload,
            timeout=15,
        )
        if resp.ok:
            print(f"    - Subtask: {subtask['name']}")
            return True
        print(f"    x Subtask failed: {subtask['name']} — {resp.status_code}: {resp.text[:80]}")
    except Exception as e:
        print(f"    x Subtask failed: {subtask['name']} — {e}")
    return False

def main() -> int:
    if not API_KEY:
        print("\nCLICKUP_API_KEY not set — skipping ClickUp task creation.")
        return 0

    if not LIST_ID:
        print("\nCLICKUP_LIST_ID_2 or CLICKUP_LIST_ID not set — skipping ClickUp task creation.")
        return 0

    if not CONTENT_FILE.exists():
        print("\nror_content_draft.md not found — skipping ClickUp task creation.")
        return 0

    print("\n-- ClickUp Task Creation --")

    md = CONTENT_FILE.read_text(encoding="utf-8")
    packs = parse_sections(md)

    if not packs:
        print(" No approved content packs found in ror_content_draft.md.")
        print(" Packs need '### Approved ClickUp Task Breakdown' to be pushed.")
        return 0

    print(f" Found {len(packs)} approved content pack(s)")

    bethan = find_bethan()
    print(f" Bethan: {'found (id=' + str(bethan) + ')' if bethan else 'not found — tasks will be unassigned'}")

    due_ms = next_friday_ms()
    days = (4 - datetime.utcnow().weekday()) % 7 or 7
    friday = datetime.utcnow() + timedelta(days=days)
    print(f" Due: Friday {friday.strftime('%d %b %Y')}")

    total_parents = 0
    total_subtasks = 0
    failed = 0

    for pack in packs:
        print(f"\n  Pack: {pack['parent_name']}")

        parent_id = create_task(
            {"name": pack["parent_name"], "description": pack["parent_description"],
             "tags": pack["tags"], "priority": pack["priority"], "due_ms": pack["due_ms"]},
            bethan, due_ms
        )

        if not parent_id:
            failed += 1
            continue

        total_parents += 1

        for subtask in pack["subtasks"]:
            ok = create_subtask(subtask, parent_id, bethan, due_ms)
            if ok:
                total_subtasks += 1
            else:
                failed += 1

    print(f"\n  {total_parents} parent tasks created")
    print(f"  {total_subtasks} subtasks created")
    if failed:
        print(f"  {failed} failures — check output above")

    return 0 if failed == 0 else 1

if __name__ == "__main__":
    sys.exit(main())
