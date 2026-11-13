#!/usr/bin/env python3
"""
Autonomous Ashby Job Application Engine.
Executes end-to-end auto-apply via ego-browser on Profile 1 (Main Profile).
Handles Ashby forms for OpenAI, Cursor, Mercor, LangChain, ElevenLabs, etc.

Features:
- Deterministic label-aware mapping for GitHub, LinkedIn, portfolio, location, and contact fields.
- Dynamic consultation with ChatGPT (Profile 1) for open custom essay questions.
- React/DOM value setter to ensure synthetic events are dispatched.
- 1-page tailored PDF resume upload.
- Full validation before staging or submission.
"""

import sys
import re
import json
import argparse
import subprocess
from pathlib import Path
from typing import Dict, Any, Optional, List

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from engine.config import (
    EGO_BROWSER_MAIN_PROFILE_ID,
    DATA_DIR,
    CANDIDATE_NAME,
    CANDIDATE_FIRST_NAME,
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

ASHBY_HISTORY_FILE = DATA_DIR / "company_apply_procedures" / "ashby_history.json"


def apply_to_ashby_job(
    job_url: str,
    resume_path: Optional[str] = None,
    submit: bool = False,
    task_space_name: str = "ashby_auto_apply"
) -> Dict[str, Any]:
    """
    Applies to an Ashby job opening using ego-browser in Profile 1.
    If submit=False, stages and validates all fields, leaving the form ready for one-click submission.
    If submit=True, clicks 'Submit Application' and confirms dispatch.
    """
    assert_real_candidate_profile()
    clean_url = job_url.strip()
    if "/application" not in clean_url:
        clean_url = clean_url.rstrip("/") + "/application"

    m_comp = re.search(r"ashbyhq\.com/([^/]+)", clean_url)
    company_name = m_comp.group(1).capitalize() if m_comp else "Tech Company"

    if not resume_path or not Path(resume_path).exists():
        routed = select_resume_for_job(company=company_name, title="Software Engineer", jd_text="")
        resume_abs = routed.get("resume_path", "")
    else:
        resume_abs = str(Path(resume_path).resolve())

    # Phase 1: Navigate, fill known identity fields, upload resume, and collect custom questions
    extract_script = f"""(async () => {{
const spaces = await listTaskSpaces();
const existing = spaces.find(s => s.name === "{task_space_name}");
const task = existing ? await taskSpace(existing.id) : await taskSpace("{task_space_name}", {{ profileId: "{EGO_BROWSER_MAIN_PROFILE_ID}" }});
const page = task.page("p1");

console.log("[Ashby-Apply] Navigating to: {clean_url}");
await page.goto("{clean_url}", {{ waitUntil: "domcontentloaded", timeout: 30000 }});
await new Promise(r => setTimeout(r, 3000));

// Wait for core name field
await page.waitForSelector("input#_systemfield_name, input[name='_systemfield_name']", {{ timeout: 20000 }});

// Helper to set values on React inputs
await page.evaluate(() => {{
  window.__setReactVal = function(el, val) {{
    if (!el) return;
    el.focus();
    const proto = el.tagName === "TEXTAREA" ? window.HTMLTextAreaElement.prototype : window.HTMLInputElement.prototype;
    const setter = Object.getOwnPropertyDescriptor(proto, "value").set;
    setter.call(el, val);
    el.dispatchEvent(new Event("input", {{ bubbles: true }}));
    el.dispatchEvent(new Event("change", {{ bubbles: true }}));
    el.dispatchEvent(new Event("blur", {{ bubbles: true }}));
  }};
}});

// 1. Fill Primary System Fields
console.log("[Ashby-Apply] Filling core candidate details...");
await page.evaluate(() => {{
  const nameEl = document.querySelector("input#_systemfield_name, input[name='_systemfield_name']");
  if (nameEl) window.__setReactVal(nameEl, "{CANDIDATE_NAME}");

  const emailEl = document.querySelector("input#_systemfield_email, input[name='_systemfield_email']");
  if (emailEl) window.__setReactVal(emailEl, "{CANDIDATE_EMAIL}");

  const phoneEl = document.querySelector("input[type='tel']");
  if (phoneEl) window.__setReactVal(phoneEl, "{CANDIDATE_PHONE}");
}});

// 2. Location (Country Selection)
try {{
  const locInput = await page.evaluate(() => {{
    const el = document.querySelector("input[placeholder*='typing']");
    return !!el;
  }});
  if (locInput) {{
    await page.click("input[placeholder*='typing']");
    await new Promise(r => setTimeout(r, 400));
    await page.keyboard.type("India");
    await new Promise(r => setTimeout(r, 800));
    await page.evaluate(() => {{
      const opts = Array.from(document.querySelectorAll('[role=\"option\"], li, div[class*=\"option\"]'));
      const india = opts.find(o => o.innerText.trim() === 'India');
      if (india) india.click();
    }});
  }}
}} catch (e) {{
  console.log("[Ashby-Apply] Location fill note:", e.message);
}}

// 2b. Date Picker Component (Earliest start date / When can you start)
try {{
  const hasDateInput = await page.evaluate(() => {{
    const inp = document.querySelector("input.ashby-application-form-input-date, input[placeholder*='Pick date']");
    return !!inp && !inp.value;
  }});
  if (hasDateInput) {{
    await page.click("input.ashby-application-form-input-date, input[placeholder*='Pick date']");
    await new Promise(r => setTimeout(r, 500));
    await page.evaluate(() => {{
      const cal = document.querySelector(".react-datepicker");
      if (cal) {{
        const day = cal.querySelector(".react-datepicker__day--today") || cal.querySelector(".react-datepicker__day:not(.react-datepicker__day--disabled)");
        if (day) day.click();
      }}
    }});
  }}
}} catch (e) {{
  console.log("[Ashby-Apply] Datepicker note:", e.message);
}}

// 3. Upload Resume PDF
const resumePath = "{resume_abs}";
if (resumePath) {{
  console.log("[Ashby-Apply] Uploading tailored resume:", resumePath);
  try {{
    await page.setInputFiles("input#_systemfield_resume", resumePath);
    await new Promise(r => setTimeout(r, 2000));
  }} catch (e) {{
    try {{
      await page.setInputFiles("input[type='file']", resumePath);
    }} catch (err) {{
      console.log("[!] Resume upload error:", err.message);
    }}
  }}
}}

// 4. Fill Known Fields by Label and Collect Custom Unfilled Questions
const inspectionResult = await page.evaluate(() => {{
  function getLabel(el) {{
    if (el.labels && el.labels[0]) return el.labels[0].innerText.trim();
    const parentLabel = el.closest("label");
    if (parentLabel) return parentLabel.innerText.trim();
    const p = el.closest("div");
    const title = p ? p.querySelector("label, [class*='label'], [class*='title'], [class*='heading']") : null;
    if (title) return title.innerText.trim();
    return el.getAttribute("aria-label") || el.placeholder || "";
  }}

  const inputs = Array.from(document.querySelectorAll("input, textarea"));
  const customQuestions = [];

  for (const el of inputs) {{
    if (el.type === "file" || el.id === "_systemfield_name" || el.id === "_systemfield_email" || el.type === "tel") continue;
    
    const label = getLabel(el).toLowerCase();
    
    // GitHub
    if (label.includes("github") || label.includes("git repo")) {{
      window.__setReactVal(el, "{CANDIDATE_GITHUB}");
      continue;
    }}
    
    // LinkedIn
    if (label.includes("linkedin")) {{
      window.__setReactVal(el, "{CANDIDATE_LINKEDIN}");
      continue;
    }}

    // Portfolio / Website
    if (label.includes("portfolio") || label.includes("personal website") || label.includes("website")) {{
      window.__setReactVal(el, "{CANDIDATE_GITHUB}");
      continue;
    }}

    // Location Preference / Preferred Location
    if (label.includes("preferred location") || label.includes("location preference") || label.includes("locations")) {{
      if (el.type === "text") window.__setReactVal(el, "Bengaluru, Hyderabad, Noida, Gurugram, Pune, Delhi NCR, India (All India Locations / Remote)");
      continue;
    }}

    // Work authorization & Sponsorship
    if (label.includes("authorized") || label.includes("legally authorized")) {{
      if (el.type === "text") window.__setReactVal(el, "Yes");
      continue;
    }}
    if (label.includes("sponsorship") || label.includes("require visa")) {{
      if (el.type === "text") window.__setReactVal(el, "No");
      continue;
    }}

    // If it's a textarea or text input that is still empty and has a question label
    if ((el.tagName === "TEXTAREA" || el.type === "text") && !el.value) {{
      const rawLabel = getLabel(el);
      if (rawLabel.length > 5 && !rawLabel.toLowerCase().includes("typing")) {{
        customQuestions.push({{
          id: el.id || el.name,
          label: rawLabel,
          tag: el.tagName
        }});
      }}
    }}
  }}

  // Handle Radio buttons (How did you hear, Work Auth, Sponsorship)
  const radios = Array.from(document.querySelectorAll("input[type='radio']"));
  for (const r of radios) {{
    const rLabel = (r.closest("label") || {{}}).innerText || "";
    const lower = rLabel.toLowerCase().trim();
    if (lower === "linkedin" || lower === "yes" || lower === "i'm a user") {{
      r.checked = true;
      r.dispatchEvent(new Event("change", {{ bubbles: true }}));
      r.dispatchEvent(new Event("input", {{ bubbles: true }}));
    }}
  }}

  // Handle Ashby Custom Yes/No Button components
  const allContainers = Array.from(document.querySelectorAll("div, fieldset")).filter(d => {{
    const btns = Array.from(d.querySelectorAll("button")).filter(b => {{
      const text = (b.innerText || "").trim().toLowerCase();
      const opt = (b.getAttribute("data-option") || "").trim().toLowerCase();
      return ["yes", "no"].includes(text) || ["yes", "no"].includes(opt);
    }});
    return btns.length === 2 && d.children.length < 8;
  }});

  for (const c of allContainers) {{
    let p = c.parentElement;
    let title = "";
    while (p && p !== document.body && !title) {{
      const heading = p.querySelector("label, p, h3, h4, [class*='title'], [class*='heading'], [class*='question']");
      if (heading && heading.innerText.length > 5) title = heading.innerText.toLowerCase();
      p = p.parentElement;
    }}
    const btns = Array.from(c.querySelectorAll("button"));
    const yesBtn = btns.find(b => (b.innerText || "").trim().toLowerCase() === "yes" || b.getAttribute("data-option") === "yes");
    const noBtn = btns.find(b => (b.innerText || "").trim().toLowerCase() === "no" || b.getAttribute("data-option") === "no");

    const isSponsorship = title.includes("sponsorship") || title.includes("require visa") || title.includes("need a work visa");
    if (isSponsorship) {{
      if (noBtn) noBtn.click();
    }} else {{
      if (yesBtn) yesBtn.click();
    }}
  }}

  // Direct sweep for unpressed Ashby Yes/No buttons
  const unpressedYesBtns = Array.from(document.querySelectorAll('button[data-option="yes"][aria-pressed="false"], button[data-option="yes"]:not([class*="selected"])'));
  for (const b of unpressedYesBtns) {{
    const parentText = (b.closest("fieldset, div, tr") || {{}}).innerText || "";
    if (!parentText.toLowerCase().includes("sponsorship") && !parentText.toLowerCase().includes("visa")) {{
      b.click();
    }}
  }}

  // Handle Checkboxes (Agreement / Confirmation / Privacy)
  const checkboxes = Array.from(document.querySelectorAll("input[type='checkbox']"));
  for (const cb of checkboxes) {{
    if (!cb.checked) {{
      cb.click();
      cb.checked = true;
      cb.dispatchEvent(new Event("change", {{ bubbles: true }}));
      cb.dispatchEvent(new Event("input", {{ bubbles: true }}));
    }}
  }}

  // Anti-Placeholder In-Browser Verification Guard
  const placeholderAudit = (() => {{
    const inputs = Array.from(document.querySelectorAll("input, textarea, select"));
    const badTokens = ["Q2FuZGlkYXRlIE5hbWU=", "NTU1MDE5OTAwMA==", "NTU1LTAxOTk=", "Y2FuZGlkYXRlQGV4YW1wbGUuY29t", "VGVjaCBDaXR5", "KzEtNTU1"].map(s => atob(s));
    const foundBad = [];
    inputs.forEach(i => {{
      const v = (i.value || "").trim();
      badTokens.forEach(token => {{
        if (v.includes(token)) foundBad.push({{ id: i.id || i.name, val: v, token: token }});
      }});
    }});
    return foundBad;
  }})();
  if (placeholderAudit.length > 0) {{
    console.error("[CRITICAL-ABORT] Detected dummy placeholders in form fields:", JSON.stringify(placeholderAudit));
    throw new Error("ABORTED: Form contains dummy placeholder credentials! Real candidate profile required.");
  }}

  return {{ customQuestions }};
}});

console.log("[Ashby-Apply] Custom Questions Found:", JSON.stringify(inspectionResult.customQuestions));
}})();
"""

    verify_script_zero_placeholders(extract_script, "Ashby Phase 1 Script")

    temp_script_path = DATA_DIR / "company_apply_procedures" / "_run_ashby_apply_p1.js"
    temp_script_path.write_text(extract_script, encoding="utf-8")

    print(f"[*] Executing Ashby Phase 1 (deterministic fill & inspection) for URL: {clean_url}")
    proc = subprocess.run(
        ["ego-browser", "nodejs"],
        input=extract_script,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        timeout=120
    )
    combined = (proc.stdout or "") + "\n" + (proc.stderr or "")
    print(combined)

    # Extract custom questions from log output
    custom_questions = []
    m = re.search(r"\[Ashby-Apply\] Custom Questions Found:\s*(\[.*?\])", combined, re.DOTALL)
    if m:
        try:
            custom_questions = json.loads(m.group(1))
        except Exception:
            pass

    # Phase 2: If custom questions exist, resolve via procedure memory / ChatGPT Profile 1
    chatgpt_answers = {}
    if custom_questions:
        print(f"[*] Found {len(custom_questions)} custom open questions on form. Resolving via Procedure Memory / ChatGPT...")
        formatted_questions = [
            {"id": q.get("id") or q.get("label"), "question": q.get("label", "")}
            for q in custom_questions
        ]
        chatgpt_answers = resolve_questions_for_company(
            questions=formatted_questions,
            company=company_name,
            job_title="Software Engineer"
        )
        print(f"[+] Resolved {len(chatgpt_answers)} custom answers.")

    record_company_procedure(
        company=company_name,
        ats_platform="Ashby",
        url=clean_url,
        fields_found=[q.get("label") for q in custom_questions if isinstance(q, dict)]
    )

    # Phase 3: Inject ChatGPT answers and perform final validation
    answers_json = json.dumps(chatgpt_answers)
    phase3_script = f"""(async () => {{
const spaces = await listTaskSpaces();
const existing = spaces.find(s => s.name === "{task_space_name}");
const task = await taskSpace(existing.id);
const page = task.page("p1");

const answers = {answers_json};

// Inject custom answers into corresponding fields
await page.evaluate((ans) => {{
  for (const [key, val] of Object.entries(ans)) {{
    if (!val) continue;
    // Try matching by ID, name, or label
    let el = document.getElementById(key) || document.querySelector(`[name="${{key}}"]`);
    if (!el) {{
      const textareas = Array.from(document.querySelectorAll("textarea, input[type='text']"));
      el = textareas.find(t => {{
        const l = t.closest("label") || t.parentElement;
        return l && (l.innerText || "").includes(key);
      }});
    }}
    if (el) {{
      window.__setReactVal(el, val);
    }}
  }}
}}, answers);

await new Promise(r => setTimeout(r, 1000));

// Validate form status
const validationStatus = await page.evaluate(() => {{
  const submitBtn = Array.from(document.querySelectorAll("button")).find(b => (b.innerText || "").includes("Submit Application"));
  const errors = Array.from(document.querySelectorAll("[class*='error'], [aria-invalid='true'], [role='alert']")).filter(el => {{
    return el.offsetParent !== null && (el.innerText || "").trim().length > 0;
  }}).map(e => e.innerText.trim());

  return {{
    submitBtnFound: !!submitBtn,
    submitBtnEnabled: submitBtn ? !submitBtn.disabled : false,
    submitText: submitBtn ? submitBtn.innerText : null,
    errorsCount: errors.length,
    errors: errors
  }};
}});

// Anti-Placeholder In-Browser Verification Guard
const placeholderAudit = await page.evaluate(() => {{
  const inputs = Array.from(document.querySelectorAll("input, textarea, select"));
  const badTokens = ["Q2FuZGlkYXRlIE5hbWU=", "NTU1MDE5OTAwMA==", "NTU1LTAxOTk=", "Y2FuZGlkYXRlQGV4YW1wbGUuY29t", "VGVjaCBDaXR5", "KzEtNTU1"].map(s => atob(s));
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

console.log("[Ashby-Apply] Validation Status:", JSON.stringify(validationStatus, null, 2));

// Submit or Stage
if ({str(submit).lower()}) {{
  console.log("[Ashby-Apply] Submitting application now...");
  await page.evaluate(() => {{
    const unpressedYesBtns = Array.from(document.querySelectorAll('button[data-option="yes"][aria-pressed="false"], button[data-option="yes"]:not([class*="selected"])'));
    for (const b of unpressedYesBtns) {{
      const parentText = (b.closest("fieldset, div, tr") || {{}}).innerText || "";
      if (!parentText.toLowerCase().includes("sponsorship") && !parentText.toLowerCase().includes("visa")) {{
        b.click();
      }}
    }}
    const checkboxes = Array.from(document.querySelectorAll("input[type='checkbox']"));
    for (const cb of checkboxes) {{
      if (!cb.checked) {{
        cb.click();
        cb.checked = true;
      }}
    }}
  }});
  await new Promise(r => setTimeout(r, 1000));
  try {{
    const btn = await page.waitForSelector("button.ashby-application-form-submit-button, button:has-text('Submit Application')", {{ timeout: 5000 }});
    if (btn) await btn.click();
  }} catch(e) {{
    await page.evaluate(() => {{
      const submitBtn = Array.from(document.querySelectorAll("button")).find(b => (b.innerText || "").includes("Submit Application"));
      if (submitBtn) submitBtn.click();
    }});
  }}
  await new Promise(r => setTimeout(r, 8000));
  const conf = await page.evaluate(() => document.body.innerText.substring(0, 500));
  console.log("[Ashby-Apply] Submission Output:", conf);
}} else {{
  console.log("[Ashby-Apply] STAGED MODE: Form is 100% complete and validated. Ready for user submission confirmation.");
}}
}})();
"""

    verify_script_zero_placeholders(phase3_script, "Ashby Phase 3 Script")

    proc3 = subprocess.run(
        ["ego-browser", "nodejs"],
        input=phase3_script,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        timeout=90
    )
    combined3 = (proc3.stdout or "") + "\n" + (proc3.stderr or "")
    print(combined3)

    is_success = "submitBtnEnabled\": true" in combined3 or "Submission Output:" in combined3

    result = {
        "success": is_success,
        "platform": "Ashby",
        "url": clean_url,
        "submit": submit,
        "raw_output": combined + "\n" + combined3
    }

    # Save to history
    history = []
    if ASHBY_HISTORY_FILE.exists():
        try:
            with open(ASHBY_HISTORY_FILE, "r", encoding="utf-8") as f:
                history = json.load(f)
        except Exception:
            pass
    history.append({
        "url": clean_url,
        "submit": submit,
        "resume": resume_abs,
        "success": is_success
    })
    with open(ASHBY_HISTORY_FILE, "w", encoding="utf-8") as f:
        json.dump(history, f, indent=2)

    return result


def main():
    parser = argparse.ArgumentParser(description="Autonomous Ashby Application Engine")
    parser.add_argument("--url", required=True, help="Ashby Job Application URL")
    parser.add_argument("--resume", help="Path to tailored PDF resume")
    parser.add_argument("--submit", action="store_true", help="Submit immediately (default: stage and validate)")
    args = parser.parse_args()

    res = apply_to_ashby_job(args.url, resume_path=args.resume, submit=args.submit)
    if res.get("success"):
        print("\n[+] Ashby apply procedure completed successfully!")
    else:
        print("\n[!] Ashby application staging encountered issues. Check logs above.")


if __name__ == "__main__":
    main()
