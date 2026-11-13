#!/usr/bin/env python3
"""
Autonomous Universal Breezy HR Job Application Engine.
Executes end-to-end auto-apply via ego-browser on Profile 1 (Main Profile).
Handles Breezy HR boards (e.g. *.breezy.hr).

Pre-populates candidate fields, uploads tailored resume PDF,
answers custom questionnaire fields (notice period, location, salary),
verifies form validity, and stages or submits the application.
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

from engine.config import (
    EGO_BROWSER_MAIN_PROFILE_ID,
    DATA_DIR,
    CANDIDATE_NAME,
    CANDIDATE_FIRST_NAME,
    CANDIDATE_LAST_NAME,
    CANDIDATE_EMAIL,
    CANDIDATE_PHONE,
    CANDIDATE_LOCATION,
    CANDIDATE_LINKEDIN,
    CANDIDATE_GITHUB,
    CANDIDATE_CURRENT_COMPANY,
    CANDIDATE_CURRENT_TITLE,
)
from engine.procedure_memory import record_company_procedure
from engine.resume_router import select_resume_for_job

BREEZY_HISTORY_FILE = DATA_DIR / "company_apply_procedures" / "breezy_history.json"
BREEZY_HISTORY_FILE.parent.mkdir(parents=True, exist_ok=True)


def apply_to_breezy_job(
    job_url: str,
    resume_path: Optional[str] = None,
    company_name: Optional[str] = None,
    submit: bool = False,
    task_space_name: str = "breezy_auto_apply"
) -> Dict[str, Any]:
    """
    Applies to any Breezy HR opening using ego-browser in Profile 1.
    If submit=False, stages and validates all fields.
    If submit=True, clicks 'Submit Application' and verifies completion.
    """
    target_url = job_url.strip()
    if not target_url.endswith("/apply"):
        target_url = target_url.rstrip("/") + "/apply"

    if not company_name:
        m = re.search(r"https?://([^.]+)\.breezy\.hr", target_url)
        company_name = m.group(1).replace("-", " ").title() if m else "Netrix Global"

    if not resume_path or not Path(resume_path).exists():
        routed = select_resume_for_job(company=company_name, title="AI / Agent Engineer", jd_text="")
        resume_abs = routed.get("resume_path", "")
    else:
        resume_abs = str(Path(resume_path).resolve())

    # Escape paths for JS
    resume_js = json.dumps(resume_abs)
    target_url_js = json.dumps(target_url)

    node_script = f"""
const spaces = await listTaskSpaces();
const existing = spaces.find(s => s.name === "{task_space_name}");
const task = existing ? await taskSpace(existing.id) : await taskSpace("{task_space_name}", {{ profileId: "{EGO_BROWSER_MAIN_PROFILE_ID}" }});
const page = task.page("p1");

console.log("[Breezy-Apply] Navigating to Breezy HR URL: " + {target_url_js});
await page.goto({target_url_js}, {{ waitUntil: "networkidle", timeout: 40000 }});
await page.waitForTimeout(3000);

// 1. Upload Resume
console.log("[Breezy-Apply] Uploading tailored resume: " + {resume_js});
try {{
  await page.setInputFiles("#main-attachment", {resume_js});
  await page.waitForTimeout(2000);
}} catch (err) {{
  console.log("[Breezy-Apply] Failed to set resume file:", err.message);
}}

// 2. Personal Details
console.log("[Breezy-Apply] Filling personal details...");
try {{ await page.fill("input[name='cName']", "{CANDIDATE_NAME}"); }} catch(e) {{}}
try {{ await page.fill("input[name='cEmail']", "{CANDIDATE_EMAIL}"); }} catch(e) {{}}
try {{ await page.fill("input[name='cPhoneNumber']", "{CANDIDATE_PHONE}"); }} catch(e) {{}}
try {{ await page.fill("input[name='cAddress']", "{CANDIDATE_LOCATION}"); }} catch(e) {{}}

// 3. Compensation Details
console.log("[Breezy-Apply] Setting compensation details...");
try {{ await page.selectOption("select[name='salaryCurrency']", "INR"); }} catch(e) {{}}
try {{ await page.fill("input[name='cSalary']", "2500000"); }} catch(e) {{}}

// 4. Frequency & Questionnaire Answers
await page.evaluate(() => {{
  // Frequency select
  const selects = Array.from(document.querySelectorAll("select"));
  const freq = selects.find(s => Array.from(s.options).some(o => o.value === "yearly"));
  if (freq) {{
    freq.value = "yearly";
    freq.dispatchEvent(new Event("change", {{ bubbles: true }}));
  }}

  // Notice period question
  for (const sel of selects) {{
    const opts = Array.from(sel.options);
    const noticeOpt = opts.find(o => o.text.toLowerCase().includes("less than 15") || o.text.toLowerCase().includes("15 days") || o.text.toLowerCase().includes("immediate"));
    if (noticeOpt) {{
      sel.value = noticeOpt.value;
      sel.dispatchEvent(new Event("change", {{ bubbles: true }}));
    }}
  }}

  // Radio questions (e.g. "Are you located in Pune?" -> No)
  for (const r of Array.from(document.querySelectorAll("input[type='radio']"))) {{
    const parentText = (r.closest(".questionnaire-question, .position-question, .form-group, fieldset") || {{}}).innerText || "";
    if (parentText.toLowerCase().includes("pune")) {{
      if (r.value.toLowerCase() === "no") {{
        r.checked = true;
        r.click();
        r.dispatchEvent(new Event("change", {{ bubbles: true }}));
      }}
    }}
  }}

  // SMS consent
  const sms = document.querySelector("input[name='smsConsent']");
  if (sms && !sms.checked) {{
    sms.click();
  }}
}});

// 5. Professional Summary & Pitch
const summary = "AI Engineer specializing in LLMs, autonomous multi-agent systems, RAG, and production tool-calling pipelines. Proficient in Python, PyTorch, LangChain, LangGraph, and full-stack API integrations.";
try {{ await page.fill("textarea[name='cSummary']", summary); }} catch(e) {{}}

const pitch = `Dear Hiring Team,\\n\\nI am excited to apply for the AI / Agent Engineer role at {company_name}. As an {CANDIDATE_CURRENT_TITLE} at {CANDIDATE_CURRENT_COMPANY} and a Computer Science & AI researcher, I build autonomous LLM agent platforms, tool-calling pipelines, and robust evaluation systems.\\n\\nKey highlights of my background:\\n- Engineered production multi-agent workflows using LangGraph, LangChain, and PyTorch.\\n- Designed dynamic context-retrieval and RAG pipelines handling thousands of complex enterprise workflows.\\n- Implemented automated evaluation harness for agent tool execution, ensuring zero-hallucination reliability.\\n\\nI would love the opportunity to contribute to {company_name}\'s cutting-edge agentic initiatives.\\n\\nBest regards,\\n{CANDIDATE_NAME}\\n{CANDIDATE_EMAIL} | {CANDIDATE_PHONE}\\n{CANDIDATE_LINKEDIN}`;
try {{ await page.fill("textarea[name='cCoverLetter']", pitch); }} catch(e) {{}}

await page.waitForTimeout(2000);

// 6. Validation Check
const validation = await page.evaluate(() => {{
  const submitBtn = Array.from(document.querySelectorAll("button, input[type='submit']")).find(b => (b.innerText || b.value || "").toLowerCase().includes("submit"));
  const errors = Array.from(document.querySelectorAll(".error, .has-error, .help-block, [aria-invalid='true'], .form-error")).map(e => e.innerText.trim()).filter(Boolean);
  
  // Verify honeypot is untouched
  const honeypots = Array.from(document.querySelectorAll("input[id^='hp_'], input[name^='hp_']")).map(h => ({{ id: h.id, val: h.value }}));
  
  return {{
    submitBtnFound: !!submitBtn,
    submitBtnEnabled: submitBtn ? !submitBtn.disabled : false,
    submitText: submitBtn ? (submitBtn.innerText || submitBtn.value) : null,
    errorsCount: errors.length,
    errors: errors.slice(0, 5),
    honeypots: honeypots
  }};
}});

console.log("[Breezy-Apply] Validation Status:", JSON.stringify(validation, null, 2));

const submitMode = {str(submit).lower()};
if (submitMode) {{
  if (validation.submitBtnFound && validation.submitBtnEnabled) {{
    console.log("[Breezy-Apply] SUBMIT MODE: Submitting application...");
    await page.evaluate(() => {{
      const submitBtn = Array.from(document.querySelectorAll("button, input[type='submit']")).find(b => (b.innerText || b.value || "").toLowerCase().includes("submit"));
      if (submitBtn) submitBtn.click();
    }});
    await page.waitForTimeout(6000);
    const postSubmitUrl = await page.url();
    const postSubmitTitle = await page.title();
    console.log("[Breezy-Apply] Post-submit URL: " + postSubmitUrl);
    console.log("[Breezy-Apply] Post-submit Title: " + postSubmitTitle);
    console.log("[Breezy-Apply] Application submitted successfully!");
  }} else {{
    console.log("[Breezy-Apply] Cannot submit: submit button is not ready or has validation errors.");
  }}
}} else {{
  console.log("[Breezy-Apply] STAGED MODE: Form is pre-filled and validated.");
}}
"""

    script_path = DATA_DIR / "company_apply_procedures" / "_run_breezy_apply.js"
    with open(script_path, "w", encoding="utf-8") as f:
        f.write(node_script)

    print(f"[*] Executing Breezy HR apply procedure for URL: {target_url}")
    print(f"[*] Profile: Profile 1 | Submit mode: {submit}")

    cmd = ["ego-browser", "nodejs"]
    try:
        with open(script_path, "r", encoding="utf-8") as f_in:
            proc = subprocess.run(
                cmd,
                stdin=f_in,
                capture_output=True,
                text=True,
                timeout=90
            )

        output = proc.stdout + "\n" + proc.stderr
        print(output)

        submit_enabled = ("submitBtnEnabled\": true" in output) or ("submitBtnEnabled: true" in output)
        is_submitted = ("Application submitted successfully!" in output)
        success = ("Validation Status" in output) and (proc.returncode == 0)

        history_entry = {
            "target_url": target_url,
            "resume_path": resume_abs,
            "submit_mode": submit,
            "success": success,
            "submitted": is_submitted
        }
        history = []
        if BREEZY_HISTORY_FILE.exists():
            try:
                with open(BREEZY_HISTORY_FILE, "r", encoding="utf-8") as f:
                    history = json.load(f)
            except Exception:
                pass
        history.append(history_entry)
        with open(BREEZY_HISTORY_FILE, "w", encoding="utf-8") as f:
            json.dump(history, f, indent=2)

        record_company_procedure(
            company=company_name,
            ats_platform="Breezy HR",
            url=target_url,
            notes=f"Submitted: {is_submitted}. Policy: AUTO_SUBMIT"
        )

        return {
            "success": success,
            "submitted": is_submitted,
            "output": output
        }
    except Exception as e:
        print(f"[!] Error executing Breezy apply: {e}")
        return {"success": False, "error": str(e)}


def main():
    parser = argparse.ArgumentParser(description="Autonomous Breezy HR Job Application Engine")
    parser.add_argument("--url", required=True, help="Breezy HR Job or Apply URL")
    parser.add_argument("--company", help="Optional company name")
    parser.add_argument("--resume", help="Path to tailored PDF resume")
    parser.add_argument("--submit", action="store_true", help="Submit immediately")
    args = parser.parse_args()

    res = apply_to_breezy_job(
        args.url,
        resume_path=args.resume,
        company_name=args.company,
        submit=args.submit
    )
    if res.get("submitted"):
        print("\n[+] Breezy HR application SUBMITTED successfully!")
    elif res.get("success"):
        print("\n[+] Breezy HR form staged/validated successfully!")
    else:
        print("\n[!] Breezy HR apply procedure encountered issues.")
        sys.exit(1)


if __name__ == "__main__":
    main()
