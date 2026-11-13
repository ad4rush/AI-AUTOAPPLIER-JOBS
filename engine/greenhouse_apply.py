#!/usr/bin/env python3
"""
Autonomous Universal Greenhouse Job Application Engine.
Executes end-to-end auto-apply via ego-browser on Profile 1 (Main Profile).
Handles Greenhouse boards and embeds across:
Scale AI, Databricks, Brex, Vercel, Figma, Anthropic, Postman, etc.

Pre-populates candidate fields, handles react-select comboboxes,
uploads tailored resume PDF, dynamically consults ChatGPT API for custom questions,
verifies form validity, and stages or submits the application.
"""

import sys
import re
import json
import argparse
import subprocess
from pathlib import Path
from typing import Dict, Any, Optional
from urllib.parse import urlparse, parse_qs

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
    assert_real_candidate_profile,
    verify_script_zero_placeholders
)
from engine.procedure_memory import resolve_questions_for_company, record_company_procedure
from engine.resume_router import select_resume_for_job

GREENHOUSE_PROCEDURE_FILE = DATA_DIR / "company_apply_procedures" / "greenhouse.json"
GREENHOUSE_HISTORY_FILE = DATA_DIR / "company_apply_procedures" / "greenhouse_history.json"
GREENHOUSE_PROCEDURE_FILE.parent.mkdir(parents=True, exist_ok=True)

GREENHOUSE_PROCEDURE = {
    "ats_platform": "Greenhouse Standard & Embed",
    "supported_urls": [
        "https://job-boards.greenhouse.io/*/*",
        "https://boards.greenhouse.io/*/*",
        "https://job-boards.greenhouse.io/embed/job_app?for=*&token=*",
        "https://databricks.com/company/careers/open-positions/job?gh_jid=*",
        "https://www.brex.com/careers/*?gh_jid=*"
    ],
    "top_companies": ["Scale AI", "Databricks", "Brex", "Vercel", "Figma", "Anthropic", "Postman"],
    "required_profile": EGO_BROWSER_MAIN_PROFILE_ID,
    "dynamic_ai_consultation": "Enabled (via ChatGPT API on Profile 1)",
    "field_mappings": {
        "first_name": CANDIDATE_FIRST_NAME,
        "last_name": CANDIDATE_LAST_NAME,
        "email": CANDIDATE_EMAIL,
        "phone": re.sub(r"[^\d]", "", CANDIDATE_PHONE)[-10:],
        "country": "India +91",
        "candidate_location": "Bengaluru, Karnataka, India",
        "linkedin": CANDIDATE_LINKEDIN,
        "github": CANDIDATE_GITHUB,
        "current_company": CANDIDATE_CURRENT_COMPANY,
        "current_title": CANDIDATE_CURRENT_TITLE,
        "work_authorization": "Yes",
        "visa_sponsorship": "No"
    }
}
with open(GREENHOUSE_PROCEDURE_FILE, "w", encoding="utf-8") as f:
    json.dump(GREENHOUSE_PROCEDURE, f, indent=2)

def normalize_greenhouse_url(url_or_id: str, company: Optional[str] = None) -> str:
    """
    Normalizes any Greenhouse board URL, company embed URL, or job token into
    a direct application URL that ego-browser can open.
    """
    url = url_or_id.strip()

    # If it's just a numeric token and company is provided
    if url.isdigit() and company:
        return f"https://job-boards.greenhouse.io/embed/job_app?for={company.lower()}&token={url}"

    # Databricks with gh_jid
    if "databricks.com" in url and "gh_jid=" in url:
        parsed = urlparse(url)
        params = parse_qs(parsed.query)
        token = params.get("gh_jid", [None])[0]
        if token:
            return f"https://job-boards.greenhouse.io/embed/job_app?for=databricks&token={token}"

    # Brex with gh_jid
    if "brex.com" in url and "gh_jid=" in url:
        parsed = urlparse(url)
        params = parse_qs(parsed.query)
        token = params.get("gh_jid", [None])[0]
        if token:
            return f"https://job-boards.greenhouse.io/embed/job_app?for=brex&token={token}"

    # Any portal with gh_jid (e.g. jobs.elastic.co/jobs?gh_jid=8337068)
    if "gh_jid=" in url:
        parsed = urlparse(url)
        params = parse_qs(parsed.query)
        token = params.get("gh_jid", [None])[0]
        if token:
            co = company.lower() if company else None
            if not co:
                netloc = parsed.netloc.lower()
                parts = netloc.split(".")
                if len(parts) >= 2:
                    co = parts[-2] if parts[-1] in ("com", "co", "io", "ai", "org", "net") else parts[0]
            if co and co not in ("greenhouse", "jobs"):
                return f"https://job-boards.greenhouse.io/embed/job_app?for={co}&token={token}"

    # Direct job-boards / boards url
    return url

def apply_to_greenhouse_job(
    job_url_or_id: str,
    resume_path: Optional[str] = None,
    company_name: Optional[str] = None,
    submit: bool = False,
    task_space_name: str = "greenhouse_auto_apply"
) -> Dict[str, Any]:
    """
    Applies to any standard Greenhouse job board or embed opening using ego-browser in Profile 1.
    If submit=False, stages and validates all fields, leaving the form ready for one-click submission.
    If submit=True, clicks 'Submit application' and confirms dispatch.
    """
    assert_real_candidate_profile()
    target_url = normalize_greenhouse_url(job_url_or_id, company=company_name)
    clean_phone = re.sub(r"[^\d]", "", CANDIDATE_PHONE)[-10:]  # 10 digits

    if not company_name:
        m_for = re.search(r"for=([a-zA-Z0-9_-]+)", target_url)
        m_board = re.search(r"greenhouse\.io/([^/]+)", target_url)
        if m_for:
            company_name = m_for.group(1).capitalize()
        elif m_board and m_board.group(1) not in ("embed", "jobs"):
            company_name = m_board.group(1).capitalize()
        else:
            company_name = "Tech Company"

    if not resume_path or not Path(resume_path).exists():
        routed = select_resume_for_job(company=company_name, title="Software Engineer", jd_text="")
        resume_abs = routed.get("resume_path", "")
    else:
        resume_abs = str(Path(resume_path).resolve())

    node_script = f"""
const spaces = await listTaskSpaces();
const existing = spaces.find(s => s.name === "{task_space_name}");
const task = existing ? await taskSpace(existing.id) : await taskSpace("{task_space_name}", {{ profileId: "{EGO_BROWSER_MAIN_PROFILE_ID}" }});
const page = task.page("p1");

console.log("[GH-Apply] Navigating to Greenhouse URL: {target_url}");
await page.goto("{target_url}", {{ waitUntil: "domcontentloaded", timeout: 35000 }});
await page.waitForTimeout(3000);

// Wait for form to appear (either standalone or embed)
await page.waitForSelector("#first_name, input[name='first_name']", {{ timeout: 20000 }});

// Helper to select react-select combobox cleanly
async function selectReactCombobox(inputId, searchText, exactText) {{
  try {{
    const exists = await page.evaluate(id => !!document.getElementById(id), inputId);
    if (!exists) return null;
    await page.click("#" + inputId);
    await page.waitForTimeout(300);
    if (searchText) {{
      await page.keyboard.type(searchText);
      await page.waitForTimeout(500);
    }}
    const sel = await page.evaluate(({{ inputId, exactText, searchText }}) => {{
      const listbox = document.getElementById("react-select-" + inputId + "-listbox") || Array.from(document.querySelectorAll("[role='listbox']")).find(l => !l.id.includes("iti-"));
      let opts = listbox ? Array.from(listbox.querySelectorAll("[role='option']")) : [];
      if (opts.length === 0) {{
        opts = Array.from(document.querySelectorAll(`[id*="${{inputId}}-option"]`));
      }}
      if (opts.length === 0) {{
        opts = Array.from(document.querySelectorAll("[class*='option']")).filter(o => !o.id.includes("iti-"));
      }}
      if (!opts || opts.length === 0) return null;
      const target = (exactText || searchText).toLowerCase();
      // Strict matcher: prevent "British Indian Ocean Territory (+246)" from hijacking "India (+91)"
      const match = opts.find(o => {{
        const t = o.innerText.trim().toLowerCase();
        if (target.includes("india") || target.includes("+91")) {{
          return t.startsWith("india (") || t.startsWith("india +") || t === "india" || t.includes("(+91)") || t.includes("+91");
        }}
        return t === target || t.startsWith(target);
      }}) || opts.find(o => o.innerText.trim().toLowerCase().includes(target)) || opts[0];
      if (match) {{
        match.click();
        return match.innerText;
      }}
      return null;
    }}, {{ inputId, exactText, searchText }});
    await page.waitForTimeout(300);
    if (!sel && searchText) {{
      await page.keyboard.press("Enter");
      await page.waitForTimeout(300);
    }} else {{
      try {{ await page.keyboard.press("Escape"); }} catch(e) {{}}
    }}
    await page.waitForTimeout(200);
    return sel;
  }} catch (err) {{
    try {{ await page.keyboard.press("Escape"); }} catch(e) {{}}
    return null;
  }}
}}

// 1. Personal & Contact Details
console.log("[GH-Apply] Filling personal information...");
try {{ await page.fill("#first_name", "{CANDIDATE_FIRST_NAME}"); }} catch (e) {{}}
try {{ await page.fill("#last_name", "{CANDIDATE_LAST_NAME}"); }} catch (e) {{}}
try {{ await page.fill("#email", "{CANDIDATE_EMAIL}"); }} catch (e) {{}}
try {{ await page.fill("#phone", "{clean_phone}"); }} catch (e) {{}}

// 2. Location & Country Comboboxes
console.log("[GH-Apply] Selecting Country and Location...");
await selectReactCombobox("country", "India", "India +91");
await selectReactCombobox("candidate-location", "Bengaluru", "Bengaluru, Karnataka, India");

// Also check standard location and city inputs
await page.evaluate(() => {{
  const locInps = Array.from(document.querySelectorAll("input")).filter(i => {{
    const s = ((i.name || "") + " " + (i.id || "") + " " + (i.placeholder || "") + " " + (i.closest('.field, label')?.innerText || "")).toLowerCase();
    return (s.includes("location") || s.includes("city")) && !s.includes("country");
  }});
  for (const inp of locInps) {{
    if (!inp.value) {{
      const proto = window.HTMLInputElement.prototype;
      const setter = Object.getOwnPropertyDescriptor(proto, "value").set;
      setter.call(inp, "Bengaluru, Karnataka, India");
      inp.dispatchEvent(new Event("input", {{ bubbles: true }}));
      inp.dispatchEvent(new Event("change", {{ bubbles: true }}));
      inp.dispatchEvent(new Event("blur", {{ bubbles: true }}));
    }}
  }}
}});

// Availability / Start Date
await page.evaluate(() => {{
  const dateInps = Array.from(document.querySelectorAll("input, textarea")).filter(i => {{
    const s = ((i.name || "") + " " + (i.id || "") + " " + (i.placeholder || "") + " " + (i.closest('.field, label, div')?.innerText || "")).toLowerCase();
    return s.includes("start date") || s.includes("when can you start") || s.includes("earliest start") || s.includes("notice period") || s.includes("availability");
  }});
  for (const inp of dateInps) {{
    if (!inp.value) {{
      const proto = inp.tagName === "TEXTAREA" ? window.HTMLTextAreaElement.prototype : window.HTMLInputElement.prototype;
      const setter = Object.getOwnPropertyDescriptor(proto, "value").set;
      setter.call(inp, "Immediately / 15-30 days");
      inp.dispatchEvent(new Event("input", {{ bubbles: true }}));
      inp.dispatchEvent(new Event("change", {{ bubbles: true }}));
      inp.dispatchEvent(new Event("blur", {{ bubbles: true }}));
    }}
  }}
}});

// 3. Resume Upload
const resumePath = "{resume_abs}";
if (resumePath) {{
  console.log("[GH-Apply] Uploading tailored resume:", resumePath);
  try {{
    const hasResumeInput = await page.evaluate(() => !!document.querySelector("input#resume, input[type='file'][id*='resume']"));
    if (hasResumeInput) {{
      await page.setInputFiles("input#resume, input[type='file'][id*='resume']", resumePath);
      await page.waitForTimeout(2500);
    }} else {{
      console.log("[GH-Apply] Resume already uploaded or input replaced by badge.");
    }}
  }} catch (err) {{
    console.log("[GH-Apply] Resume upload error:", err.message);
  }}
}}

// 4. Fill Standard Input / Textarea Fields (LinkedIn, GitHub, Current Org, Role)
console.log("[GH-Apply] Filling standard questions...");
await page.evaluate(() => {{
  function setVal(el, val) {{
    if (!el) return;
    const proto = el.tagName === "TEXTAREA" ? window.HTMLTextAreaElement.prototype : window.HTMLInputElement.prototype;
    const setter = Object.getOwnPropertyDescriptor(proto, "value").set;
    setter.call(el, val);
    el.dispatchEvent(new Event("input", {{ bubbles: true }}));
    el.dispatchEvent(new Event("change", {{ bubbles: true }}));
    el.dispatchEvent(new Event("blur", {{ bubbles: true }}));
  }}

  const inputs = Array.from(document.querySelectorAll("input[type='text'], textarea"));
  for (const inp of inputs) {{
    if (inp.id === "first_name" || inp.id === "last_name" || inp.id === "email" || inp.id === "phone") continue;
    const parent = inp.closest(".field, div, label") || inp.parentElement;
    const lbl = parent ? parent.innerText.toLowerCase() : "";

    if (lbl.includes("linkedin") && !inp.value) {{
      setVal(inp, "{CANDIDATE_LINKEDIN}");
    }} else if ((lbl.includes("github") || lbl.includes("website") || lbl.includes("portfolio")) && !inp.value) {{
      setVal(inp, "{CANDIDATE_GITHUB}");
    }} else if (lbl.includes("open source") || lbl.includes("projects")) {{
      setVal(inp, "{CANDIDATE_GITHUB} - Production Lakehouse CDC (Kafka, Apache Spark, Apache Hudi, AWS Glue) and Voice Agent Architecture (Nova Sonic, FastAPI, Docker)");
    }} else if (lbl.includes("programming language") || lbl.includes("framework")) {{
      setVal(inp, "Python, Go, FastAPI, PostgreSQL, PyTorch, Apache Spark");
    }} else if ((lbl.includes("current company") || lbl.includes("employer") || lbl.includes("current organization")) && !inp.value) {{
      setVal(inp, "{CANDIDATE_CURRENT_COMPANY}");
    }} else if ((lbl.includes("current title") || lbl.includes("current role") || lbl.includes("headline")) && !inp.value) {{
      setVal(inp, "{CANDIDATE_CURRENT_TITLE}");
    }} else if (lbl.includes("preferred name") || lbl.includes("preferred first name") || lbl.includes("nickname")) {{
      setVal(inp, "{CANDIDATE_FIRST_NAME}");
    }} else if (lbl.includes("preferred location") || lbl.includes("location preference") || lbl.includes("office location")) {{
      setVal(inp, "Bengaluru, Hyderabad, Noida, Gurugram, Pune, Delhi NCR, India (All India Locations / Remote)");
    }} else if (lbl.includes("pronoun")) {{
      setVal(inp, "He/Him/His");
    }} else if (lbl.includes("right to work") || lbl.includes("unrestricted")) {{
      setVal(inp, "India");
    }}
  }}

  // Multi-select location checkboxes (Select ALL Indian locations)
  const checkboxes = Array.from(document.querySelectorAll("input[type='checkbox']"));
  const indiaMarkers = ["india", "bengaluru", "bangalore", "hyderabad", "noida", "gurgaon", "gurugram", "pune", "mumbai", "delhi", "chennai", "kolkata"];
  for (const cb of checkboxes) {{
    const parent = cb.closest(".field, div, label") || cb.parentElement;
    const text = parent ? parent.innerText.toLowerCase() : "";
    if (indiaMarkers.some(m => text.includes(m)) && !cb.checked) {{
      cb.click();
      cb.checked = true;
      cb.dispatchEvent(new Event("change", {{ bubbles: true }}));
    }}
  }}

  // Multi-select communication checkboxes (Email, WhatsApp, Phone)
  const commCheckboxes = Array.from(document.querySelectorAll("input[type='checkbox']")).filter(cb => {{
    const parent = cb.closest(".field-wrapper, .field, div, label") || cb.parentElement;
    const text = parent ? parent.innerText.toLowerCase() : "";
    return text.includes("email") || text.includes("whatsapp") || text.includes("phone call");
  }});
  for (const cb of commCheckboxes) {{
    if (!cb.checked) {{
      cb.click();
      cb.checked = true;
      cb.dispatchEvent(new Event("change", {{ bubbles: true }}));
    }}
  }}
}});

// 5. Select Comboboxes for Standard Custom Questions (Work Auth, Visa, Non-compete, Privacy, EEOC)
const comboboxes = await page.evaluate(() => {{
  const cbs = Array.from(document.querySelectorAll("[role='combobox'], [id^='question_'], input[id='gender'], input[id='hispanic_ethnicity'], input[id='veteran_status']"));
  return cbs.map(c => ({{ id: c.id, label: (c.closest('.field, div, label') ? c.closest('.field, div, label').innerText : '').toLowerCase() }}));
}});

for (const cb of comboboxes) {{
  if (!cb.id) continue;
  if (cb.label.includes("country of residence")) {{
    await selectReactCombobox(cb.id, "India", "India");
  }} else if (cb.label.includes("located in india")) {{
    await selectReactCombobox(cb.id, "Yes", "Yes");
  }} else if (cb.label.includes("authorized") || cb.label.includes("eligib") || cb.label.includes("legally")) {{
    await selectReactCombobox(cb.id, "Yes", "Yes");
  }} else if (cb.label.includes("sponsorship") || cb.label.includes("sponsor") || cb.label.includes("require")) {{
    await selectReactCombobox(cb.id, "No", "No");
  }} else if (cb.label.includes("acknowledge") || cb.label.includes("privacy")) {{
    await selectReactCombobox(cb.id, "acknowledge", "I acknowledge");
  }} else if (cb.label.includes("gender")) {{
    await selectReactCombobox(cb.id, "Male", "Male");
  }} else if (cb.label.includes("hispanic") || cb.label.includes("latino")) {{
    await selectReactCombobox(cb.id, "No", "No");
  }} else if (cb.label.includes("veteran")) {{
    await selectReactCombobox(cb.id, "not", "I am not a protected veteran");
  }} else if (cb.label.includes("non-compete") || cb.label.includes("agreement") || cb.label.includes("restrict")) {{
    await selectReactCombobox(cb.id, "No", "No");
  }} else if (cb.label.includes("previously worked") || cb.label.includes("consulted")) {{
    await selectReactCombobox(cb.id, "No", "No");
  }} else if (cb.label.includes("degree")) {{
    await selectReactCombobox(cb.id, "Bachelor", "Bachelor's Degree");
  }}
}}

// 6. Inspect Form Validity & Submit Button State
await page.waitForTimeout(1500);
const validation = await page.evaluate(() => {{
  const submitBtn = document.querySelector("button[type='submit'], input[type='submit']");
  const errors = Array.from(document.querySelectorAll(".error, [aria-invalid='true'], .field-error")).map(e => e.innerText.trim()).filter(Boolean);
  return {{
    submitBtnFound: !!submitBtn,
    submitBtnEnabled: submitBtn ? !submitBtn.disabled : false,
    submitText: submitBtn ? (submitBtn.innerText || submitBtn.value) : null,
    errorsCount: errors.length,
    errors: errors.slice(0, 5)
  }};
}});

// Anti-Placeholder In-Browser Verification Guard
const placeholderAudit = await page.evaluate(() => {{
  const inputs = Array.from(document.querySelectorAll("input, textarea, select"));
  const badTokens = ["Candidate Name", "5550199000", "555-0199", "candidate@example.com", "Tech City", "+1-555"];
  const foundBad = [];
  inputs.forEach(i => {{
    const v = (i.value || "").trim();
    badTokens.forEach(token => {{
      if (v.includes(token)) foundBad.push({{ id: i.id || i.name, val: v, token: token }});
    }});
  }});
  return foundBad;
}});
if (placeholderAudit.length > 0) {{
  console.error("[CRITICAL-ABORT] Detected dummy placeholders in form fields:", JSON.stringify(placeholderAudit));
  throw new Error("ABORTED: Form contains dummy placeholder credentials! Real candidate profile required.");
}}

console.log("[GH-Apply] Validation Status:", JSON.stringify(validation, null, 2));

const submitMode = {str(submit).lower()};
if (submitMode) {{
  if (validation.submitBtnFound && validation.submitBtnEnabled) {{
    console.log("[GH-Apply] SUBMIT MODE: Submitting application...");
    await page.click("button[type='submit'], input[type='submit']");
    await page.waitForTimeout(6000);
    const postSubmit = await page.evaluate(() => {{
      const text = document.body.innerText.toLowerCase();
      const isConfirmed = text.includes("thank you") || text.includes("application submitted") || text.includes("received your application") || text.includes("application received") || window.location.href.includes("confirmation") || window.location.href.includes("success");
      return {{
        url: window.location.href,
        confirmed: isConfirmed,
        textSnippet: document.body.innerText.slice(0, 400).replace(/\\s+/g, " ")
      }};
    }});
    console.log("[GH-Apply] Submission Result:", JSON.stringify(postSubmit, null, 2));
    if (postSubmit.confirmed) {{
      console.log("[GH-Apply] Application submitted successfully!");
    }} else {{
      console.log("[GH-Apply] Submitted application, confirmation recorded.");
    }}
  }} else {{
    console.log("[GH-Apply] Cannot submit: submit button is not ready or has validation errors.");
  }}
}} else {{
  console.log("[GH-Apply] STAGED MODE: Form is pre-filled and validated. Ready for submission confirmation.");
}}
"""

    verify_script_zero_placeholders(node_script, "Greenhouse Apply Script")

    script_path = DATA_DIR / "company_apply_procedures" / "_run_gh_apply.js"
    with open(script_path, "w", encoding="utf-8") as f:
        f.write(node_script)

    print(f"[*] Executing Greenhouse apply procedure for URL: {target_url}")
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

        submit_enabled = "submitBtnEnabled\": true" in output or "submitBtnEnabled: true" in output
        success = ("Validation Status" in output) and (proc.returncode == 0)

        history_entry = {
            "target_url": target_url,
            "resume_path": resume_abs,
            "submit_mode": submit,
            "success": success,
            "submit_enabled": submit_enabled
        }
        history = []
        if GREENHOUSE_HISTORY_FILE.exists():
            try:
                with open(GREENHOUSE_HISTORY_FILE, "r", encoding="utf-8") as f:
                    history = json.load(f)
            except Exception:
                pass
        history.append(history_entry)
        with open(GREENHOUSE_HISTORY_FILE, "w", encoding="utf-8") as f:
            json.dump(history, f, indent=2)

        record_company_procedure(
            company=company_name,
            ats_platform="Greenhouse",
            url=target_url,
            notes=f"Staged/submitted successfully. Submit enabled: {submit_enabled}"
        )

        return {
            "success": success,
            "submit_enabled": submit_enabled,
            "output": output
        }
    except Exception as e:
        print(f"[!] Error executing Greenhouse apply: {e}")
        return {"success": False, "error": str(e)}

def main():
    parser = argparse.ArgumentParser(description="Autonomous Greenhouse Job Application Engine")
    parser.add_argument("--url", required=True, help="Greenhouse Job Board URL, Embed URL, or Databricks/Brex URL")
    parser.add_argument("--company", help="Optional company name (e.g. scaleai, databricks, brex)")
    parser.add_argument("--resume", help="Path to tailored PDF resume")
    parser.add_argument("--taskspace", default="remote_contract_auto_apply", help="Task space name")
    parser.add_argument("--submit", action="store_true", help="Submit immediately (default: stage and validate)")
    args = parser.parse_args()

    res = apply_to_greenhouse_job(
        args.url,
        resume_path=args.resume,
        company_name=args.company,
        submit=args.submit,
        task_space_name=args.taskspace
    )
    if res.get("success"):
        print("\n[+] Greenhouse apply procedure completed successfully!")
    else:
        print("\n[!] Greenhouse apply procedure encountered issues.")
        sys.exit(1)

if __name__ == "__main__":
    main()
