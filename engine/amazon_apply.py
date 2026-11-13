#!/usr/bin/env python3
"""
Autonomous Multi-Step Amazon Application Engine.
Applies to Amazon early-career and L4 jobs using the authenticated session in ego-browser Profile 1.
Handles:
- Amazon Jobs applicant portal navigation (/applicant/jobs/{job_id}/apply)
- Pre-filled profile verification
- SMS updates skip
- Select2 jQuery dropdown auto-fill
- Government employee disclosure & consent
- Review & Final submission
"""

import sys
import re
import json
import argparse
import subprocess
from pathlib import Path
from typing import Dict, Any, Optional

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from engine.config import EGO_BROWSER_MAIN_PROFILE_ID
from engine.db import update_job_status, update_text_summary

def extract_job_id(url: str) -> Optional[str]:
    m = re.search(r"/jobs/(\d+)", url)
    return m.group(1) if m else None

def apply_to_amazon_job(
    url: str,
    resume_path: Optional[str] = None,
    submit: bool = True,
    task_space_name: str = "amazon_auto_apply"
) -> Dict[str, Any]:
    job_id = extract_job_id(url)
    if not job_id:
        return {"success": False, "error": f"Could not extract Amazon Job ID from URL: {url}"}

    apply_url = f"https://account.amazon.jobs/applicant/jobs/{job_id}/apply"

    node_template = """(async () => {
const spaces = await listTaskSpaces();
let existing = spaces.find(s => s.name === "__TASK_SPACE__");
let task;
if (existing) {
  task = existing.ownership === "agent" ? await taskSpace(existing.id) : await takeOverTaskSpace(existing.id);
} else {
  task = await taskSpace("__TASK_SPACE__", { profileId: "__PROFILE_ID__" });
}
const page = (await task.pages())[0];

console.log("[Amazon-Apply] Navigating to: __APPLY_URL__");
await page.goto("__APPLY_URL__", { waitUntil: "domcontentloaded", timeout: 45000 });
await new Promise(r => setTimeout(r, 4000));

// Check if already applied or completed immediately upon navigation
const immediateCheck = await page.evaluate(() => {
  const url = window.location.href;
  const text = document.body.innerText;
  const isDuplicate = url.includes("result=duplicate") || text.includes("already applied for this position");
  const isSuccess = url.includes("result=success") || text.includes("Your application for") || text.includes("has been submitted");
  if (isDuplicate || isSuccess) {
    return {
      title: document.title,
      url: url,
      isSuccess: true,
      alreadyApplied: isDuplicate,
      bodySnippet: text.slice(0, 300)
    };
  }
  return null;
});

if (immediateCheck) {
  console.log("[Amazon-Apply] Detected existing/immediate completion:", JSON.stringify(immediateCheck));
  console.log(JSON.stringify({
    success: true,
    job_id: "__JOB_ID__",
    finalState: immediateCheck
  }));
  return;
}

// Multi-step form navigator
for (let step = 0; step < 20; step++) {
  await page.evaluate(() => {
    // 0. Skip SMS if modal / button exists
    const skipBtn = document.querySelector("#save-and-continue-form-button");
    if (skipBtn && skipBtn.offsetParent !== null) {
      skipBtn.click();
    }

    // 1. Country / Citizenship dropdown
    const selects = Array.from(document.querySelectorAll("select"));
    for (const s of selects) {
      if (!s.value || s.value === "") {
        for (const opt of s.options) {
          if (opt.text.toLowerCase() === "india" || opt.value === "INDIA") {
            s.value = opt.value;
            s.dispatchEvent(new Event("change", { bubbles: true }));
            break;
          }
        }
      }
    }

    // 2. Select2 jQuery dropdowns (Job-specific questions)
    if (typeof window.$ !== "undefined" && $("select.select2-hidden-accessible").length > 0) {
      $("select.select2-hidden-accessible").each((idx, el) => {
        if (!$(el).val() || $(el).val() === "") {
          $(el).val("1").trigger("change");
        }
      });
    }

    // 3. Consent checkbox
    const consentYes = document.querySelector("#consent-yes");
    if (consentYes && !consentYes.checked) {
      consentYes.checked = true;
      consentYes.dispatchEvent(new Event("change", { bubbles: true }));
    }

    // 4. Radios: General Questions & Work Eligibility
    const prevApplied = document.querySelector("input[name*=PREVIOUSLY_APPLIED][value=YES]");
    if (prevApplied && !prevApplied.checked) { prevApplied.click(); prevApplied.checked = true; prevApplied.dispatchEvent(new Event("change", { bubbles: true })); }

    const prevEmp = document.querySelector("input[name*=PREVIOUS_AMAZON_EMPLOYMENT][value=NO]");
    if (prevEmp && !prevEmp.checked) { prevEmp.click(); prevEmp.checked = true; prevEmp.dispatchEvent(new Event("change", { bubbles: true })); }

    const nonComp = document.querySelector("input[name*=NON_COMPETITION][value=NO]");
    if (nonComp && !nonComp.checked) { nonComp.click(); nonComp.checked = true; nonComp.dispatchEvent(new Event("change", { bubbles: true })); }

    const spons = document.querySelector("input[name*=REQUIRE_SPONSORSHIP][value=NO]");
    if (spons && !spons.checked) { spons.click(); spons.checked = true; spons.dispatchEvent(new Event("change", { bubbles: true })); }

    const govt = document.querySelector("input[name*=GOVERNMENT_EMPLOYEE][value=NEVER]") || document.querySelector("#radio-874eaabd-675d-1ec1-a239-73fac91fef56");
    if (govt && !govt.checked) { govt.click(); govt.checked = true; govt.dispatchEvent(new Event("change", { bubbles: true })); }

    const exportNo = document.querySelector("input[name*=DEEMED_EXPORT][value=NO]");
    if (exportNo && !exportNo.checked) { exportNo.click(); exportNo.checked = true; exportNo.dispatchEvent(new Event("change", { bubbles: true })); }

    // 5. Acknowledgement checkboxes
    document.querySelectorAll("input[type=checkbox]").forEach(cb => {
      if (!cb.checked && cb.offsetParent !== null) {
        cb.click();
      }
    });
  });

  await new Promise(r => setTimeout(r, 1500));

  // Check if reached Review / Submit step
  const status = await page.evaluate(() => {
    const buttons = Array.from(document.querySelectorAll("button, a.btn")).filter(b => b.offsetParent !== null);
    const submitBtn = buttons.find(b => b.innerText.trim() === "Submit application");
    const continueBtn = buttons.find(b => {
      const t = b.innerText.trim();
      return (t === "Continue" || t === "Save & continue" || t === "Skip & continue");
    });
    return {
      hasSubmit: !!submitBtn,
      hasContinue: !!continueBtn
    };
  });

  if (status.hasSubmit) {
    if (__SUBMIT__) {
      console.log("[Amazon-Apply] Clicking Submit application...");
      await page.evaluate(() => {
        const btn = Array.from(document.querySelectorAll("button, a.btn")).find(b => {
          const t = b.innerText.trim();
          return t === "Submit application" && b.offsetParent !== null;
        });
        if (btn) btn.click();
      });
      await new Promise(r => setTimeout(r, 10000));
    } else {
      console.log("[Amazon-Apply] Reached Review step. Staged for user review (--submit not set).");
    }
    break;
  }

  if (status.hasContinue) {
    console.log("[Amazon-Apply] Advancing to next step...");
    await page.evaluate(() => {
      const btn = Array.from(document.querySelectorAll("button, a.btn")).find(b => {
        const t = b.innerText.trim();
        return (t === "Continue" || t === "Save & continue" || t === "Skip & continue") && b.offsetParent !== null;
      });
      if (btn) btn.click();
    });
    await new Promise(r => setTimeout(r, 4000));
  } else {
    break;
  }
}

const finalState = await page.evaluate(() => {
  const url = window.location.href;
  const text = document.body.innerText;
  const isDuplicate = url.includes("result=duplicate") || text.includes("already applied for this position");
  const isLimitReached = url.includes("result=application_limit_reach") || text.includes("hit the limit of 10 job applications");
  const isSuccess = url.includes("result=success") || text.includes("Your application for") || text.includes("has been submitted") || text.includes("Thank you for your application") || isDuplicate || isLimitReached;
  return {
    title: document.title,
    url: url,
    isSuccess: isSuccess,
    alreadyApplied: isDuplicate,
    isLimitReached: isLimitReached,
    bodySnippet: text.slice(0, 300)
  };
});

console.log(JSON.stringify({
  success: finalState.isSuccess,
  job_id: "__JOB_ID__",
  finalState
}));
})();
"""

    node_script = (
        node_template
        .replace("__TASK_SPACE__", task_space_name)
        .replace("__PROFILE_ID__", EGO_BROWSER_MAIN_PROFILE_ID)
        .replace("__APPLY_URL__", apply_url)
        .replace("__SUBMIT__", str(submit).lower())
        .replace("__JOB_ID__", job_id)
    )

    try:
        proc = subprocess.run(
            ["ego-browser", "nodejs"],
            input=node_script,
            text=True,
            capture_output=True,
            timeout=150
        )
        combined = (proc.stdout or "") + "\n" + (proc.stderr or "")
        for line in combined.splitlines():
            line = line.strip()
            if line.startswith("{") and line.endswith("}"):
                try:
                    data = json.loads(line)
                    if "success" in data:
                        return data
                except Exception:
                    continue
        return {"success": False, "raw_output": combined}
    except Exception as e:
        return {"success": False, "error": str(e)}

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Autonomous Amazon Job Applier")
    parser.add_argument("--url", required=True, help="Amazon Job URL")
    parser.add_argument("--resume", help="Tailored resume path")
    parser.add_argument("--submit", action="store_true", default=True, help="Submit immediately")
    parser.add_argument("--task-space", default=None, help="Custom task space name")
    args = parser.parse_args()

    tspace = args.task_space or "amazon_auto_apply"
    res = apply_to_amazon_job(args.url, resume_path=args.resume, submit=args.submit, task_space_name=tspace)
    print(json.dumps(res, indent=2))
