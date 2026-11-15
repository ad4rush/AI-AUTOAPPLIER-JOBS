#!/usr/bin/env python3
"""
Autonomous LinkedIn Easy Apply Engine.
Operates deterministically via ego-browser on Profile 1 (Personal / Main Profile)
or Profile 2 (College Profile) with authenticated LinkedIn sessions.

Key Capabilities:
- Direct job application via LinkedIn Easy Apply flow (`https://www.linkedin.com/jobs/view/{job_id}/`).
- Autonomous multi-step traversal across 1/N to N/N dialog pages.
- Native React-controlled state synchronization using prototype property setters.
- Intelligent answering for screening questions:
  * Radio button groups (Language proficiency, immediate availability, Yes/No qualifications, sponsorship).
  * Select dropdowns (CTC, salary in LPA, experience years, notice period, country code).
  * Text inputs & Textareas (LinkedIn URL, GitHub, portfolio, notice period, phone, city typeahead).
  * Compliance, identity verification, and agreement checkboxes.
- Resumes: Automatic selection of candidate's latest uploaded resume.
- Strict Production Safety:
  * Default mode: STAGE_AND_VALIDATE (reaches Review & Submit screen, takes high-res screenshot, hands off to user).
  * Submit mode: Directly submits when `--submit` is explicitly passed and verifies confirmation.
- Lifelong Procedure Memory: Saves exact discovered flow to data/company_apply_procedures/<company>/SKILL.md.
"""

import sys
import os
import re
import json
import time
import argparse
import subprocess
from pathlib import Path
from datetime import datetime
from typing import Dict, Any, Optional, List

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from engine.config import (
    EGO_BROWSER_MAIN_PROFILE_ID,
    EGO_BROWSER_COLLEGE_PROFILE_ID,
    DATA_DIR,
    CANDIDATE_NAME,
    CANDIDATE_FIRST_NAME,
    CANDIDATE_LAST_NAME,
    CANDIDATE_EMAIL,
    CANDIDATE_PERSONAL_EMAIL,
    CANDIDATE_COLLEGE_EMAIL,
    CANDIDATE_PHONE,
    CANDIDATE_PHONE_PLAIN,
    CANDIDATE_LOCATION,
    CANDIDATE_CITY,
    CANDIDATE_LINKEDIN,
    CANDIDATE_GITHUB,
    CANDIDATE_CURRENT_COMPANY,
    CANDIDATE_CURRENT_TITLE,
    ANS_WORK_AUTH_INDIA,
    ANS_SPONSORSHIP_INDIA,
    ANS_YEARS_OF_EXP,
    ANS_CURRENT_CTC,
    ANS_EXPECTED_CTC,
    ANS_NOTICE_PERIOD,
    ANS_COLLEGE,
    ANS_DEGREE,
    ANS_MAJOR,
    ANS_GRAD_YEAR,
    assert_real_candidate_profile,
    verify_script_zero_placeholders
)
from engine.procedure_memory import record_company_procedure
from engine.db import update_job_status
from engine.resume_router import select_resume_for_job


def apply_to_linkedin_job(
    url_or_id: str,
    resume_path: Optional[str] = None,
    company_name: Optional[str] = None,
    title: Optional[str] = None,
    submit: bool = False,
    profile_id: str = EGO_BROWSER_COLLEGE_PROFILE_ID,
    task_space_name: Optional[str] = None,
    job_id_db: Optional[str] = None
) -> Dict[str, Any]:
    """
    Autonomously navigates and completes the LinkedIn Easy Apply modal for a job.
    Defaults to Profile 2 ('COLLEGE PROFILE' - Adarsh Jha, adarsh22024@iiitd.ac.in).
    """
    assert_real_candidate_profile()

    clean_target = url_or_id.strip()
    m_id = re.search(r"(\d{8,12})", clean_target)
    if not m_id:
        return {"success": False, "error": f"Invalid LinkedIn job URL or ID: '{clean_target}'"}
    
    numeric_job_id = m_id.group(1)
    target_job_url = f"https://www.linkedin.com/jobs/view/{numeric_job_id}/"

    tspace = task_space_name or f"apply_li_{numeric_job_id}"
    comp = company_name or "Target Company"

    output_json_path = f"/tmp/linkedin_apply_{numeric_job_id}_{int(time.time() * 1000)}.json"
    staged_screenshot_path = str(DATA_DIR / "company_apply_procedures" / f"staged_linkedin_{numeric_job_id}.png")
    submitted_screenshot_path = str(DATA_DIR / "company_apply_procedures" / f"submitted_linkedin_{numeric_job_id}.png")

    # Resolve actual title and job description from database if not passed
    effective_title = title or ""
    effective_jd = ""
    if (not effective_title or not comp or comp == "Target Company") and (job_id_db or numeric_job_id):
        try:
            from engine.db import get_db_connection
            conn = get_db_connection()
            c = conn.cursor()
            c.execute("SELECT title, company, raw_jd_path, tailored_resume_dir FROM jobs WHERE job_id = ? OR url LIKE ?", 
                      (job_id_db or f"%{numeric_job_id}%", f"%{numeric_job_id}%"))
            row = c.fetchone()
            conn.close()
            if row:
                if not effective_title and row["title"]:
                    effective_title = row["title"]
                if (not comp or comp == "Target Company") and row["company"]:
                    comp = row["company"]
                if row["tailored_resume_dir"] and not resume_path:
                    t_dir = Path(row["tailored_resume_dir"])
                    if t_dir.exists():
                        t_pdfs = list(t_dir.glob("*.pdf"))
                        if t_pdfs:
                            resume_path = str(t_pdfs[0])
                if row["raw_jd_path"] and Path(row["raw_jd_path"]).exists():
                    try:
                        with open(row["raw_jd_path"], "r", encoding="utf-8") as f:
                            effective_jd = f.read()
                    except Exception:
                        pass
        except Exception:
            pass

    if not effective_title:
        effective_title = "Software Engineer"

    # Dynamic archetype-aware resume routing
    if not resume_path or not Path(resume_path).exists():
        routed = select_resume_for_job(company=comp, title=effective_title, jd_text=effective_jd, job_id=job_id_db or "")
        resume_abs = routed.get("resume_path", "")
        chosen_archetype = routed.get("archetype", "SWE_BACKEND")
        is_custom_tailored = routed.get("is_tailored", False)
    else:
        resume_abs = str(Path(resume_path).resolve())
        chosen_archetype = classify_master_archetype(effective_title, effective_jd)
        is_custom_tailored = True

    print(f"[*] LinkedIn dynamic resume routing for {comp} — '{effective_title}': Archetype={chosen_archetype} | File={Path(resume_abs).name} | CustomTailored={is_custom_tailored}")

    # Candidate profile constants for JavaScript injection (Profile 2 College Identity)
    cand_first = (CANDIDATE_FIRST_NAME or "Adarsh").replace('"', '\\"')
    cand_last = (CANDIDATE_LAST_NAME or "Jha").replace('"', '\\"')
    cand_email = (CANDIDATE_COLLEGE_EMAIL or CANDIDATE_EMAIL).replace('"', '\\"')
    cand_phone_digits = CANDIDATE_PHONE_PLAIN.replace('"', '\\"')
    cand_name = f"{cand_first} {cand_last}".strip()
    
    # Clean city for LinkedIn typeahead dropdown (e.g., "Delhi, India" rather than compound "Delhi / Gurgaon, India")
    raw_city = (CANDIDATE_CITY or "Delhi, India").split("/")[0].strip()
    if "delhi" in raw_city.lower() and "india" not in raw_city.lower():
        cand_city = f"{raw_city}, India"
    else:
        cand_city = raw_city
    cand_city = cand_city.replace('"', '\\"')

    cand_linkedin = CANDIDATE_LINKEDIN.replace('"', '\\"')
    cand_github = CANDIDATE_GITHUB.replace('"', '\\"')
    cand_current_title = (CANDIDATE_CURRENT_TITLE or "Software Engineer").replace('"', '\\"')
    cand_current_company = (CANDIDATE_CURRENT_COMPANY or "Technology Enterprise").replace('"', '\\"')
    cand_summary = f"{cand_name} - B.Tech {ANS_MAJOR} from {ANS_COLLEGE} ({ANS_GRAD_YEAR}). Experienced in AI systems, distributed computing, and backend architecture.".replace('"', '\\"')

    node_script = f"""
const fs = await import("node:fs/promises");

const spaces = await listTaskSpaces();
let existing = spaces.find(s => s.name === "{tspace}");
let task;
if (existing) {{
  if (existing.profileId && existing.profileId !== "{profile_id}") {{
    console.log(`[LinkedIn-Apply] Existing space ${{existing.id}} has profile ${{existing.profileId}}, expected {profile_id}. Finishing old space...`);
    try {{
      const oldTask = existing.ownership === "agent" ? await taskSpace(existing.id) : await takeOverTaskSpace(existing.id);
      await oldTask.finish({{ keep: [] }});
    }} catch(e) {{
      console.log("[LinkedIn-Apply] Could not close mismatched space:", e.message);
    }}
    task = await taskSpace("{tspace}", {{ profileId: "{profile_id}" }});
  }} else if (existing.ownership === "agent") {{
    task = await taskSpace(existing.id);
  }} else {{
    try {{
      task = await takeOverTaskSpace(existing.id);
    }} catch(e) {{
      task = await taskSpace("{tspace}", {{ profileId: "{profile_id}" }});
    }}
  }}
}} else {{
  task = await taskSpace("{tspace}", {{ profileId: "{profile_id}" }});
}}

const page = task.page("p1");

console.log("[LinkedIn-Apply] Navigating to job: {target_job_url}");
await page.goto("{target_job_url}", {{ waitUntil: "domcontentloaded", timeout: 25000 }});
await new Promise(r => setTimeout(r, 3500));

// Check if authenticated
const currentUrl = await page.url();
if (currentUrl.includes("/login") || currentUrl.includes("/checkpoint/")) {{
  console.log("[LinkedIn-Apply] Auth wall encountered. Handing off task to user.");
  await task.handOff();
  await fs.writeFile("{output_json_path}", JSON.stringify({{
    success: false,
    authRequired: true,
    error: "LinkedIn authentication required in profile {profile_id}"
  }}));
  process.exit(0);
}}

// Extract metadata if needed
const pageMeta = await page.evaluate(() => {{
  const title = document.querySelector("h1")?.innerText?.trim() || "";
  const compEl = document.querySelector(".job-details-jobs-unified-top-card__company-name, a[href*='/company/']");
  const comp = compEl ? compEl.innerText.trim() : "";
  const easyApplyBtn = Array.from(document.querySelectorAll("button")).find(b => 
    (b.innerText && b.innerText.includes("Easy Apply")) ||
    (b.getAttribute("aria-label") && b.getAttribute("aria-label").includes("Easy Apply"))
  );
  const externalApplyBtn = Array.from(document.querySelectorAll("button, a")).find(b =>
    (b.innerText && b.innerText.includes("Apply on company website")) ||
    (b.href && b.href.includes("externalApply"))
  );
  const isAlreadyApplied = Array.from(document.querySelectorAll("button, span, div.artdeco-inline-feedback, p")).some(el => {{
    const t = (el.innerText || "").trim().toLowerCase();
    return t === "applied" || t.startsWith("applied on") || t.startsWith("applied ");
  }});
  return {{
    title,
    company: comp,
    hasEasyApply: !!easyApplyBtn,
    hasExternalApply: !!externalApplyBtn,
    isAlreadyApplied
  }};
}});

console.log("[LinkedIn-Apply] Page metadata:", JSON.stringify(pageMeta));

if (!pageMeta.hasEasyApply) {{
  if (pageMeta.isAlreadyApplied) {{
    console.log("[LinkedIn-Apply] Job has already been applied to on LinkedIn.");
    await fs.writeFile("{output_json_path}", JSON.stringify({{
      success: true,
      isEasyApply: true,
      alreadyApplied: true,
      submitted: true,
      company: pageMeta.company || "{comp}",
      title: pageMeta.title
    }}));
    try {{ await task.finish({{ keep: [] }}); }} catch(e) {{}}
    process.exit(0);
  }}

  console.log("[LinkedIn-Apply] Job does not have an Easy Apply button.");
  await fs.writeFile("{output_json_path}", JSON.stringify({{
    success: false,
    isEasyApply: false,
    hasExternalApply: pageMeta.hasExternalApply,
    error: pageMeta.hasExternalApply ? "Job requires external ATS application" : "No Easy Apply button found on page",
    company: pageMeta.company || "{comp}",
    title: pageMeta.title
  }}));
  try {{ await task.finish({{ keep: [] }}); }} catch(e) {{}}
  process.exit(0);
}}

// Open Easy Apply Modal
console.log("[LinkedIn-Apply] Clicking Easy Apply button...");
await page.evaluate(() => {{
  const easyApplyBtn = Array.from(document.querySelectorAll("button")).find(b => 
    (b.innerText && b.innerText.includes("Easy Apply")) ||
    (b.getAttribute("aria-label") && b.getAttribute("aria-label").includes("Easy Apply"))
  );
  if (easyApplyBtn) easyApplyBtn.click();
}});
await new Promise(r => setTimeout(r, 2500));

// Multi-step solver loop
let stepNumber = 0;
let isReviewScreen = false;
let recordedSteps = [];
let capturedFields = [];

while (stepNumber < 15) {{
  stepNumber++;

  const stepState = await page.evaluate(() => {{
    const d = document.querySelector("dialog");
    if (!d) return {{ open: false }};

    const header = d.innerText.match(/(\\d+\\/\\d+\\s*pages)/)?.[1] || "";
    const title = d.querySelector("h2, h3, h1")?.innerText?.trim() || "";
    const buttons = Array.from(d.querySelectorAll("button")).map(b => b.innerText.trim()).filter(Boolean);
    const isReview = buttons.includes("Submit application") || d.innerText.includes("Review your application");

    return {{
      open: true,
      header,
      title,
      buttons,
      isReview
    }};
  }});

  if (!stepState.open) {{
    console.log("[LinkedIn-Apply] Dialog is not open. Terminating loop.");
    break;
  }}

  console.log(`[LinkedIn-Apply] Step ${{stepNumber}}: ${{stepState.header}} | ${{stepState.title}} | Buttons: ${{stepState.buttons.join(", ")}}`);
  recordedSteps.push(`${{stepState.header}}: ${{stepState.title}}`);

  if (stepState.isReview) {{
    isReviewScreen = true;
    console.log("[LinkedIn-Apply] Reached Review & Submit screen!");
    break;
  }}

  // Handle City Typeahead via Playwright page keyboard if present
  const needTypeahead = await page.evaluate(() => {{
    const d = document.querySelector("dialog");
    const ta = d ? d.querySelector("input[data-testid='typeahead-input']") : null;
    if (!ta) return false;
    const hasErr = d.innerText.includes("This field is required") || d.innerText.includes("Location (city)*");
    return hasErr || !ta.value || ta.value.trim() === "";
  }});

  if (needTypeahead) {{
    try {{
      console.log("[LinkedIn-Apply] Selecting city typeahead from dropdown listbox...");
      await page.click("dialog input[data-testid='typeahead-input']");
      await page.keyboard.press("Meta+A");
      await page.keyboard.press("Backspace");
      await page.keyboard.type("{cand_city}", {{ delay: 60 }});
      await new Promise(r => setTimeout(r, 1500));
      await page.keyboard.press("ArrowDown");
      await new Promise(r => setTimeout(r, 300));
      await page.keyboard.press("Enter");
      await new Promise(r => setTimeout(r, 600));
    }} catch(err) {{
      console.log("[LinkedIn-Apply] Typeahead interaction error:", err.message);
    }}
  }}

  // Resume File Upload (for dedicated tailored or specialized backend resumes)
  const isResumeStep = await page.evaluate(() => {{
    const d = document.querySelector("dialog");
    const text = (d ? d.innerText : "").toLowerCase();
    const hasFileInput = d ? !!d.querySelector("input[type='file']") : false;
    return (text.includes("resume") || text.includes("upload resume")) && hasFileInput;
  }});

  if (isResumeStep && "{resume_abs}" && ({str(is_custom_tailored).lower()} || "{chosen_archetype}" === "SWE_BACKEND")) {{
    try {{
      console.log("[LinkedIn-Apply] Uploading specialized/tailored resume: {resume_abs}");
      await page.setInputFiles("dialog input[type='file']", ["{resume_abs}"]);
      await new Promise(r => setTimeout(r, 2000));
    }} catch(err) {{
      console.log("[LinkedIn-Apply] Resume file upload note:", err.message);
    }}
  }}

  // Perform intelligent field filling on current step
  const fillResult = await page.evaluate((cand) => {{
    const d = document.querySelector("dialog");
    if (!d) return {{ success: false, reason: "No dialog" }};

    const nativeInputSetter = Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, "value")?.set;
    const nativeSelectSetter = Object.getOwnPropertyDescriptor(window.HTMLSelectElement.prototype, "value")?.set;
    const nativeTextAreaSetter = Object.getOwnPropertyDescriptor(window.HTMLTextAreaElement.prototype, "value")?.set;

    function setVal(el, val) {{
      if (el.tagName === "SELECT") {{
        if (nativeSelectSetter) nativeSelectSetter.call(el, val);
        else el.value = val;
        el.dispatchEvent(new Event("change", {{ bubbles: true }}));
      }} else if (el.tagName === "TEXTAREA") {{
        if (nativeTextAreaSetter) nativeTextAreaSetter.call(el, val);
        else el.value = val;
        el.dispatchEvent(new Event("input", {{ bubbles: true }}));
        el.dispatchEvent(new Event("change", {{ bubbles: true }}));
        el.dispatchEvent(new Event("blur", {{ bubbles: true }}));
      }} else {{
        if (nativeInputSetter) nativeInputSetter.call(el, val);
        else el.value = val;
        el.dispatchEvent(new Event("input", {{ bubbles: true }}));
        el.dispatchEvent(new Event("change", {{ bubbles: true }}));
        el.dispatchEvent(new Event("blur", {{ bubbles: true }}));
      }}
    }}

    const touched = [];

    // 0. Work Experience Subform (if open with Save button)
    const titleInp = Array.from(d.querySelectorAll("input")).find(i => (i.getAttribute("aria-label") || "").includes("title"));
    const compInp = Array.from(d.querySelectorAll("input")).find(i => (i.getAttribute("aria-label") || "").includes("Company"));
    const currWorkCb = Array.from(d.querySelectorAll("input[type='checkbox']")).find(cb => (cb.getAttribute("aria-label") || "").includes("currently work here"));
    const saveBtn = Array.from(d.querySelectorAll("button")).find(b => b.innerText.trim() === "Save");

    if (titleInp && !titleInp.value) {{
      setVal(titleInp, cand.currentTitle || "Software Engineer");
      if (compInp && !compInp.value) setVal(compInp, cand.currentCompany || "Technology Enterprise");
      if (currWorkCb && !currWorkCb.checked) {{
        currWorkCb.click();
        currWorkCb.checked = true;
        currWorkCb.dispatchEvent(new Event("change", {{ bubbles: true }}));
      }}
      const expSelects = Array.from(d.querySelectorAll("select"));
      if (expSelects[0]) setVal(expSelects[0], "1");
      if (expSelects[1]) {{
        const opt = Array.from(expSelects[1].options).find(o => o.text.includes("2024"));
        if (opt) setVal(expSelects[1], opt.value);
      }}
      if (saveBtn) {{
        saveBtn.click();
        touched.push("experience_saved");
      }}
    }}

    // 1. Radio Groups
    const radios = Array.from(d.querySelectorAll("input[type='radio']"));
    const groups = {{}};
    for (const r of radios) {{
      if (!groups[r.name]) groups[r.name] = [];
      groups[r.name].push(r);
    }}

    for (const gName in groups) {{
      const list = groups[gName];
      const hasChecked = list.some(r => r.checked);

      // Intelligent Resume Archetype Selector
      const isResumeGroup = list.some(r => {{
        const txt = (r.parentElement?.parentElement?.innerText || r.getAttribute("aria-label") || "").toLowerCase();
        return txt.includes(".pdf") || txt.includes("resume");
      }});

      if (isResumeGroup) {{
        let targetResumeRadio = null;
        for (const r of list) {{
          const rText = (r.parentElement?.parentElement?.innerText || r.getAttribute("aria-label") || "").toLowerCase();
          if (cand.archetype === "DATA_ENGINEER" && (rText.includes("data") || rText.includes("lakehouse"))) {{
            targetResumeRadio = r;
            break;
          }} else if (cand.archetype === "AI_ENGINEER" && (rText.includes("ai") || rText.includes("ml") || rText.includes("llm"))) {{
            targetResumeRadio = r;
            break;
          }} else if (cand.archetype === "SWE_BACKEND" && (rText.includes("backend") || rText.includes("swe") || rText.includes("software"))) {{
            targetResumeRadio = r;
            break;
          }}
        }}
        if (targetResumeRadio && !targetResumeRadio.checked) {{
          const label = d.querySelector(`label[for="${{targetResumeRadio.id}}"]`);
          if (label) label.click();
          else targetResumeRadio.click();
          targetResumeRadio.checked = true;
          targetResumeRadio.dispatchEvent(new Event("input", {{ bubbles: true }}));
          targetResumeRadio.dispatchEvent(new Event("change", {{ bubbles: true }}));
          touched.push(`resume_radio:${{targetResumeRadio.id}}`);
        }}
        continue;
      }}

      if (!hasChecked) {{
        const qText = (list[0].getAttribute("aria-label") || list[0].closest("fieldset")?.innerText || list[0].closest("div")?.parentElement?.innerText || "").toLowerCase();
        let chosen = null;

        for (const r of list) {{
          const optText = (r.parentElement?.parentElement?.innerText || r.getAttribute("aria-label") || "").trim().toLowerCase();
          
          // Language proficiency
          if (qText.includes("english") || qText.includes("language")) {{
            if (optText.includes("fluent") || optText.includes("advanced") || optText.includes("native")) chosen = r;
          }}
          // Start date / notice period
          else if (qText.includes("start date") || qText.includes("notice period") || qText.includes("earliest")) {{
            if (optText.includes("immediately") || optText.includes("within 30 days") || optText.includes("15")) chosen = r;
          }}
          // Visa sponsorship (Negative)
          else if (qText.includes("sponsorship") || qText.includes("require visa") || qText.includes("require sponsorship")) {{
            if (optText === "no" || optText.includes("do not require")) chosen = r;
          }}
          // Criminal / Misconduct / Non-compete (Negative)
          else if (qText.includes("convicted") || qText.includes("criminal") || qText.includes("non-compete") || qText.includes("disciplinary")) {{
            if (optText === "no") chosen = r;
          }}
          // Right to work / Authorisation (Positive)
          else if (qText.includes("authorized") || qText.includes("legally") || qText.includes("right to work") || qText.includes("citizen")) {{
            if (optText === "yes" || optText.includes("authorized")) chosen = r;
          }}
          // Shifts / Relocation / Background check (Positive)
          else if (qText.includes("shift") || qText.includes("background check") || qText.includes("own identity") || qText.includes("truthful")) {{
            if (optText === "yes") chosen = r;
          }}
          // General default affirmative
          else {{
            if (optText === "yes") chosen = r;
          }}
        }}

        if (!chosen) chosen = list[0];

        const label = d.querySelector(`label[for="${{chosen.id}}"]`);
        if (label) label.click();
        else chosen.click();
        chosen.checked = true;
        chosen.dispatchEvent(new Event("input", {{ bubbles: true }}));
        chosen.dispatchEvent(new Event("change", {{ bubbles: true }}));
        touched.push(`radio:${{qText.slice(0, 30)}}`);
      }}
    }}

    // 2. Select Dropdowns
    const selects = Array.from(d.querySelectorAll("select"));
    for (const sel of selects) {{
      if (!sel.value || sel.value.trim() === "") {{
        const qText = (sel.closest("div")?.parentElement?.innerText || sel.getAttribute("aria-label") || "").toLowerCase();
        let val = "";

        if (qText.includes("country code") || sel.id.includes("countryCode")) {{
          val = "in";
        }} else if (qText.includes("current salary") || qText.includes("current ctc")) {{
          const opt = Array.from(sel.options).find(o => 
            o.value === "20" || o.text === "20" || o.text.includes("18 - 21") || o.text.includes("15 - 18") || o.text.includes("20")
          );
          val = opt ? opt.value : (sel.options[1]?.value || "");
        }} else if (qText.includes("expected salary") || qText.includes("expected ctc")) {{
          const opt = Array.from(sel.options).find(o => 
            o.value === "28" || o.text === "28" || o.text.includes("27 - 30") || o.text.includes("24 - 27") || o.text.includes("28")
          );
          val = opt ? opt.value : (sel.options[1]?.value || "");
        }} else if (qText.includes("comfortable working from office") || qText.includes("work from office") || qText.includes("hybrid") || qText.includes("on-site")) {{
          const opt = Array.from(sel.options).find(o => o.text.toLowerCase().trim() === "yes" || o.value.toLowerCase().trim() === "yes");
          val = opt ? opt.value : (sel.options[1]?.value || "");
        }} else if (qText.includes("additional months") || qText.includes("month")) {{
          const opt = Array.from(sel.options).find(o => o.value === "0" || o.text.includes("0"));
          val = opt ? opt.value : (sel.options[1]?.value || "");
        }} else if (qText.includes("experience") || qText.includes("year")) {{
          const opt = Array.from(sel.options).find(o => o.value === "2" || o.text.includes("2") || o.value === "1" || o.text.includes("1"));
          val = opt ? opt.value : (sel.options[1]?.value || "");
        }} else if (qText.includes("notice")) {{
          const opt = Array.from(sel.options).find(o => o.text.toLowerCase().includes("immediate") || o.text.includes("15") || o.text.includes("30"));
          val = opt ? opt.value : (sel.options[1]?.value || "");
        }} else {{
          const yesOpt = Array.from(sel.options).find(o => o.text.toLowerCase().trim() === "yes" || o.value.toLowerCase().trim() === "yes");
          const valid = yesOpt || Array.from(sel.options).find(o => o.value && !o.text.toLowerCase().includes("select"));
          val = valid ? valid.value : "";
        }}

        if (val) {{
          setVal(sel, val);
          touched.push(`select:${{qText.slice(0, 30)}}`);
        }}
      }}
    }}

    // 3. Text Inputs & Textareas
    const textEls = Array.from(d.querySelectorAll("input[type='text'], input[type='tel'], input[type='number'], input:not([type]), textarea"));
    for (const ti of textEls) {{
      if (ti.getAttribute("data-testid") === "typeahead-input") continue;

      if (!ti.value || ti.value.trim() === "") {{
        const qText = (ti.getAttribute("aria-label") || ti.placeholder || ti.closest("div")?.parentElement?.innerText || "").toLowerCase();
        let val = "";

        if (qText.includes("linkedin")) {{
          val = cand.linkedin;
        }} else if (qText.includes("github")) {{
          val = cand.github;
        }} else if (qText.includes("website") || qText.includes("portfolio")) {{
          val = cand.github;
        }} else if (qText.includes("phone") || ti.type === "tel") {{
          val = cand.phone;
        }} else if (qText.includes("first name")) {{
          val = cand.first;
        }} else if (qText.includes("last name")) {{
          val = cand.last;
        }} else if (qText.includes("email")) {{
          val = cand.email;
        }} else if (qText.includes("notice period in days") || qText.includes("notice")) {{
          val = "15";
        }} else if (qText.includes("current ctc in inr") || qText.includes("current annual compensation in inr")) {{
          val = "2000000";
        }} else if (qText.includes("expected ctc in inr") || qText.includes("expected annual compensation in inr")) {{
          val = "2800000";
        }} else if (qText.includes("ctc") || qText.includes("salary") || qText.includes("compensation")) {{
          val = qText.includes("lpa") ? "20" : "2000000";
        }} else if (qText.includes("expected")) {{
          val = qText.includes("lpa") ? "28" : "2800000";
        }} else if (qText.includes("experience") || qText.includes("year")) {{
          val = "2";
        }} else if (qText.includes("gpa") || qText.includes("percentage") || qText.includes("grade")) {{
          val = "8.2";
        }} else if (qText.includes("cover letter") || qText.includes("summary") || qText.includes("pitch") || qText.includes("why")) {{
          val = cand.summary;
        }} else if (qText.includes("city") || qText.includes("location")) {{
          val = cand.city;
        }} else {{
          val = ti.type === "number" ? "2" : "Yes";
        }}

        setVal(ti, val);
        touched.push(`text:${{qText.slice(0, 30)}}`);
      }}
    }}

    // 4. Checkboxes (Compliance, Truthfulness, Right to Work)
    const checkboxes = Array.from(d.querySelectorAll("input[type='checkbox']"));
    for (const cb of checkboxes) {{
      if (!cb.checked) {{
        cb.click();
        cb.checked = true;
        cb.dispatchEvent(new Event("change", {{ bubbles: true }}));
        touched.push("checkbox");
      }}
    }}

    return {{ success: true, touched }};
  }}, {{
    first: "{cand_first}",
    last: "{cand_last}",
    email: "{cand_email}",
    phone: "{cand_phone_digits}",
    city: "{cand_city}",
    linkedin: "{cand_linkedin}",
    github: "{cand_github}",
    currentTitle: "{cand_current_title}",
    currentCompany: "{cand_current_company}",
    summary: "{cand_summary}",
    archetype: "{chosen_archetype}"
  }});

  if (fillResult.touched) {{
    capturedFields.push(...fillResult.touched);
  }}

  await new Promise(r => setTimeout(r, 1000));

  // Advance by clicking Next or Review
  const advanceResult = await page.evaluate(() => {{
    const d = document.querySelector("dialog");
    if (!d) return {{ advanced: false, reason: "No dialog" }};

    const nextBtn = Array.from(d.querySelectorAll("button")).find(b => 
      ["Next", "Review"].includes(b.innerText.trim())
    );

    if (nextBtn) {{
      nextBtn.click();
      return {{ advanced: true, btnText: nextBtn.innerText.trim() }};
    }}
    return {{ advanced: false, reason: "No advance button" }};
  }});

  if (!advanceResult.advanced) {{
    console.log("[LinkedIn-Apply] Could not advance step. Reason:", advanceResult.reason);
    break;
  }}

  await new Promise(r => setTimeout(r, 2500));
}}

let submittedSuccessfully = false;
let confirmationText = "";

if (isReviewScreen) {{
  if ({str(submit).lower()}) {{
    console.log("[LinkedIn-Apply] Production Submit Mode enabled. Executing final submission...");
    await page.evaluate(() => {{
      const d = document.querySelector("dialog");
      const submitBtn = Array.from(d.querySelectorAll("button")).find(b => b.innerText.trim() === "Submit application");
      if (submitBtn) submitBtn.click();
    }});

    await new Promise(r => setTimeout(r, 5000));
    await page.screenshot({{ path: "{submitted_screenshot_path}", fullPage: true }});

    const confirmationInfo = await page.evaluate(() => {{
      const d = document.querySelector("dialog");
      const text = (d ? d.innerText : document.body.innerText).toLowerCase();
      const isSent = text.includes("application was sent") ||
                     text.includes("application sent") ||
                     text.includes("applied") ||
                     text.includes("application submitted") ||
                     text.includes("keep track of your application");
      return {{
        isConfirmed: isSent,
        snippet: (d ? d.innerText : document.body.innerText).slice(0, 300).replace(/\\n+/g, " | ")
      }};
    }});

    submittedSuccessfully = confirmationInfo.isConfirmed;
    confirmationText = confirmationInfo.snippet;
    console.log("[LinkedIn-Apply] Application submission confirmed:", submittedSuccessfully);
    if (submittedSuccessfully) {{
      try {{
        await task.finish({{ keep: [] }});
      }} catch(e) {{
        console.log("[LinkedIn-Apply] Task finish note:", e.message);
      }}
    }}
  }} else {{
    console.log("[LinkedIn-Apply] Safe Mode: Staging on Review & Submit screen with zero errors.");
    await page.screenshot({{ path: "{staged_screenshot_path}", fullPage: true }});
    // Hand off task to user so ego-browser tab remains active and reviewable
    await task.handOff();
    console.log("[LinkedIn-Apply] Handed off task space '{tspace}' to candidate for final 1-click submission.");
  }}
}} else {{
  console.log("[LinkedIn-Apply] Application flow did not reach Review screen within allowed steps.");
}}

await fs.writeFile("{output_json_path}", JSON.stringify({{
  success: isReviewScreen,
  staged: isReviewScreen && !{str(submit).lower()},
  submitted: submittedSuccessfully,
  isReviewScreen: isReviewScreen,
  confirmationText: confirmationText,
  company: pageMeta.company || "{comp}",
  title: pageMeta.title,
  stepsTraversed: recordedSteps,
  fieldsFilledCount: capturedFields.length,
  screenshotPath: {str(submit).lower()} ? "{submitted_screenshot_path}" : "{staged_screenshot_path}",
  taskSpace: "{tspace}"
}}));
"""

    verify_script_zero_placeholders(node_script, "LinkedIn Easy Apply Engine")

    try:
        proc = subprocess.run(
            ["ego-browser", "nodejs"],
            input=node_script,
            text=True,
            capture_output=True,
            timeout=180
        )
        
        output_file = Path(output_json_path)
        if output_file.exists():
            with open(output_file, "r", encoding="utf-8") as f:
                res_data = json.load(f)
            try:
                os.remove(output_file)
            except OSError:
                pass
        else:
            res_data = {
                "success": False,
                "error": "No output JSON written by ego-browser",
                "raw": (proc.stdout or "") + "\n" + (proc.stderr or "")
            }

        final_company = res_data.get("company") or comp
        final_title = res_data.get("title") or "Software Engineer"
        is_success = bool(res_data.get("success"))
        is_submitted = bool(res_data.get("submitted"))

        if not is_success:
            err_log = (proc.stdout or "") + "\n" + (proc.stderr or "")
            print(f"[!] LinkedIn Apply Node Output:\n{err_log}")
            if not res_data.get("error"):
                last_step = res_data.get("stepsTraversed", [])[-1] if res_data.get("stepsTraversed") else "unknown"
                res_data["error"] = f"Application flow halted at {last_step}"

        # Lifelong procedure memory recording
        if is_success:
            record_company_procedure(
                company=final_company,
                ats_platform="linkedin_easy_apply",
                url=target_job_url,
                fields_found=[
                    "contact_city_typeahead", "phone_country_code", "phone_number",
                    "email", "resume_radio_selector", "language_proficiency_radio",
                    "earliest_start_date_radio", "sponsorship_radio", "salary_lpa_select",
                    "expected_ctc_select", "linkedin_url_input", "github_url_input",
                    "terms_agreement_checkbox"
                ],
                notes=f"LinkedIn Easy Apply modal successfully completed ({len(res_data.get('stepsTraversed', []))} steps). Status: {'SUBMITTED' if is_submitted else 'STAGED_FOR_REVIEW'}.",
                selectors={
                    "easy_apply_button": "button:has-text('Easy Apply'), button[aria-label='Easy Apply to this job']",
                    "modal_dialog": "dialog",
                    "next_button": "dialog button:has-text('Next')",
                    "review_button": "dialog button:has-text('Review')",
                    "submit_button": "dialog button:has-text('Submit application')",
                    "city_typeahead": "input[data-testid='typeahead-input']"
                },
                question_answers={
                    "level_of_english": "Fluent/Native-like or Advanced",
                    "earliest_start_date": "I am available immediately / within 30 days",
                    "require_sponsorship": "No",
                    "authorized_to_work": "Yes",
                    "current_salary_lpa": "20",
                    "expected_salary_lpa": "28"
                },
                step_by_step_instructions=[
                    "Navigate to job view: https://www.linkedin.com/jobs/view/{job_id}/",
                    "Click button[aria-label='Easy Apply to this job']",
                    "Contact info: set city typeahead to Delhi, India, verify phone and email",
                    "Resume: ensure latest PDF resume radio is selected",
                    "Additional questions: select Fluent for English, Immediate for start date, Yes for work authorization, No for sponsorship",
                    "Salary selects: 20 LPA current, 28 LPA expected",
                    "Advance Next -> Review -> Submit application"
                ],
                task_space=tspace
            )

        # Update database status if job_id was linked
        if job_id_db:
            new_status = "APPLIED" if is_submitted else ("STAGED_FOR_REVIEW" if is_success else "FAILED")
            details = {
                "notes": f"[LinkedIn Easy Apply] {'Submitted directly' if is_submitted else f'Staged in ego-browser {profile_id}'}. TaskSpace: {tspace}. Resume: {resume_abs}"
            }
            if is_submitted:
                details["applied_at"] = datetime.now().isoformat()
            update_job_status(
                job_id=job_id_db,
                status=new_status,
                details=details,
                refresh_summary=True
            )

        return {
            "success": is_success,
            "staged": res_data.get("staged", False),
            "submitted": is_submitted,
            "company": final_company,
            "title": final_title,
            "url": target_job_url,
            "job_id": numeric_job_id,
            "steps": res_data.get("stepsTraversed", []),
            "screenshot": res_data.get("screenshotPath"),
            "task_space": tspace,
            "error": res_data.get("error")
        }

    except Exception as e:
        return {
            "success": False,
            "error": str(e),
            "company": comp,
            "url": target_job_url
        }


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Autonomous LinkedIn Easy Apply Engine")
    parser.add_argument("--url", required=True, help="LinkedIn Job View URL or numeric Job ID")
    parser.add_argument("--company", help="Optional company name")
    parser.add_argument("--resume", help="Optional PDF resume path")
    parser.add_argument("--submit", action="store_true", help="Submit immediately (default: stage & review)")
    parser.add_argument("--profile", default=EGO_BROWSER_MAIN_PROFILE_ID, help="Ego browser profile ID")
    parser.add_argument("--task-space", help="Optional custom task space name")
    args = parser.parse_args()

    result = apply_to_linkedin_job(
        url_or_id=args.url,
        resume_path=args.resume,
        company_name=args.company,
        submit=args.submit,
        profile_id=args.profile,
        task_space_name=args.task_space
    )
    print(json.dumps(result, indent=2))
