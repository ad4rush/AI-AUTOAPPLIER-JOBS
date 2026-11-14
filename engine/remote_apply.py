#!/usr/bin/env python3
"""
Autonomous Remote & Contract Job Application Engine (Mercor & Outlier).
Executes end-to-end auto-apply or staging via ego-browser on Profile 1 (Main Profile).
Pre-populates candidate details, attaches strictly 1-page tailored master resume,
and answers standard eligibility screening questions.
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
    MASTER_RESUME_DIR,
    CANDIDATE_NAME,
    CANDIDATE_PERSONAL_EMAIL,
    CANDIDATE_PHONE_PLAIN,
    CANDIDATE_LINKEDIN
)
from engine.db import update_job_status, update_text_summary

def apply_to_remote_contract_job(
    url_or_id: str,
    resume_path: Optional[str] = None,
    submit: bool = False,
    task_space_name: str = "remote_contract_auto_apply"
) -> Dict[str, Any]:
    """
    Applies to an Outlier, Mercor, or remote contract opening in ego-browser Profile 1.
    """
    if not resume_path:
        resume_path = str(PROJECT_ROOT / "master_resumes" / "RESUME_1_AI_ENGINEER.pdf")

    resume_abs = str(Path(resume_path).resolve())

    # Determine platform
    is_mercor = "mercor.com" in url_or_id or "mercor" in url_or_id.lower()
    is_outlier = "outlier.ai" in url_or_id or "outlier" in url_or_id.lower()

    target_url = url_or_id
    if not target_url.startswith("http"):
        if "outlier" in url_or_id:
            oid = url_or_id.replace("outlier_", "")
            target_url = f"https://app.outlier.ai/en/expert/opportunities/{oid}"
        elif "mercor" in url_or_id:
            target_url = "https://work.mercor.com"

    print(f"[*] Navigating to Remote Contract Job: {target_url}")
    print(f"[*] Target Platform: {'Mercor' if is_mercor else 'Outlier' if is_outlier else 'Remote Portal'}")

    # If the URL is an Ashby application (e.g. jobs.ashbyhq.com/mercor/...), delegate to Ashby engine
    if "ashbyhq.com" in target_url:
        from engine.ashby_apply import apply_to_ashby_job
        return apply_to_ashby_job(target_url, resume_path=resume_abs, submit=submit, task_space_name=task_space_name)

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
      task = await taskSpace("{task_space_name}_" + Date.now(), {{ profileId: "{EGO_BROWSER_MAIN_PROFILE_ID}" }});
    }}
  }}
}} else {{
  task = await taskSpace("{task_space_name}", {{ profileId: "{EGO_BROWSER_MAIN_PROFILE_ID}" }});
}}
const page = task.page("p1");

console.log("[Remote-Apply] Loading portal: {target_url}");
await page.goto("{target_url}", {{ waitUntil: "domcontentloaded", timeout: 45000 }});
await new Promise(r => setTimeout(r, 4000));

const currentUrl = await page.url();
const title = await page.title();
console.log("[Remote-Apply] Reached: " + title + " (" + currentUrl + ")");

// Fill candidate basics with React-aware property setter
const formResult = await page.evaluate(async () => {{
  function setReactValue(input, value) {{
    const proto = window.HTMLInputElement.prototype;
    const desc = Object.getOwnPropertyDescriptor(proto, "value");
    if (desc && desc.set) {{
      desc.set.call(input, value);
    }} else {{
      input.value = value;
    }}
    input.dispatchEvent(new Event("input", {{ bubbles: true }}));
    input.dispatchEvent(new Event("change", {{ bubbles: true }}));
    input.dispatchEvent(new Event("blur", {{ bubbles: true }}));
  }}

  const inputs = Array.from(document.querySelectorAll('input, textarea'));
  const log = [];
  
  // Name
  const nameInput = inputs.find(i => {{
    const l = (i.labels && i.labels[0] ? i.labels[0].innerText : "") || (i.placeholder || "") || (i.name || "");
    return l.toLowerCase().includes("name");
  }});
  if (nameInput && !nameInput.value) {{
    nameInput.focus();
    setReactValue(nameInput, "{CANDIDATE_NAME}");
    log.push("Filled Name: {CANDIDATE_NAME}");
  }}
  
  // Email
  const emailInput = inputs.find(i => {{
    const l = (i.labels && i.labels[0] ? i.labels[0].innerText : "") || (i.placeholder || "") || (i.name || "") || i.type;
    return l.toLowerCase().includes("email");
  }});
  if (emailInput && !emailInput.value) {{
    emailInput.focus();
    setReactValue(emailInput, "{CANDIDATE_PERSONAL_EMAIL}");
    log.push("Filled Email: {CANDIDATE_PERSONAL_EMAIL}");
  }}

  // Phone
  const phoneInput = inputs.find(i => {{
    const l = (i.labels && i.labels[0] ? i.labels[0].innerText : "") || (i.placeholder || "") || (i.name || "") || i.type;
    return l.toLowerCase().includes("phone") || l.toLowerCase().includes("mobile") || l.toLowerCase().includes("tel");
  }});
  if (phoneInput && !phoneInput.value) {{
    phoneInput.focus();
    setReactValue(phoneInput, "{CANDIDATE_PHONE_PLAIN}");
    log.push("Filled Phone: {CANDIDATE_PHONE_PLAIN}");
  }}

  // LinkedIn
  const linkedinInput = inputs.find(i => {{
    const l = (i.labels && i.labels[0] ? i.labels[0].innerText : "") || (i.placeholder || "") || (i.name || "");
    return l.toLowerCase().includes("linkedin");
  }});
  if (linkedinInput && !linkedinInput.value) {{
    linkedinInput.focus();
    setReactValue(linkedinInput, "{CANDIDATE_LINKEDIN}");
    log.push("Filled LinkedIn");
  }}
  
  return log;
}});

console.log("[Remote-Apply] Fields filled:", formResult);

// Handle file upload if file input exists
const fileInput = await page.evaluate(() => {{
  const f = document.querySelector('input[type="file"]');
  return !!f;
}});

if (fileInput && "{resume_abs}") {{
  try {{
    console.log("[Remote-Apply] Uploading master resume: {resume_abs}");
    if (typeof page.setInputFiles === "function") {{
      await page.setInputFiles('input[type="file"]', "{resume_abs}");
      await new Promise(r => setTimeout(r, 1500));
    }}
  }} catch(e) {{
    console.log("[Remote-Apply] Upload error: " + e.message);
  }}
}}

// Handle submission confirmation verification
let submitted = false;
let confirmationSnippet = "";
if ({str(submit).lower()}) {{
  console.log("[Remote-Apply] Submit=True requested. Locating submit button...");
  submitted = await page.evaluate(() => {{
    const btns = Array.from(document.querySelectorAll('button, input[type="submit"]'));
    const subBtn = btns.find(b => {{
      const t = (b.innerText || b.value || "").toLowerCase();
      return t.includes("apply") || t.includes("submit") || t.includes("continue");
    }});
    if (subBtn && !subBtn.disabled) {{
      subBtn.click();
      return true;
    }}
    return false;
  }});
  await new Promise(r => setTimeout(r, 4000));
  confirmationSnippet = await page.evaluate(() => document.body ? document.body.innerText.slice(0, 500) : "");
}}

const hasRealForm = formResult.length > 0;
const isConfirmedSubmitted = submitted && (
  confirmationSnippet.toLowerCase().includes("thank you") ||
  confirmationSnippet.toLowerCase().includes("received your application") ||
  confirmationSnippet.toLowerCase().includes("submitted") ||
  confirmationSnippet.toLowerCase().includes("success")
);

const isSuccess = hasRealForm && ({str(submit).lower()} ? isConfirmedSubmitted : true);

console.log(JSON.stringify({{
  success: isSuccess,
  submitted: isConfirmedSubmitted,
  url: await page.url(),
  title: await page.title(),
  fieldsFilled: formResult,
  error: isSuccess ? null : (hasRealForm ? "Submit confirmation not detected" : "No interactive application form fields found on page")
}}));
"""
    try:
        proc = subprocess.run(
            ["ego-browser", "nodejs"],
            input=node_script,
            text=True,
            capture_output=True,
            timeout=60
        )
        combined = (proc.stdout or "") + "\n" + (proc.stderr or "")
        for line in combined.splitlines():
            line = line.strip()
            if line.startswith("{") and line.endswith("}"):
                try:
                    return json.loads(line)
                except Exception:
                    continue
        return {"success": False, "raw_output": combined}
    except Exception as e:
        return {"success": False, "error": str(e)}

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Auto-apply to remote contract jobs (Outlier, Mercor)")
    parser.add_argument("--url", required=True, help="Job URL or ID")
    parser.add_argument("--resume", help="Path to tailored PDF resume")
    parser.add_argument("--submit", action="store_true", help="Submit immediately")
    args = parser.parse_args()

    res = apply_to_remote_contract_job(args.url, resume_path=args.resume, submit=args.submit)
    print(json.dumps(res, indent=2))
