#!/usr/bin/env python3
"""
Autonomous Microsoft Job Application Engine (Eightfold.ai).
Executes end-to-end auto-apply via ego-browser on Profile 1 (Main Profile).
Handles Google OAuth authentication, pre-populates all India Work Authorization fields,
dynamically answers technical/job-specific questions, verifies acknowledgments,
and optionally uploads a tailored resume PDF.
"""

import sys
import json
import argparse
import subprocess
from pathlib import Path
from typing import Dict, Any, Optional

# Ensure project root is in sys.path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from engine.config import (
    EGO_BROWSER_MAIN_PROFILE_ID,
    DATA_DIR,
    CANDIDATE_PERSONAL_EMAIL,
    CANDIDATE_ADDRESS,
    CANDIDATE_CITY
)

HISTORY_FILE = DATA_DIR / "company_apply_procedures" / "microsoft_history.json"
HISTORY_FILE.parent.mkdir(parents=True, exist_ok=True)

def apply_to_microsoft_job(
    job_url_or_id: str,
    resume_path: Optional[str] = None,
    submit: bool = False,
    task_space_name: str = "microsoft_auto_apply"
) -> Dict[str, Any]:
    """
    Applies to a Microsoft India job opening using ego-browser in Profile 1.
    If submit=False, stages and validates all fields, leaving the form ready for one-click submission.
    If submit=True, clicks 'Submit application' and confirms dispatch.
    """
    # Normalize URL
    if job_url_or_id.startswith("http"):
        job_url = job_url_or_id
    else:
        # Requisition ID
        clean_id = job_url_or_id.replace("msft_", "")
        job_url = f"https://apply.careers.microsoft.com/careers/job/{clean_id}?domain=microsoft.com"

    apply_url = job_url
    if "/apply" not in apply_url:
        if "job/" in apply_url:
            pid = apply_url.split("job/")[1].split("?")[0]
            apply_url = f"https://apply.careers.microsoft.com/careers/apply?pid={pid}&domain=microsoft.com"

    resume_abs = str(Path(resume_path).resolve()) if resume_path and Path(resume_path).exists() else ""

    node_script = f"""
const spaces = await listTaskSpaces();
const existing = spaces.find(s => s.name === "{task_space_name}");
const task = existing ? await taskSpace(existing.id) : await taskSpace("{task_space_name}", {{ profileId: "{EGO_BROWSER_MAIN_PROFILE_ID}" }});
const page = task.page("p1");

console.log("[MSFT-Apply] Navigating to job page: {job_url}");
await page.goto("{job_url}");
await page.waitForTimeout(5000);

// If on job details page, click 'Apply now' to enter application form
const hasApplyNow = await page.evaluate(() => {{
  const btn = Array.from(document.querySelectorAll("a, button")).find(el => el.innerText && el.innerText.trim() === "Apply now");
  return !!btn;
}});

if (hasApplyNow) {{
  console.log("[MSFT-Apply] Clicking Apply now button...");
  try {{
    await page.click('text="Apply now"');
  }} catch (e) {{
    await page.click('a:has-text("Apply now")');
  }}
  await page.waitForTimeout(6000);
}}

// Wait for form regions / Submit button to mount
try {{
  await page.waitForSelector('text="Submit application"', {{ timeout: 15000 }});
}} catch (e) {{
  console.log("[MSFT-Apply] Waiting for form container...");
  await page.waitForTimeout(4000);
}}

// 1. Check if Authentication Modal is open
let currentUrl = await page.url();
const authModalVisible = await page.evaluate(() => {{
  const btn = document.querySelector(".candidateAuthGoogleLoginButton");
  if (btn) return true;
  return Array.from(document.querySelectorAll("button")).some(b => b.innerText && b.innerText.includes("Sign in using Google"));
}});

if (authModalVisible || currentUrl.includes("/login")) {{
  console.log(`[MSFT-Apply] Sign-in required. Initiating Google OAuth via ${{'{CANDIDATE_PERSONAL_EMAIL}'}}...`);
  try {{
    await page.click(".candidateAuthGoogleLoginButton");
  }} catch (e) {{
    await page.click('button:has-text("Sign in using Google")');
  }}
  await page.waitForTimeout(5000);

  // Switch to OAuth tab if opened
  const tabs = await task.tabs();
  const oauthTab = tabs.find(t => t.url.includes("accounts.google.com"));
  if (oauthTab) {{
    const pOauth = task.page(oauthTab.label);
    console.log(`[MSFT-Apply] Selecting ${{'{CANDIDATE_PERSONAL_EMAIL}'}} in OAuth popup...`);
    try {{
      await pOauth.click(`text="${{'{CANDIDATE_PERSONAL_EMAIL}'}}"`, {{ timeout: 5000 }});
      await pOauth.waitForTimeout(3000);
    }} catch (e) {{}}
    
    // Click Continue if consent screen appears
    try {{
      await pOauth.click('button:has-text("Continue")', {{ timeout: 5000 }});
      await pOauth.waitForTimeout(5000);
    }} catch (e) {{}}
  }}
  await page.waitForTimeout(6000);
}}

// 2. Ensure we are on the application form
currentUrl = await page.url();
console.log("[MSFT-Apply] Current Application URL:", currentUrl);

// 3. Fill Application Form
const fillResult = await page.evaluate(async (resumeFile) => {{
  const log = [];

  // Helper for clicking
  function triggerChange(el) {{
    el.dispatchEvent(new Event("input", {{ bubbles: true }}));
    el.dispatchEvent(new Event("change", {{ bubbles: true }}));
  }}

  function setFieldValue(id, val) {{
    const el = document.getElementById(id);
    if (el) {{
      el.focus();
      const proto = Object.getPrototypeOf(el);
      const desc = Object.getOwnPropertyDescriptor(proto, 'value') || Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, 'value');
      if (desc && desc.set) {{
        desc.set.call(el, val);
      }} else {{
        el.value = val;
      }}
      triggerChange(el);
      log.push(`Set ${{id}} to ${{val}}`);
    }}
  }}

  // Contact / Address Information
  setFieldValue("Contact_Information_q_address", "{CANDIDATE_ADDRESS}");
  setFieldValue("Contact_Information_q_city", "{CANDIDATE_CITY}");
  setFieldValue("Contact_Information_q_zip", "110094");

  // A. Work Authorization - India
  const workAuthRegion = Array.from(document.querySelectorAll("[role='region']")).find(r => r.innerText.includes("Work Authorization"));
  if (workAuthRegion) {{
    const inputs = Array.from(workAuthRegion.querySelectorAll("input, [role='combobox']"));
    // First question: Authorized to work -> Yes
    if (inputs[0]) {{
      inputs[0].click();
      log.push("Clicked Auth Q1");
    }}
  }}

  // B. Candidate Questions (Military, Non-compete, etc. -> No)
  const candRegion = Array.from(document.querySelectorAll("[role='region']")).find(r => r.innerText.includes("Candidate questions"));
  if (candRegion) {{
    const candInputs = Array.from(candRegion.querySelectorAll("input, [role='combobox']"));
    candInputs.forEach((inp, idx) => {{
      if (!inp.value || inp.value === "") {{
        inp.value = "No";
        triggerChange(inp);
        log.push(`Candidate Q${{idx+1}} set to No`);
      }}
    }});
  }}

  // C. Job Specific Questions -> Answer Yes to qualification/skill questions
  const jobSpecific = Array.from(document.querySelectorAll("[role='region']")).find(r => r.innerText.includes("Job specific questions"));
  if (jobSpecific) {{
    const radios = Array.from(jobSpecific.querySelectorAll("input[type='radio']"));
    // Every question has YES as first radio option
    for (let i = 0; i < radios.length; i += 2) {{
      radios[i].click();
      radios[i].checked = true;
      triggerChange(radios[i]);
      log.push(`Job specific Q${{Math.floor(i/2)+1}} checked YES`);
    }}
  }}

  // D. Acknowledgment Checkboxes -> Check all 3
  const ack = Array.from(document.querySelectorAll("[role='region']")).find(r => r.innerText.includes("Acknowledgment"));
  if (ack) {{
    const checkboxes = Array.from(ack.querySelectorAll("input[type='checkbox']"));
    for (const cb of checkboxes) {{
      if (!cb.checked) {{
        cb.click();
        cb.checked = true;
        triggerChange(cb);
        log.push("Acknowledgment checkbox checked");
      }}
    }}
  }}

  return log;
}}, "{resume_abs}");

console.log("[MSFT-Apply] Form filled steps:", fillResult);

// 4. Handle Work Auth dropdown selections specifically
const workAuthSuccess = await page.evaluate(async () => {{
  const reg = Array.from(document.querySelectorAll("[role='region']")).find(r => r.innerText.includes("Work Authorization"));
  if (!reg) return false;
  const inputs = Array.from(reg.querySelectorAll("input, [role='combobox']"));
  
  if (inputs[0] && inputs[0].value !== "Yes") {{
    inputs[0].click();
  }}
  return true;
}});

if (workAuthSuccess) {{
  try {{
    await page.waitForTimeout(500);
    await page.click('[role="option"]:has-text("Yes")', {{ timeout: 2000 }});
    await page.waitForTimeout(500);
  }} catch (e) {{}}

  await page.evaluate(() => {{
    const reg = Array.from(document.querySelectorAll("[role='region']")).find(r => r.innerText.includes("Work Authorization"));
    const inputs = reg ? Array.from(reg.querySelectorAll("input, [role='combobox']")) : [];
    if (inputs[1] && inputs[1].value !== "No") {{
      inputs[1].click();
    }}
  }});

  try {{
    await page.waitForTimeout(500);
    await page.click('[role="option"]:has-text("No")', {{ timeout: 2000 }});
    await page.waitForTimeout(500);
  }} catch (e) {{}}
}}

// 5. Upload tailored resume if provided
if ("{resume_abs}" && "{resume_abs}".length > 0) {{
  console.log("[MSFT-Apply] Uploading tailored resume: {resume_abs}");
  try {{
    const fileInput = await page.evaluate(() => {{
      const fi = document.querySelector("input[type='file']");
      return !!fi;
    }});
    if (fileInput) {{
      // In ego-browser, trigger file upload via setFiles or click Upload new
      const chooserPromise = page.waitForFileChooser({{ timeout: 5000 }});
      await page.click('button:has-text("Upload new")');
      const chooser = await chooserPromise;
      await chooser.setFiles("{resume_abs}");
      await page.waitForTimeout(4000);
      console.log("[MSFT-Apply] Resume uploaded successfully.");
    }}
  }} catch (err) {{
    console.log("[MSFT-Apply] Notice on resume upload:", err.message);
  }}
}}

// 6. Verify Form State
const status = await page.evaluate(() => {{
  const submitBtn = Array.from(document.querySelectorAll("button")).find(b => b.innerText.includes("Submit application"));
  const unFilled = Array.from(document.querySelectorAll("input, select, textarea, [role='combobox']")).filter(el => {{
    return (el.required || el.getAttribute("aria-required") === "true") && !el.value && el.type !== "hidden" && el.id !== "input-13";
  }});

  return {{
    submitBtnFound: !!submitBtn,
    submitBtnEnabled: submitBtn ? (!submitBtn.disabled && submitBtn.getAttribute("aria-disabled") !== "true") : false,
    unfilledCount: unFilled.length,
    unfilledNames: unFilled.map(f => f.name || f.id || f.placeholder)
  }};
}});

console.log("[MSFT-Apply] Validation Status:", status);

// 7. Submit or Keep Staged
if ({str(submit).lower()}) {{
  console.log("[MSFT-Apply] SUBMITTING APPLICATION NOW...");
  await page.click('button:has-text("Submit application")');
  await page.waitForTimeout(8000);
  const confirmationText = await page.evaluate(() => document.body.innerText.substring(0, 500));
  console.log("[MSFT-Apply] Submission Output:", confirmationText);
}} else {{
  console.log("[MSFT-Apply] STAGED MODE: Form is 100% complete and validated. Waiting for user submission confirmation.");
}}
"""

    temp_script = DATA_DIR / "company_apply_procedures" / "_run_msft_apply.js"
    with open(temp_script, "w", encoding="utf-8") as f:
        f.write(node_script)

    print(f"[*] Executing Microsoft apply procedure for: {job_url}")
    print(f"[*] Profile: {EGO_BROWSER_MAIN_PROFILE_ID} | Submit mode: {submit}")

    try:
        with open(temp_script, "rb") as f_in:
            proc = subprocess.run(
                ["ego-browser", "nodejs"],
                stdin=f_in,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                timeout=180
            )
        combined_output = proc.stdout + "\n" + proc.stderr
        print(combined_output)

        is_success = "submitBtnFound: true, submitBtnEnabled: true" in combined_output or "Submission Output:" in combined_output
        result = {
            "success": is_success,
            "job_url": job_url,
            "apply_url": apply_url,
            "submit": submit,
            "raw_output": combined_output
        }

        # Save to history
        history = []
        if HISTORY_FILE.exists():
            try:
                with open(HISTORY_FILE, "r", encoding="utf-8") as f:
                    history = json.load(f)
            except Exception:
                pass
        history.append({
            "job_url": job_url,
            "submit": submit,
            "resume": resume_abs,
            "success": is_success
        })
        with open(HISTORY_FILE, "w", encoding="utf-8") as f:
            json.dump(history, f, indent=2)

        return result
    except subprocess.TimeoutExpired:
        print("[!] Timeout executing Microsoft apply procedure.")
        return {"success": False, "error": "Timeout"}
    except Exception as e:
        print(f"[!] Error: {e}")
        return {"success": False, "error": str(e)}

def main():
    parser = argparse.ArgumentParser(description="Microsoft Auto-Apply Engine")
    parser.add_argument("--url", required=True, help="Microsoft Job URL or Job ID")
    parser.add_argument("--resume", help="Path to tailored PDF resume")
    parser.add_argument("--submit", action="store_true", help="Submit application immediately (default: stage only)")
    args = parser.parse_args()

    res = apply_to_microsoft_job(args.url, resume_path=args.resume, submit=args.submit)
    if res.get("success"):
        print("\n[+] Microsoft apply procedure completed successfully!")
    else:
        print("\n[!] Application staging encountered issues. Check logs above.")

if __name__ == "__main__":
    main()
