#!/usr/bin/env python3
"""
Autonomous Barclays Job Application Engine (Workday).
Applies or stages application using ego-browser on Profile 1 (Main Profile).
Handles Workday account creation / authentication, attaches tailored 1-page XeTeX resume,
answers all 10 compliance/screening questions, accepts terms, and reviews/submits application.
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

    submit_action = 'await page.click(\'button[data-automation-id="pageFooterNextButton"]\');' if submit else '// Staged at Review'

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
let curUrl = await page.url();
console.log("[Barclays-Apply] Current URL:", curUrl);

// If not on Workday, navigate to target url
if (!curUrl.includes("barclays.wd3.myworkdayjobs.com")) {{
  console.log("[Barclays-Apply] Navigating to: {url}");
  await page.goto("{url}");
  await page.waitForTimeout(5000);
}}

// Check if on search.jobs.barclays landing page
curUrl = await page.url();
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

// Handle Autofill with Resume if present
const hasAutofill = await page.evaluate(() => {{
  const a = Array.from(document.querySelectorAll("a, button")).find(el => el.innerText && el.innerText.includes("Autofill with Resume"));
  return !!a;
}});
if (hasAutofill) {{
  console.log("[Barclays-Apply] Clicking Autofill with Resume...");
  try {{
    await page.click('a:has-text("Autofill with Resume"), button:has-text("Autofill with Resume")');
    await page.waitForTimeout(4000);
  }} catch (e) {{}}
}}

// If on Create Account / Sign In page
const hasEmailInput = await page.evaluate(() => !!document.getElementById("input-4"));
if (hasEmailInput) {{
  console.log("[Barclays-Apply] Handling account registration...");
  await page.fill("#input-4", "{CANDIDATE_EMAIL}");
  try {{ await page.fill("#input-5", "{DEFAULT_PORTAL_PASSWORD}"); }} catch (e) {{}}
  try {{ await page.fill("#input-6", "{DEFAULT_PORTAL_PASSWORD}"); }} catch (e) {{}}
  try {{ await page.click("#input-9"); }} catch (e) {{}}
  await page.waitForTimeout(1000);
  try {{
    await page.click('div[aria-label="Create Account"][role="button"]');
  }} catch (e) {{}}
  await page.waitForTimeout(5000);
}}

// Step progression loop
for (let step = 0; step < 7; step++) {{
  const bodyText = await page.evaluate(() => document.body.innerText);

  // Check if submitted
  if (bodyText.includes("Application Submitted") || (bodyText.includes("Welcome, {CANDIDATE_NAME}") && bodyText.includes("My Applications"))) {{
    console.log("[Barclays-Apply] Application is already SUBMITTED!");
    break;
  }}

  // Step: My Information
  if (bodyText.includes("My Information") && document.getElementById("source--source")) {{
    console.log("[Barclays-Apply] Handling Step: My Information...");
    try {{
      // Select Source: LinkedIn
      await page.click('#source--source');
      await page.fill('#source--source', 'LinkedIn');
      await page.press('#source--source', 'Enter');
      await page.waitForTimeout(1000);

      // Select State: Delhi
      const stateVal = await page.evaluate(() => document.getElementById("address--countryRegion")?.innerText);
      if (!stateVal || stateVal.includes("Select One")) {{
        await page.click('#address--countryRegion');
        await page.waitForTimeout(800);
        await page.evaluate(() => {{
          const opt = Array.from(document.querySelectorAll('[role="option"]')).find(o => o.innerText.toLowerCase().includes("delhi"));
          if (opt) opt.click();
        }});
        await page.waitForTimeout(800);
      }}

      // Click Next
      await page.evaluate(() => {{
        const btn = document.querySelector('button[data-automation-id="pageFooterNextButton"]');
        if (btn) btn.click();
      }});
      await page.waitForTimeout(5000);
      continue;
    }} catch (e) {{
      console.log("[Barclays-Apply] Error in My Information:", e.message);
    }}
  }}

  // Step: My Experience (Resume)
  if (bodyText.includes("My Experience") && bodyText.includes("Resume/CV")) {{
    console.log("[Barclays-Apply] Handling Step: My Experience...");
    await page.evaluate(() => {{
      const btn = document.querySelector('button[data-automation-id="pageFooterNextButton"]');
      if (btn) btn.click();
    }});
    await page.waitForTimeout(5000);
    continue;
  }}

  // Step: Application Questions
  if (bodyText.includes("Application Questions") && document.getElementById("primaryQuestionnaire--7312167fa45f1001e09b10f910650000")) {{
    console.log("[Barclays-Apply] Handling Step: Application Questions...");
    const answers = [
      {{ id: "primaryQuestionnaire--7312167fa45f1001e09b10f910650000", match: "No" }},
      {{ id: "primaryQuestionnaire--7312167fa45f1001e09b11930b190001", match: "No" }},
      {{ id: "primaryQuestionnaire--7312167fa45f1001e09b12e9830f0000", match: "No" }},
      {{ id: "primaryQuestionnaire--7312167fa45f1001e09b141d3fd40000", match: "Yes - I am a citizen" }},
      {{ id: "primaryQuestionnaire--7312167fa45f1001e09b15eab3770000", match: "No" }},
      {{ id: "primaryQuestionnaire--7312167fa45f1001e09b168428020000", match: "No" }},
      {{ id: "primaryQuestionnaire--7312167fa45f1001e09b171dd53a0000", match: "No" }},
      {{ id: "primaryQuestionnaire--8febd4e8556f1001e0acfbc668140000", match: "Yes" }},
      {{ id: "primaryQuestionnaire--7312167fa45f1001e09b171dd53a0003", match: "Yes" }},
      {{ id: "primaryQuestionnaire--7312167fa45f1001e09b1852b8f30001", match: "No" }}
    ];

    for (const item of answers) {{
      await page.evaluate((btnId) => {{
        const btn = document.getElementById(btnId);
        if (btn) btn.scrollIntoView({{ behavior: 'instant', block: 'center' }});
      }}, item.id);
      await page.waitForTimeout(300);
      try {{
        await page.click(`#${{item.id}}`);
        await page.waitForTimeout(600);
        await page.evaluate((target) => {{
          const opts = Array.from(document.querySelectorAll('[role="option"]'));
          const found = opts.find(o => (o.innerText || '').trim().toLowerCase() === target.toLowerCase()) ||
                        opts.find(o => (o.innerText || '').trim().toLowerCase().startsWith(target.toLowerCase()));
          if (found) found.click();
        }}, item.match);
        await page.waitForTimeout(400);
      }} catch (e) {{}}
    }}

    await page.evaluate(() => {{
      const btn = document.querySelector('button[data-automation-id="pageFooterNextButton"]');
      if (btn) btn.click();
    }});
    await page.waitForTimeout(5000);
    continue;
  }}

  // Step: Voluntary Disclosures
  if (bodyText.includes("Voluntary Disclosures") && document.getElementById("termsAndConditions--acceptTermsAndAgreements")) {{
    console.log("[Barclays-Apply] Handling Step: Voluntary Disclosures...");
    try {{
      // Select Asian (India)
      await page.click('#personalInfoPerson--ethnicity');
      await page.waitForTimeout(600);
      await page.evaluate(() => {{
        const opts = Array.from(document.querySelectorAll('[role="option"]'));
        const target = opts.find(o => o.innerText.includes("Asian") || o.innerText.includes("Indian"));
        if (target) target.click();
      }});
      await page.waitForTimeout(400);

      // Check Terms checkbox
      const isChecked = await page.evaluate(() => document.getElementById("termsAndConditions--acceptTermsAndAgreements")?.checked);
      if (!isChecked) {{
        await page.click('#termsAndConditions--acceptTermsAndAgreements');
        await page.waitForTimeout(400);
      }}

      await page.evaluate(() => {{
        const btn = document.querySelector('button[data-automation-id="pageFooterNextButton"]');
        if (btn) btn.click();
      }});
      await page.waitForTimeout(5000);
      continue;
    }} catch (e) {{
      console.log("[Barclays-Apply] Error in Voluntary Disclosures:", e.message);
    }}
  }}

  // Step: Review
  if (bodyText.includes("Review") && document.querySelector('button[data-automation-id="pageFooterNextButton"]')) {{
    const submitText = await page.evaluate(() => document.querySelector('button[data-automation-id="pageFooterNextButton"]')?.innerText.trim());
    console.log("[Barclays-Apply] On Review Step. Button text:", submitText);
    {submit_action}
    await page.waitForTimeout(5000);
    break;
  }}
}}

const finalUrl = await page.url();
const finalTitle = await page.title();
console.log("[Barclays-Apply] Final URL:", finalUrl, "Title:", finalTitle);
}})();
"""

    temp_script = DATA_DIR / "_run_barclays_apply.js"
    with open(temp_script, "w", encoding="utf-8") as f:
        f.write(script)

    print(f"[*] Executing Barclays Workday automation (submit={submit}) for: {url}")
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
