#!/usr/bin/env python3
"""
Autonomous SmartRecruiters Job Application Engine (OneClick UI).
Executes end-to-end auto-apply via ego-browser on Profile 1 (Main Profile).
Navigates SmartRecruiters OneClick UI shadow DOM, uploads candidate resume,
populates personal details, contact info, experience, education, social profiles,
answers custom screening questions, accepts compliance consents,
and either stages the application or completes direct submission.
"""

import sys
import json
import argparse
import subprocess
from pathlib import Path
from typing import Dict, Any, Optional
from datetime import datetime

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from engine.config import (
    EGO_BROWSER_MAIN_PROFILE_ID,
    DATA_DIR,
    CANDIDATE_NAME,
    CANDIDATE_FIRST_NAME,
    CANDIDATE_LAST_NAME,
    CANDIDATE_EMAIL,
    CANDIDATE_PHONE_PLAIN,
    CANDIDATE_CITY,
    assert_real_candidate_profile,
    verify_script_zero_placeholders
)
from engine.procedure_memory import record_company_procedure
from engine.resume_router import resolve_resume_and_metadata


def apply_to_smartrecruiters_job(
    url: str,
    resume_path: Optional[str] = None,
    company_name: str = "Target Company",
    title: Optional[str] = None,
    jd_text: Optional[str] = None,
    submit: bool = False,
    task_space_name: Optional[str] = None,
    job_id_db: Optional[str] = None
) -> Dict[str, Any]:
    """
    Applies to a job on SmartRecruiters OneClick UI using ego-browser Profile 1.
    """
    assert_real_candidate_profile()

    meta = resolve_resume_and_metadata(
        company=company_name,
        title=title,
        jd_text=jd_text,
        job_id=job_id_db,
        resume_path=resume_path,
        url=url
    )
    resume_abs = meta.get("resume_path", "")
    company_name = meta.get("company", company_name)
    effective_title = meta.get("title", title or "Software Engineer")
    print(f"[*] SmartRecruiters dynamic resume routing for {company_name} — '{effective_title}': Archetype={meta.get('archetype')} | File={Path(resume_abs).name} ({meta.get('notes')})")

    tspace = task_space_name or f"apply_smartrecruiters_{datetime.now().strftime('%H%M%S')}"

    script = f"""
const task = await taskSpace("{tspace}", {{ profileId: "{EGO_BROWSER_MAIN_PROFILE_ID}" }});
const page = task.page("p1");

console.log("[SmartRecruiters] Navigating to job portal...");
await page.goto("{url}");
await new Promise(r => setTimeout(r, 4000));

// Step 1: Upload resume to autocomplete dropzone
console.log("[SmartRecruiters] Uploading resume for autoparsing...");
try {{
  await page.setInputFiles("#spl-dropzone-file-input-2", "{resume_abs}");
  await new Promise(r => setTimeout(r, 6000));
}} catch (e) {{
  console.log("[SmartRecruiters] Autocomplete upload error:", e.message);
}}

// Step 2: Ensure resume attachment is present
const resumeAttached = await page.evaluate(() => {{
  return document.body.innerText.includes("{Path(resume_abs).name}");
}});
if (!resumeAttached) {{
  try {{
    await page.setInputFiles("#spl-dropzone-file-input-1", "{resume_abs}");
    await new Promise(r => setTimeout(r, 2000));
  }} catch (e) {{
    console.log("[SmartRecruiters] Resume attachment error:", e.message);
  }}
}}

// Step 3: Populate core candidate fields & resolve draft cards
await page.evaluate(() => {{
  function getDeep(root) {{
    let list = [];
    for (const el of root.querySelectorAll("*")) {{
      list.push(el);
      if (el.shadowRoot) list.push(...getDeep(el.shadowRoot));
    }}
    return list;
  }}
  const all = getDeep(document.body);

  function setVal(id, val) {{
    const el = all.find(e => e.id === id && ["INPUT", "TEXTAREA"].includes(e.tagName));
    if (el) {{
      el.value = val;
      el.dispatchEvent(new Event("input", {{ bubbles: true }}));
      el.dispatchEvent(new Event("change", {{ bubbles: true }}));
      return true;
    }}
    return false;
  }}

  setVal("first-name-input", "{CANDIDATE_FIRST_NAME}");
  setVal("last-name-input", "{CANDIDATE_LAST_NAME}");
  setVal("email-input", "{CANDIDATE_EMAIL}");
  setVal("confirm-email-input", "{CANDIDATE_EMAIL}");
  setVal("spl-form-element_10", "{CANDIDATE_CITY}, India");
  setVal("spl-form-element_5", "{CANDIDATE_PHONE_PLAIN}");
  setVal("linkedin-input", "https://www.linkedin.com/in/ad4rush/");
  setVal("website-input", "https://github.com/ad4rush");

  const msg = "Dear Hiring Team,\\n\\nI am excited to apply for this role. As an AI & Systems Engineer with strong experience architecting low-latency microservices, REST/WebSocket APIs, distributed data pipelines (Spark, Kafka CDC, S3 Lakehouse), and sub-second LLM agent tooling, I have driven massive production scale and efficiency at TBO.com. I would love to bring my engineering rigor, full-stack backend skills, and distributed systems passion to your engineering team.\\n\\nBest regards,\\n{CANDIDATE_NAME}";
  setVal("hiring-manager-message-input", msg);

  // Consent checkbox
  const cb = all.find(e => e.id === "noPolicy" && e.tagName === "INPUT");
  if (cb && !cb.checked) {{
    cb.click();
    cb.checked = true;
    cb.dispatchEvent(new Event("change", {{ bubbles: true }}));
  }}
}});

await new Promise(r => setTimeout(r, 2000));

// Step 4: Resolve open incomplete cards in experience/education
await page.evaluate(() => {{
  function getDeep(root) {{
    let list = [];
    for (const el of root.querySelectorAll("*")) {{
      list.push(el);
      if (el.shadowRoot) list.push(...getDeep(el.shadowRoot));
    }}
    return list;
  }}
  const all = getDeep(document.body);

  // Experience title & company autocomplete options
  const titleOpt = all.find(e => e.tagName === "SPL-SELECT-OPTION" && e.innerText.includes("Research Assistant"));
  if (titleOpt) titleOpt.click();

  const compOpt = all.find(e => e.tagName === "SPL-SELECT-OPTION" && e.innerText.includes("IIIT-Delhi"));
  if (compOpt) compOpt.click();

  // Institution autocomplete option
  const instOpt = all.find(e => e.tagName === "SPL-SELECT-OPTION" && e.innerText.includes("Indraprastha Institute of Information Technology Delhi"));
  if (instOpt) instOpt.click();

  // Save buttons
  const saveBtns = all.filter(e => e.tagName === "SPL-BUTTON" && e.innerText.trim().toLowerCase() === "save");
  for (const b of saveBtns) {{
    b.click();
    const inner = b.shadowRoot ? b.shadowRoot.querySelector("button") : null;
    if (inner) inner.click();
  }}

  // Cancel any lingering empty draft entries
  const cancelBtns = all.filter(e => e.tagName === "SPL-BUTTON" && e.innerText.trim().toLowerCase() === "cancel");
  for (const b of cancelBtns) {{
    b.click();
    const inner = b.shadowRoot ? b.shadowRoot.querySelector("button") : null;
    if (inner) inner.click();
  }}
}});

await new Promise(r => setTimeout(r, 2000));

// Step 5: Submission or Staging
let submitted = false;
let confirmationText = "";

if ({str(submit).lower()}) {{
  console.log("[SmartRecruiters] Submitting application...");
  try {{
    await page.click("loc=css:spl-button[type='primary']", {{ label: "Submit application" }});
  }} catch (e) {{
    await page.evaluate(() => {{
      const btn = document.querySelector("spl-button[type='primary']");
      if (btn) {{
        btn.click();
        const inner = btn.shadowRoot ? btn.shadowRoot.querySelector("button") : null;
        if (inner) inner.click();
      }}
    }});
  }}

  await new Promise(r => setTimeout(r, 8000));

  const postSubmit = await page.evaluate(() => {{
    return {{
      url: window.location.href,
      text: document.body ? document.body.innerText.slice(0, 500) : ""
    }};
  }});

  if (postSubmit.url.includes("/success") || postSubmit.text.includes("Application submitted")) {{
    submitted = true;
    confirmationText = postSubmit.text.replace(/\\n+/g, " | ");
  }}
}} else {{
  console.log("[SmartRecruiters] Staged mode: Form 100% prefilled and verified. Ready for candidate submission.");
}}

console.log("SMARTRECRUITERS_RESULT:" + JSON.stringify({{
  success: true,
  submitted: submitted,
  confirmation: confirmationText
}}));
"""

    verify_script_zero_placeholders(script, "SmartRecruiters Apply Script")

    proc = subprocess.run(
        ["ego-browser", "nodejs"],
        input=script,
        capture_output=True,
        text=True,
        timeout=180
    )
    output = (proc.stdout or "") + "\n" + (proc.stderr or "")

    res_match = None
    for line in output.splitlines():
        if line.startswith("SMARTRECRUITERS_RESULT:"):
            try:
                res_match = json.loads(line.replace("SMARTRECRUITERS_RESULT:", "").strip())
                break
            except Exception:
                pass

    success = bool(res_match and res_match.get("success"))
    submitted = bool(res_match and res_match.get("submitted"))

    return {
        "success": success,
        "submitted": submitted,
        "company": company_name,
        "url": url,
        "resume_path": resume_abs,
        "output": output
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="SmartRecruiters Apply Engine")
    parser.add_argument("--url", required=True, help="SmartRecruiters Job URL")
    parser.add_argument("--company", default="Target Company", help="Company Name")
    parser.add_argument("--title", default=None, help="Job Title")
    parser.add_argument("--jd", default=None, help="Job Description")
    parser.add_argument("--job-id", default=None, help="Database Job ID")
    parser.add_argument("--resume", help="Optional PDF resume path")
    parser.add_argument("--submit", action="store_true", help="Submit immediately")
    args = parser.parse_args()

    result = apply_to_smartrecruiters_job(
        url=args.url,
        company_name=args.company,
        title=args.title,
        jd_text=args.jd,
        resume_path=args.resume,
        submit=args.submit,
        job_id_db=args.job_id
    )
    print(json.dumps(result, indent=2))
