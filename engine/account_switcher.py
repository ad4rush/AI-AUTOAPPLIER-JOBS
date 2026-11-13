#!/usr/bin/env python3
"""
Autonomous Account Switcher & Profile Routing Engine.
Stores the deterministic mapping of services, portals, and ATS platforms to browser profiles:
- Profile 1 ("Main Profile" -> CANDIDATE_PERSONAL_EMAIL from .env):
  Mercor, ChatGPT, DataAnnotation, Turing, Alignerr, Outlier, Microsoft, Personal Gmail.
- Profile 2 ("College Profile" -> CANDIDATE_COLLEGE_EMAIL from .env):
  LinkedIn, College Gmail, University Portals.

Provides programmatic API and CLI helpers for:
- Deterministic profile resolution: get_profile_for_service(service)
- Account listing and status: list_accounts()
- Automated inbox retrieval: fetch_inbox_emails(account, limit)
"""

import sys
import json
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
    DATA_DIR
)
from engine.email_reader import fetch_profile_emails

ACCOUNT_SERVICE_REGISTRY: Dict[str, Dict[str, Any]] = {
    "mercor": {
        "service_name": "Mercor",
        "profile_id": EGO_BROWSER_MAIN_PROFILE_ID,
        "email": CANDIDATE_PERSONAL_EMAIL,
        "role_category": "Remote Tech Contracts & Talent Networks",
        "auth_type": "Direct / Verified Session",
        "home_url": "https://work.mercor.com/explore"
    },
    "chatgpt": {
        "service_name": "ChatGPT Consultation Engine",
        "profile_id": EGO_BROWSER_MAIN_PROFILE_ID,
        "email": CANDIDATE_PERSONAL_EMAIL,
        "role_category": "AI Evaluation & Answer Formulation",
        "auth_type": f"Google OAuth ({CANDIDATE_PERSONAL_EMAIL})",
        "home_url": "https://chatgpt.com"
    },
    "dataannotation": {
        "service_name": "DataAnnotation Tech",
        "profile_id": EGO_BROWSER_MAIN_PROFILE_ID,
        "email": CANDIDATE_PERSONAL_EMAIL,
        "role_category": "Remote ML & Programming Task Assessment",
        "auth_type": f"Google OAuth ({CANDIDATE_PERSONAL_EMAIL})",
        "home_url": "https://app.dataannotation.tech/workers/projects"
    },
    "turing": {
        "service_name": "Turing Work Portal",
        "profile_id": EGO_BROWSER_MAIN_PROFILE_ID,
        "email": CANDIDATE_PERSONAL_EMAIL,
        "role_category": "Remote ML Engineering & Specialized Vetting",
        "auth_type": f"Direct Candidate Session ({CANDIDATE_PERSONAL_EMAIL})",
        "home_url": "https://work.turing.com/dashboard"
    },
    "alignerr": {
        "service_name": "Alignerr (Labelbox)",
        "profile_id": EGO_BROWSER_MAIN_PROFILE_ID,
        "email": CANDIDATE_PERSONAL_EMAIL,
        "role_category": "Remote AI Evaluation & Modeling",
        "auth_type": f"Google OAuth ({CANDIDATE_PERSONAL_EMAIL})",
        "home_url": "https://app.alignerr.com/home"
    },
    "outlier": {
        "service_name": "Outlier AI",
        "profile_id": EGO_BROWSER_MAIN_PROFILE_ID,
        "email": CANDIDATE_PERSONAL_EMAIL,
        "role_category": "Remote AI Training & Coding Expertise",
        "auth_type": "Direct Candidate Session",
        "home_url": "https://app.outlier.ai/opportunities"
    },
    "microsoft": {
        "service_name": "Microsoft Careers (Eightfold.ai)",
        "profile_id": EGO_BROWSER_MAIN_PROFILE_ID,
        "email": CANDIDATE_PERSONAL_EMAIL,
        "role_category": "Enterprise FTE & Research Intern Roles",
        "auth_type": f"Google OAuth ({CANDIDATE_PERSONAL_EMAIL})",
        "home_url": "https://careers.microsoft.com"
    },
    "personal_gmail": {
        "service_name": "Personal Gmail Inbox",
        "profile_id": EGO_BROWSER_MAIN_PROFILE_ID,
        "email": CANDIDATE_PERSONAL_EMAIL,
        "role_category": "Direct Candidate Communication & Alerts",
        "auth_type": f"Google Session ({CANDIDATE_PERSONAL_EMAIL})",
        "home_url": "https://mail.google.com"
    },
    "linkedin": {
        "service_name": "LinkedIn Careers & ATS Scraper",
        "profile_id": EGO_BROWSER_COLLEGE_PROFILE_ID,
        "email": CANDIDATE_COLLEGE_EMAIL,
        "role_category": "Professional Network, Job Postings & InMail",
        "auth_type": f"College LinkedIn Session ({CANDIDATE_COLLEGE_EMAIL})",
        "home_url": "https://www.linkedin.com/jobs/"
    },
    "college_gmail": {
        "service_name": "University College Inbox",
        "profile_id": EGO_BROWSER_COLLEGE_PROFILE_ID,
        "email": CANDIDATE_COLLEGE_EMAIL,
        "role_category": "Academic / University Communications & Referrals",
        "auth_type": f"Google Workspace ({CANDIDATE_COLLEGE_EMAIL})",
        "home_url": "https://mail.google.com"
    }
}


def get_profile_for_service(service_name: str) -> Dict[str, Any]:
    """Resolves the browser profile and email for any requested service or portal."""
    s_key = service_name.lower().strip()
    if s_key in ACCOUNT_SERVICE_REGISTRY:
        return ACCOUNT_SERVICE_REGISTRY[s_key]

    # Fuzzy match
    for k, v in ACCOUNT_SERVICE_REGISTRY.items():
        if k in s_key or s_key in k or v["service_name"].lower() in s_key:
            return v

    # Fallback to Profile 1 (Personal)
    return {
        "service_name": service_name,
        "profile_id": EGO_BROWSER_MAIN_PROFILE_ID,
        "email": CANDIDATE_PERSONAL_EMAIL,
        "role_category": "General Tech Portal",
        "auth_type": "Profile 1 Default",
        "home_url": ""
    }


def list_registered_accounts() -> List[Dict[str, Any]]:
    """Returns the list of all registered accounts, profiles, and services."""
    return list(ACCOUNT_SERVICE_REGISTRY.values())


def fetch_inbox_messages(account_type: str = "personal", limit: int = 10) -> Dict[str, Any]:
    """
    Fetches the top N messages from personal or college inbox deterministically.
    Account options: 'personal' (Profile 1) or 'college' (Profile 2).
    """
    acc_clean = account_type.lower().strip()
    if acc_clean not in ["personal", "college"]:
        acc_clean = "personal"

    print(f"[*] Fetching top {limit} emails from {acc_clean.upper()} inbox...")
    return fetch_profile_emails(acc_clean, limit=limit)


def open_service_in_profile(service_name: str, target_url: Optional[str] = None) -> Dict[str, Any]:
    """
    Opens the requested service in its assigned browser profile via ego-browser.
    """
    cfg = get_profile_for_service(service_name)
    profile_id = cfg["profile_id"]
    url = target_url or cfg["home_url"]
    task_space_name = f"portal_{service_name.lower().replace(' ', '_')}"

    node_script = f"""
const spaces = await listTaskSpaces();
let existing = spaces.find(s => s.name === "{task_space_name}");
let task;
if (existing) {{
  if (existing.ownership === "agent") {{
    task = await taskSpace(existing.id);
  }} else {{
    try {{
      task = await takeOverTaskSpace(existing.id);
    }} catch(e) {{
      task = await taskSpace("{task_space_name}_" + Date.now(), {{ profileId: "{profile_id}" }});
    }}
  }}
}} else {{
  task = await taskSpace("{task_space_name}", {{ profileId: "{profile_id}" }});
}}
const page = task.page("p1");
console.log("[Account-Switcher] Opening {cfg['service_name']} in {profile_id} at: {url}");
await page.goto("{url}", {{ waitUntil: "domcontentloaded", timeout: 30000 }});
await new Promise(r => setTimeout(r, 4000));
console.log("JSON_STATUS:" + JSON.stringify({{
  success: true,
  service: "{cfg['service_name']}",
  profile: "{profile_id}",
  email: "{cfg['email']}",
  url: await page.url(),
  title: await page.title()
}}));
"""

    try:
        proc = subprocess.run(
            ["ego-browser", "nodejs"],
            input=node_script,
            text=True,
            capture_output=True,
            timeout=45
        )
        combined = (proc.stdout or "") + "\n" + (proc.stderr or "")
        for line in combined.splitlines():
            line = line.strip()
            if line.startswith("JSON_STATUS:"):
                return json.loads(line.replace("JSON_STATUS:", "", 1))
        return {"success": False, "raw_output": combined}
    except Exception as e:
        return {"success": False, "error": str(e)}


if __name__ == "__main__":
    print("[*] Account Switcher & Profile Routing Matrix:")
    print(f"{'SERVICE':<25} | {'PROFILE':<10} | {'EMAIL':<30} | {'AUTH TYPE'}")
    print("-" * 90)
    for v in list_registered_accounts():
        print(f"{v['service_name']:<25} | {v['profile_id']:<10} | {v['email']:<30} | {v['auth_type']}")
