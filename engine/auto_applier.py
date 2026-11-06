import re
import json
from pathlib import Path
from typing import Dict, Any, Optional

from engine.config import (
    DATA_DIR,
    DEFAULT_PORTAL_PASSWORD,
    is_auto_apply_allowed,
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
    EGO_BROWSER_PROFILE_ID
)

PROCEDURES_DIR = DATA_DIR / "company_apply_procedures"
PROCEDURES_DIR.mkdir(parents=True, exist_ok=True)

CANDIDATE_DATA = {
    "full_name": CANDIDATE_NAME,
    "first_name": CANDIDATE_FIRST_NAME,
    "last_name": CANDIDATE_LAST_NAME,
    "email": CANDIDATE_EMAIL,
    "phone": CANDIDATE_PHONE,
    "location": CANDIDATE_LOCATION,
    "linkedin": CANDIDATE_LINKEDIN,
    "github": CANDIDATE_GITHUB,
    "current_company": CANDIDATE_CURRENT_COMPANY,
    "current_title": CANDIDATE_CURRENT_TITLE,
    "degree": "B.Tech in Computer Science & Artificial Intelligence",
    "college": "Indraprastha Institute of Information Technology Delhi (IIIT-Delhi)",
    "grad_year": "2026",
    "current_ctc": "₹20 LPA",
    "expected_ctc": "₹25+ LPA (Negotiable based on role & upside)",
    "notice_period": "30 days (negotiable/immediate)",
    "work_auth_india": "Yes",
    "us_visa_required": "Yes for US relocation; No for remote contract/independent contractor",
    "password": DEFAULT_PORTAL_PASSWORD
}

def get_company_procedure(company: str) -> Optional[Dict[str, Any]]:
    path = PROCEDURES_DIR / f"{company.lower()}.json"
    if path.exists():
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    return None

def save_company_procedure(company: str, procedure: Dict[str, Any]):
    path = PROCEDURES_DIR / f"{company.lower()}.json"
    with open(path, "w", encoding="utf-8") as f:
        json.dump(procedure, f, indent=2)

def generate_form_fill_script(
    company: str,
    job_url: str,
    resume_pdf_path: str,
    ats_type: str = "greenhouse"
) -> Dict[str, Any]:
    """
    Generates ego-browser automation script to auto-fill application forms.
    Guards against blacklisted companies (Google, Microsoft, Rubrik) to protect candidate.
    """
    if not is_auto_apply_allowed(company):
        return {
            "allowed": False,
            "reason": f"Company '{company}' is on AUTO_APPLY_BLACKLIST. Automated bot submission is disabled to prevent candidate ban. Tailored resume & referral notes ready for manual review.",
            "script": None
        }

    script = f"""
const fs = await import("node:fs/promises");
const task = await taskSpace("job_applier_workload", {{ profileId: "{EGO_BROWSER_PROFILE_ID}" }});
const p1 = task.page("p1");

console.log("[AutoApplier] Navigating to job application page: {job_url}");
await p1.goto("{job_url}");
await p1.waitForTimeout(5000);

// Candidate Data
const cand = {json.dumps(CANDIDATE_DATA)};

// Common form filler helper
async function safeFill(selectors, value) {{
  for (const s of selectors) {{
    try {{
      const el = p1.locator(s);
      if (await el.isVisible({{ timeout: 1500 }})) {{
        await el.fill(value);
        console.log(`Filled ${{s}} with ${{value}}`);
        return true;
      }}
    }} catch (e) {{}}
  }}
  return false;
}}

// 1. Fill First & Last Name
await safeFill(["input[name*='first_name']", "#first_name", "input[aria-label*='First Name']"], cand.first_name);
await safeFill(["input[name*='last_name']", "#last_name", "input[aria-label*='Last Name']"], cand.last_name);
await safeFill(["input[name*='name']:not([name*='first']):not([name*='last'])", "#name"], cand.full_name);

// 2. Fill Email & Phone
await safeFill(["input[name*='email']", "#email", "input[type='email']"], cand.email);
await safeFill(["input[name*='phone']", "#phone", "input[type='tel']"], cand.phone);

// 3. Fill LinkedIn & GitHub
await safeFill(["input[name*='linkedin']", "input[name*='urls[LinkedIn]']", "#linkedin"], cand.linkedin);
await safeFill(["input[name*='github']", "input[name*='urls[GitHub]']", "#github"], cand.github);

// 4. Fill Location / City
await safeFill(["input[name*='location']", "#location", "input[name*='candidate[location]']"], cand.location);

// 5. Fill Password if portal registration is requested
await safeFill(["input[name*='password']", "input[type='password']"], cand.password);

// 6. Resume Upload
const fileInput = p1.locator("input[type='file'][name*='resume'], input[type='file'][name*='file'], input[type='file']");
if (await fileInput.isVisible({{ timeout: 2000 }})) {{
  console.log("[AutoApplier] Uploading tailored resume: {resume_pdf_path}");
  await fileInput.setInputFiles("{resume_pdf_path}");
}}

console.log("[AutoApplier] Form fields auto-populated. Waiting for candidate confirmation before submission.");
"""
    return {
        "allowed": True,
        "company": company,
        "url": job_url,
        "resume": resume_pdf_path,
        "script": script
    }
