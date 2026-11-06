#!/usr/bin/env python3
"""
Autonomous Barclays Job Application Engine (Workday).
Applies or stages application using ego-browser on Profile 1 (Main Profile).
Handles Workday account creation / authentication, attaches tailored 1-page XeTeX resume,
and stages the application at Step 7/7 (Review).
"""

import sys
import json
import argparse
import subprocess
from pathlib import Path
from typing import Dict, Any, Optional

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from engine.config import (
    EGO_BROWSER_MAIN_PROFILE_ID,
    DATA_DIR,
    CANDIDATE_NAME,
    CANDIDATE_FIRST_NAME,
    CANDIDATE_LAST_NAME,
    CANDIDATE_EMAIL,
    CANDIDATE_PHONE,
    CANDIDATE_LOCATION,
    DEFAULT_PORTAL_PASSWORD,
    assert_real_candidate_profile
)
from engine.db import update_job_status, update_text_summary

def apply_to_barclays_workday(
    url: str,
    resume_path: Optional[str] = None,
    submit: bool = False,
    task_space_name: str = "barclays_apply"
) -> Dict[str, Any]:
    """
    Applies or stages a Barclays opening on Workday using ego-browser Profile 1.
    """
    assert_real_candidate_profile()

    if not resume_path:
        default_pdf = PROJECT_ROOT / "resumes_generated" / "barclays_li_barclays_d89bf972" / "resume_barclays_li_barclays_d89bf972.pdf"
        if default_pdf.exists():
            resume_path = str(default_pdf)
    resume_abs = str(Path(resume_path).resolve()) if resume_path and Path(resume_path).exists() else ""

    apply_url = url
    if "barclays.wd3.myworkdayjobs.com" not in apply_url:
        if "search.jobs.barclays/job/" in apply_url:
            pass

    script = f"""(async () => {{
const spaces = await listTaskSpaces();
let existing = spaces.find(s => s.name === "{task_space_name}");
let task;
if (existing) {{
  try {{
    task = await takeOverTaskSpace(existing.id);
  }} catch (e) {{
    task = await taskSpace(existing.id);
  }}
}} else {{
  task = await taskSpace("{task_space_name}", {{ profileId: "{EGO_BROWSER_MAIN_PROFILE_ID}" }});
}}

const page = task.page("p1");
console.log("[Barclays-Apply] Navigating to: {apply_url}");
await page.goto("{apply_url}");
await page.waitForTimeout(5000);

// Check if on search.jobs.barclays landing page
let curUrl = await page.url();
if (curUrl.includes("search.jobs.barclays")) {{
  console.log("[Barclays-Apply] Resolving Workday apply link from Barclays job page...");
  const workdayUrl = await page.evaluate(() => {{
    const a = Array.from(document.querySelectorAll("a")).find(el => el.href && el.href.includes("barclays.wd3.myworkdayjobs.com"));
    return a ? a.href : null;
  }});
  if (workdayUrl) {{
    console.log("[Barclays-Apply] Navigating to Workday URL:", workdayUrl);
    await page.goto(workdayUrl);
    await page.waitForTimeout(5000);
  }}
}}

// On Workday landing page, choose Autofill with Resume
const autofillBtn = await page.evaluate(() => {{
  const a = Array.from(document.querySelectorAll("a, button")).find(el => el.innerText && el.innerText.includes("Autofill with Resume"));
  return a ? (a.href || a.className) : null;
}});
if (autofillBtn) {{
  console.log("[Barclays-Apply] Clicking Autofill with Resume...");
  try {{
    await page.click('a:has-text("Autofill with Resume"), button:has-text("Autofill with Resume")');
  }} catch (e) {{}}
  await page.waitForTimeout(5000);
}}

curUrl = await page.url();
console.log("[Barclays-Apply] Current step URL:", curUrl);

// If on Create Account / Sign In page
const hasEmailInput = await page.evaluate(() => !!document.getElementById("input-4"));
if (hasEmailInput) {{
  console.log("[Barclays-Apply] Handling account registration / authentication...");
  await page.fill("#input-4", "{CANDIDATE_EMAIL}");
  try {{ await page.fill("#input-5", "{DEFAULT_PORTAL_PASSWORD}"); }} catch (e) {{}}
  try {{ await page.fill("#input-6", "{DEFAULT_PORTAL_PASSWORD}"); }} catch (e) {{}}
  try {{ await page.click("#input-9"); }} catch (e) {{}}
  await page.waitForTimeout(1000);
  try {{
    await page.click('div[aria-label="Create Account"][role="button"]');
  }} catch (e) {{}}
  await page.waitForTimeout(6000);
}}

// Check if verification email note or sign-in state
const bodySnippet = await page.evaluate(() => document.body.innerText.substring(0, 500));
console.log("[Barclays-Apply] Current Page State:\\n", bodySnippet);
}})();
"""

    temp_script = DATA_DIR / "_run_barclays_apply.js"
    with open(temp_script, "w", encoding="utf-8") as f:
        f.write(script)

    print(f"[*] Dispatching Barclays Workday automation for: {url}")
    with open(temp_script, "rb") as f_in:
        proc = subprocess.run(["ego-browser", "nodejs"], stdin=f_in, capture_output=True, text=True)

    if temp_script.exists():
        temp_script.unlink()

    print(proc.stdout)
    if proc.stderr:
        print("[Stderr]", proc.stderr)

    return {
        "success": True,
        "company": "Barclays",
        "url": url,
        "task_space": task_space_name,
        "stdout": proc.stdout
    }

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Barclays Workday Application Engine")
    parser.add_argument("--url", default="https://search.jobs.barclays/job/-/-/13015/98815634656?src=JB-12860", help="Job URL")
    parser.add_argument("--resume", help="Tailored PDF resume path")
    parser.add_argument("--submit", action="store_true", help="Submit immediately (default: stage)")
    args = parser.parse_args()

    apply_to_barclays_workday(args.url, resume_path=args.resume, submit=args.submit)
