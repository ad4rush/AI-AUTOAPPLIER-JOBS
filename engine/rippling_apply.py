#!/usr/bin/env python3
"""
Autonomous Job Application Engine for Rippling.
Applies or stages application using ego-browser on Profile 1 (Main Profile).
Attaches candidate tailored 1-page resume and fills all verified identity fields.
Includes multi-step modal handling, resume autofill parsing, custom education/relocation
resolution, EEO selections, and triple-layer anti-placeholder circuit breakers.
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
    CANDIDATE_NAME,
    CANDIDATE_EMAIL,
    CANDIDATE_PHONE,
    CANDIDATE_PHONE_PLAIN,
    CANDIDATE_LINKEDIN,
    CANDIDATE_GITHUB,
    CANDIDATE_CURRENT_COMPANY,
    assert_real_candidate_profile
)
from engine.db import update_job_status, update_text_summary

def apply_rippling(
    url: str = "https://ats.rippling.com/rippling/jobs/472ecc5e-9610-477b-bbb9-8b075c8f5a67",
    resume_path: Optional[str] = None,
    submit: bool = False,
    task_space_name: str = "rippling_auto_apply"
) -> Dict[str, Any]:
    assert_real_candidate_profile()

    name_parts = CANDIDATE_NAME.split()
    first_name = name_parts[0] if name_parts else ""
    last_name = " ".join(name_parts[1:]) if len(name_parts) > 1 else first_name

    if not resume_path:
        resume_path = str(PROJECT_ROOT / "master_resumes" / "RESUME_1_AI_ENGINEER.pdf")
    resume_abs = str(Path(resume_path).resolve())

    node_script = f"""(async () => {{
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
      task = await taskSpace("{task_space_name}_" + Date.now(), {{ profileId: "Profile 1" }});
    }}
  }}
}} else {{
  task = await taskSpace("{task_space_name}", {{ profileId: "Profile 1" }});
}}
const page = task.page("p1");

console.log("[Rippling-Apply] Navigating to: {url}");
await page.goto("{url}", {{ waitUntil: "domcontentloaded", timeout: 45000 }});
await new Promise(r => setTimeout(r, 3000));

// Step 1: If on overview page, click Apply now
if (!window.location.href.includes("step=application")) {{
  await page.evaluate(() => {{
    const btns = Array.from(document.querySelectorAll("button")).filter(b => b.innerText.trim().toLowerCase() === "apply now");
    if (btns.length > 0) btns[0].click();
  }});
  await new Promise(r => setTimeout(r, 3000));
}}

// Step 2: Upload Resume
await page.evaluate(() => {{
  const files = document.querySelectorAll("input[type='file']");
  if (files.length > 0) files[0].id = "resume-file-input";
  if (files.length > 1) files[1].id = "cover-letter-file-input";
}});
try {{
  await page.setInputFiles("#resume-file-input", "{resume_abs}");
  console.log("[Rippling-Apply] Uploaded resume PDF, waiting for autofill parse...");
  await new Promise(r => setTimeout(r, 4000));
}} catch (e) {{
  console.log("[Rippling-Apply] Resume upload note:", e.message);
}}

// Step 3: Fill Core Candidate Identity & Overwrite Parsed Fields
const filledLog = await page.evaluate(async () => {{
  function setReactVal(el, val) {{
    if (!el) return;
    el.focus();
    const proto = el.tagName === "TEXTAREA" ? window.HTMLTextAreaElement.prototype : window.HTMLInputElement.prototype;
    const setter = Object.getOwnPropertyDescriptor(proto, "value").set;
    if (setter) {{
      setter.call(el, val);
    }} else {{
      el.value = val;
    }}
    el.dispatchEvent(new Event("input", {{ bubbles: true }}));
    el.dispatchEvent(new Event("change", {{ bubbles: true }}));
    el.dispatchEvent(new Event("blur", {{ bubbles: true }}));
  }}

  const log = [];

  // Legal First Name & Last Name
  const f12 = document.getElementById("field-12");
  if (f12) {{ setReactVal(f12, "{first_name}"); log.push("First Name: {first_name}"); }}
  const f16 = document.getElementById("field-16");
  if (f16) {{ setReactVal(f16, "{last_name}"); log.push("Last Name: {last_name}"); }}

  // Email
  const f20 = document.getElementById("field-20");
  if (f20) {{ setReactVal(f20, "{CANDIDATE_EMAIL}"); log.push("Email: {CANDIDATE_EMAIL}"); }}

  // Current Company
  const f31 = document.getElementById("field-31");
  if (f31) {{ setReactVal(f31, "{CANDIDATE_CURRENT_COMPANY}"); log.push("Current Company: {CANDIDATE_CURRENT_COMPANY}"); }}

  // Phone
  const f35 = document.getElementById("field-35");
  if (f35) {{ setReactVal(f35, "{CANDIDATE_PHONE_PLAIN}"); log.push("Phone: {CANDIDATE_PHONE_PLAIN}"); }}

  // LinkedIn
  const f55 = document.getElementById("field-55");
  if (f55) {{ setReactVal(f55, "{CANDIDATE_LINKEDIN}"); log.push("LinkedIn: {CANDIDATE_LINKEDIN}"); }}

  // Website
  const f59 = document.getElementById("field-59");
  if (f59) {{ setReactVal(f59, "{CANDIDATE_GITHUB}"); log.push("Website: {CANDIDATE_GITHUB}"); }}

  // Highest level of education
  const f67 = document.getElementById("field-67");
  if (f67) {{ setReactVal(f67, "B.Tech in Computer Science & Artificial Intelligence"); log.push("Education filled"); }}

  // Year of passing
  const f71 = document.getElementById("field-71");
  if (f71) {{ setReactVal(f71, "2026"); log.push("Year of passing: 2026"); }}

  // Stream or specialisation
  const f75 = document.getElementById("field-75");
  if (f75) {{ setReactVal(f75, "Computer Science & Artificial Intelligence"); log.push("Stream: CS & AI"); }}

  return log;
}});
console.log("[Rippling-Apply] Inputs updated:", filledLog);

// Step 4: Dropdown Selections (Location, Relocation, EEO)
// Location selection: Delhi, India
await page.evaluate(() => {{
  const el = document.getElementById("field-46");
  if (el) {{
    el.focus();
    el.select();
  }}
}});
await page.keyboard.press("Backspace");
await page.keyboard.type("Delhi, India");
await new Promise(r => setTimeout(r, 800));
await page.evaluate(() => {{
  const opt0 = document.getElementById("field-46-list-option-0");
  if (opt0) opt0.click();
}});
await new Promise(r => setTimeout(r, 500));

// Bengaluru based? -> No
await page.evaluate(() => {{
  const el = document.getElementById("field-79");
  if (el) el.click();
}});
await new Promise(r => setTimeout(r, 400));
await page.evaluate(() => {{
  const opt = document.getElementById("field-79-list-option-1");
  if (opt) opt.click();
}});
await new Promise(r => setTimeout(r, 400));

// Available for in-person interview in Bengaluru within 2 weeks? -> Yes
await page.evaluate(() => {{
  const el = document.getElementById("field-85");
  if (el) el.click();
}});
await new Promise(r => setTimeout(r, 400));
await page.evaluate(() => {{
  const opt = document.getElementById("field-85-list-option-0");
  if (opt) opt.click();
}});
await new Promise(r => setTimeout(r, 400));

// Gender -> Male
await page.evaluate(() => {{
  const el = document.getElementById("field-91");
  if (el) el.click();
}});
await new Promise(r => setTimeout(r, 400));
await page.evaluate(() => {{
  const opt = document.getElementById("field-91-list-option-0");
  if (opt) opt.click();
}});
await new Promise(r => setTimeout(r, 400));

// Race -> Asian
await page.evaluate(() => {{
  const el = document.getElementById("field-97");
  if (el) {{
    el.focus();
    el.click();
  }}
}});
await new Promise(r => setTimeout(r, 400));
await page.evaluate(() => {{
  const opt = document.getElementById("field-97-list-option-1");
  if (opt) opt.click();
}});
await new Promise(r => setTimeout(r, 400));

// Hispanic/Latino -> No
await page.evaluate(() => {{
  const el = document.getElementById("field-104");
  if (el) el.click();
}});
await new Promise(r => setTimeout(r, 400));
await page.evaluate(() => {{
  const opt = document.getElementById("field-104-list-option-1");
  if (opt) opt.click();
}});
await new Promise(r => setTimeout(r, 400));

// Veteran Status -> I am not a protected veteran
await page.evaluate(() => {{
  const el = document.getElementById("field-110");
  if (el) el.click();
}});
await new Promise(r => setTimeout(r, 400));
await page.evaluate(() => {{
  const opt = document.getElementById("field-110-list-option-0");
  if (opt) opt.click();
}});
await new Promise(r => setTimeout(r, 400));

// SMS Opt-In -> true
await page.evaluate(() => {{
  const radio = document.querySelector("input[name='sms_opt_in'][value='true']");
  if (radio) {{
    radio.click();
    radio.checked = true;
    radio.dispatchEvent(new Event("change", {{ bubbles: true }}));
  }}
}});

// Step 5: Triple-Layer Anti-Placeholder Circuit Breaker Audit
const audit = await page.evaluate(() => {{
  const forbidden = ["dummy", "placeholder", "555-0199", "5550199000", "example.com", "tech city", "candidate name"];
  const inputs = Array.from(document.querySelectorAll("input, textarea, select"));
  const issues = [];
  inputs.forEach(i => {{
    const val = (i.value || "").toLowerCase();
    forbidden.forEach(tok => {{
      if (val.includes(tok)) {{
        issues.push({{ id: i.id, name: i.name, value: i.value, matched: tok }});
      }}
    }});
  }});
  return issues;
}});
if (audit.length > 0) {{
  throw new Error("Placeholder circuit breaker failed! Detected: " + JSON.stringify(audit));
}}

let submitted = false;
let confirmationText = "";
if ({str(submit).lower()}) {{
  console.log("[Rippling-Apply] Submitting application...");
  await page.evaluate(() => {{
    const btn = Array.from(document.querySelectorAll("button, input[type='submit']")).find(b => {{
      const t = (b.innerText || b.value || "").trim().toLowerCase();
      return t === "apply";
    }});
    if (btn) btn.click();
  }});
  await new Promise(r => setTimeout(r, 6000));
  const postState = await page.evaluate(() => ({{
    url: window.location.href,
    body: document.body.innerText.slice(0, 500)
  }}));
  if (postState.url.includes("step=confirmation") || postState.body.toLowerCase().includes("successfully applied")) {{
    submitted = true;
    confirmationText = postState.body;
  }}
}}

console.log(JSON.stringify({{
  success: true,
  company: "Rippling",
  url: await page.url(),
  title: await page.title(),
  submitted: submitted,
  confirmationText: confirmationText,
  fieldsFilled: filledLog
}}));
}})();
"""
    try:
        proc = subprocess.run(
            ["ego-browser", "nodejs"],
            input=node_script,
            text=True,
            capture_output=True,
            timeout=90
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
    parser = argparse.ArgumentParser(description="Apply to Rippling")
    parser.add_argument("--url", default="https://ats.rippling.com/rippling/jobs/472ecc5e-9610-477b-bbb9-8b075c8f5a67", help="Job posting URL")
    parser.add_argument("--resume", help="Tailored PDF resume path")
    parser.add_argument("--submit", action="store_true", help="Submit immediately")
    args = parser.parse_args()

    res = apply_rippling(url=args.url, resume_path=args.resume, submit=args.submit)
    print(json.dumps(res, indent=2))
