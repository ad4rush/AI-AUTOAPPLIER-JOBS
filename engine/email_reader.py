#!/usr/bin/env python3
"""
Autonomous Email Reader & Inbox Inspector Plugin.
Operates via ego-browser on:
- Profile 1 ("Main Profile" -> CANDIDATE_PERSONAL_EMAIL from .env)
- Profile 2 ("COLLEGE PROFILE" -> CANDIDATE_COLLEGE_EMAIL from .env)

Fetches the top N emails deterministically, supports full message body reading,
keyword searching, and unread status detection.
"""

import sys
import json
import argparse
import subprocess
from pathlib import Path
from typing import Dict, Any, List, Optional

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from engine.config import (
    EGO_BROWSER_MAIN_PROFILE_ID,
    EGO_BROWSER_COLLEGE_PROFILE_ID,
    CANDIDATE_PERSONAL_EMAIL,
    CANDIDATE_COLLEGE_EMAIL,
)

PROFILES_CONFIG = {
    "personal": {
        "profile_id": EGO_BROWSER_MAIN_PROFILE_ID,  # "Profile 1"
        "task_space": "email_reader_personal",
        "email": CANDIDATE_PERSONAL_EMAIL,
        "display_name": f"Personal Inbox ({CANDIDATE_PERSONAL_EMAIL})"
    },
    "college": {
        "profile_id": EGO_BROWSER_COLLEGE_PROFILE_ID,  # "Profile 2"
        "task_space": "email_reader_college",
        "email": CANDIDATE_COLLEGE_EMAIL,
        "display_name": f"College Inbox ({CANDIDATE_COLLEGE_EMAIL})"
    }
}


def _run_node_script(script_content: str, timeout: int = 60) -> Dict[str, Any]:
    """Executes a JavaScript automation script via ego-browser nodejs."""
    try:
        proc = subprocess.run(
            ["ego-browser", "nodejs"],
            input=script_content,
            text=True,
            capture_output=True,
            timeout=timeout
        )
        combined = (proc.stdout or "") + "\n" + (proc.stderr or "")
        json_lines = []
        for line in combined.splitlines():
            line = line.strip()
            if line.startswith("JSON_RESULT:"):
                payload = line.replace("JSON_RESULT:", "", 1).strip()
                try:
                    return json.loads(payload)
                except Exception:
                    pass
            elif line.startswith("{") and line.endswith("}"):
                try:
                    parsed = json.loads(line)
                    if "success" in parsed or "emails" in parsed:
                        return parsed
                except Exception:
                    continue
        return {"success": False, "raw_output": combined, "error": "No JSON payload found"}
    except Exception as e:
        return {"success": False, "error": str(e)}


def fetch_profile_emails(profile_key: Optional[str] = None, limit: int = 10, search_query: Optional[str] = None, profile: Optional[str] = None, **kwargs) -> Dict[str, Any]:
    """
    Fetches the top N emails from the specified Gmail profile inbox.
    """
    profile_key = profile_key or profile or "personal"
    if profile_key not in PROFILES_CONFIG:
        return {"success": False, "error": f"Unknown profile '{profile_key}'. Available: {list(PROFILES_CONFIG.keys())}"}

    cfg = PROFILES_CONFIG[profile_key]
    profile_id = cfg["profile_id"]
    task_space = cfg["task_space"]
    email_addr = cfg["email"]

    node_script = f"""
const spaces = await listTaskSpaces();
let existing = spaces.find(s => s.name === "{task_space}");
let task;
if (existing) {{
  if (existing.ownership === "agent") {{
    task = await taskSpace(existing.id);
  }} else {{
    try {{
      task = await takeOverTaskSpace(existing.id);
    }} catch(e) {{
      task = await taskSpace("{task_space}_" + Date.now(), {{ profileId: "{profile_id}" }});
    }}
  }}
}} else {{
  task = await taskSpace("{task_space}", {{ profileId: "{profile_id}" }});
}}

const page = task.page("p1");
const currentUrl = await page.url();

if (!currentUrl.includes("mail.google.com")) {{
  await page.goto("https://mail.google.com/mail/u/0/#inbox", {{ waitUntil: "domcontentloaded", timeout: 35000 }});
  await new Promise(r => setTimeout(r, 4000));
}} else if (!currentUrl.includes("#inbox")) {{
  await page.goto("https://mail.google.com/mail/u/0/#inbox", {{ waitUntil: "domcontentloaded", timeout: 35000 }});
  await new Promise(r => setTimeout(r, 3000));
}} else {{
  await page.reload({{ waitUntil: "domcontentloaded" }});
  await new Promise(r => setTimeout(r, 3000));
}}

const emails = await page.evaluate((maxCount) => {{
  const rows = Array.from(document.querySelectorAll("tr.zA"));
  return rows.slice(0, maxCount).map((row, idx) => {{
    const isUnread = row.classList.contains("zE");
    const senderElem = row.querySelector(".yX, .zF, .bA4 span");
    let sender = senderElem ? senderElem.innerText.trim() : (row.querySelector(".yP, .zF")?.innerText.trim() || "Unknown");
    sender = sender.split("\\n")[0].trim();
    const subjectElem = row.querySelector(".bog, span[data-thread-id]");
    const subject = subjectElem ? subjectElem.innerText.trim() : "No Subject";
    const snippetElem = row.querySelector(".y2");
    let snippet = snippetElem ? snippetElem.innerText.replace(/^[\\s\\-\\:\\u00A0]+/, "").trim() : "";
    const dateElem = row.querySelector(".xW span, .xW");
    const date = dateElem ? (dateElem.getAttribute("title") || dateElem.innerText.trim()) : "";
    return {{
      index: idx + 1,
      isUnread,
      sender,
      subject,
      snippet,
      date
    }};
  }});
}}, {max(limit, 30)});

console.log("JSON_RESULT:" + JSON.stringify({{
  success: true,
  profile: "{profile_key}",
  account: "{email_addr}",
  emails: emails
}}));
"""
    result = _run_node_script(node_script, timeout=60)
    if not result.get("success"):
        return result

    all_emails = result.get("emails", [])

    # In-memory keyword filtering if search query requested
    if search_query:
        q = search_query.strip().lower()
        filtered = [
            e for e in all_emails
            if q in e["sender"].lower() or q in e["subject"].lower() or q in e["snippet"].lower()
        ]
        result["emails"] = filtered[:limit]
        result["total_matches"] = len(filtered)
    else:
        result["emails"] = all_emails[:limit]

    return result


def fetch_inbox_emails(profile: str = "all", limit: int = 10, search_query: Optional[str] = None) -> Dict[str, Any]:
    """
    Fetches top N emails from personal, college, or both profiles.
    """
    results = {}
    if profile in ("personal", "all"):
        print(f"[*] Checking Personal Inbox (Profile 1: {PROFILES_CONFIG['personal']['email']})...")
        results["personal"] = fetch_profile_emails("personal", limit=limit, search_query=search_query)

    if profile in ("college", "all"):
        print(f"[*] Checking College Inbox (Profile 2: {PROFILES_CONFIG['college']['email']})...")
        results["college"] = fetch_profile_emails("college", limit=limit, search_query=search_query)

    return results


def read_email_message(profile_key: str = "college", index: int = 1) -> Dict[str, Any]:
    """
    Navigates to and reads the full message body of the email at index `index` (1-indexed).
    Then safely navigates back to the inbox.
    """
    if profile_key not in PROFILES_CONFIG:
        return {"success": False, "error": f"Unknown profile '{profile_key}'"}

    cfg = PROFILES_CONFIG[profile_key]
    profile_id = cfg["profile_id"]
    task_space = cfg["task_space"]
    row_idx = max(0, index - 1)

    node_script = f"""
const spaces = await listTaskSpaces();
let existing = spaces.find(s => s.name === "{task_space}");
let task;
if (existing) {{
  if (existing.ownership === "agent") {{
    task = await taskSpace(existing.id);
  }} else {{
    try {{
      task = await takeOverTaskSpace(existing.id);
    }} catch(e) {{
      task = await taskSpace("{task_space}_" + Date.now(), {{ profileId: "{profile_id}" }});
    }}
  }}
}} else {{
  task = await taskSpace("{task_space}", {{ profileId: "{profile_id}" }});
}}

const page = task.page("p1");
const currentUrl = await page.url();

if (!currentUrl.includes("#inbox")) {{
  await page.goto("https://mail.google.com/mail/u/0/#inbox", {{ waitUntil: "domcontentloaded", timeout: 35000 }});
  await new Promise(r => setTimeout(r, 4000));
}}

// Click target row
const clicked = await page.evaluate((targetIdx) => {{
  const rows = document.querySelectorAll("tr.zA");
  if (rows.length > targetIdx) {{
    rows[targetIdx].click();
    return true;
  }}
  return false;
}}, {row_idx});

if (!clicked) {{
  console.log("JSON_RESULT:" + JSON.stringify({{ success: false, error: "Row index out of range" }}));
  process.exit(0);
}}

await new Promise(r => setTimeout(r, 3500));

const details = await page.evaluate(() => {{
  const subject = document.querySelector("h2.hP")?.innerText?.trim() || "";
  const senderName = document.querySelector("span.gD")?.innerText?.trim() || document.querySelector("span[email]")?.innerText?.trim() || "";
  const senderEmail = document.querySelector("span[email]")?.getAttribute("email") || "";
  const dateStr = document.querySelector(".g3")?.getAttribute("title") || document.querySelector(".g3")?.innerText?.trim() || "";
  const bodies = Array.from(document.querySelectorAll(".a3s.aiL, .a3s"));
  const bodyText = bodies.map(b => b.innerText.trim()).filter(Boolean).join("\\n\\n--- Thread Reply ---\\n\\n");

  return {{
    subject,
    senderName,
    senderEmail,
    date: dateStr,
    body: bodyText
  }};
}});

// Return to inbox so state is preserved
await page.goto("https://mail.google.com/mail/u/0/#inbox", {{ waitUntil: "domcontentloaded" }});

console.log("JSON_RESULT:" + JSON.stringify({{
  success: true,
  profile: "{profile_key}",
  index: {index},
  ...details
}}));
"""
    return _run_node_script(node_script, timeout=60)


def format_email_table(emails: List[Dict[str, Any]], title: str) -> str:
    """Formats emails into a readable terminal table."""
    lines = []
    lines.append("\n" + "=" * 90)
    lines.append(f"  {title.upper()}")
    lines.append("=" * 90)
    lines.append(f"{'#':<4} {'STATUS':<9} {'DATE':<10} {'SENDER':<22} {'SUBJECT'}")
    lines.append("-" * 90)

    if not emails:
        lines.append("  (No emails found matching criteria)")
        lines.append("=" * 90 + "\n")
        return "\n".join(lines)

    for e in emails:
        idx = f"[{e['index']}]"
        status = "● UNREAD" if e.get("isUnread") else "○ read"
        date = (e.get("date") or "")[:9]
        sender = (e.get("sender") or "")[:20]
        subject = e.get("subject") or "(No Subject)"
        if len(subject) > 42:
            subject = subject[:39] + "..."
        lines.append(f"{idx:<4} {status:<9} {date:<10} {sender:<22} {subject}")
        snippet = e.get("snippet", "")
        if snippet:
            clean_snippet = snippet.replace("\n", " ")
            if len(clean_snippet) > 82:
                clean_snippet = clean_snippet[:79] + "..."
            lines.append(f"     └─ {clean_snippet}")

    lines.append("=" * 90 + "\n")
    return "\n".join(lines)


def format_email_detail(detail: Dict[str, Any]) -> str:
    """Formats full email body for terminal display."""
    lines = []
    lines.append("\n" + "=" * 80)
    lines.append(f"EMAIL MESSAGE DETAIL (Index #{detail.get('index')})")
    lines.append("=" * 80)
    lines.append(f"  Profile : {detail.get('profile')}")
    lines.append(f"  Subject : {detail.get('subject')}")
    sender_str = detail.get('senderName', '')
    if detail.get('senderEmail'):
        sender_str += f" <{detail.get('senderEmail')}>"
    lines.append(f"  From    : {sender_str}")
    lines.append(f"  Date    : {detail.get('date')}")
    lines.append("-" * 80)
    lines.append("\n" + detail.get('body', '(Empty body)') + "\n")
    lines.append("=" * 80 + "\n")
    return "\n".join(lines)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Autonomous Email Inbox Reader (Personal & College)")
    parser.add_argument("--profile", choices=["personal", "college", "all"], default="all", help="Which Gmail profile to check")
    parser.add_argument("--limit", type=int, default=10, help="Number of emails to fetch (default: 10)")
    parser.add_argument("--search", help="Optional search query filter")
    parser.add_argument("--read", type=int, help="Read full message body of email at specified index")
    parser.add_argument("--json", action="store_true", help="Output raw JSON instead of table")
    args = parser.parse_args()

    if args.read:
        target_prof = "college" if args.profile == "all" else args.profile
        print(f"[*] Reading full body of email #{args.read} from {target_prof} profile...")
        detail = read_email_message(profile_key=target_prof, index=args.read)
        if args.json:
            print(json.dumps(detail, indent=2))
        else:
            if detail.get("success"):
                print(format_email_detail(detail))
            else:
                print(f"[!] Error reading email: {detail.get('error')}")
    else:
        results = fetch_inbox_emails(profile=args.profile, limit=args.limit, search_query=args.search)
        if args.json:
            print(json.dumps(results, indent=2))
        else:
            for prof_key, prof_res in results.items():
                if prof_res.get("success"):
                    title = PROFILES_CONFIG[prof_key]["display_name"]
                    if args.search:
                        title += f" [Filtered: '{args.search}']"
                    print(format_email_table(prof_res.get("emails", []), title))
                else:
                    print(f"[!] Failed to fetch emails for {prof_key}: {prof_res.get('error')}")
