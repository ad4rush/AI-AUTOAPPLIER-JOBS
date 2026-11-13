#!/usr/bin/env python3
"""
Autonomous Manatal (careers-page.com) Application Engine.
Operates via ego-browser on Profile 1 ("Main Profile").

Handles both Manatal Themes:
1. Modern Theme (React Shadow DOM inside #application-root):
   - Fast 2-field application (Full Name, Email, Terms Checkbox).
2. Classic Theme (Standard HTML DOM):
   - Full Name, Email, Phone, Cover Letter, Resume Upload (PDF), Terms Checkbox.

Supports both AUTO_SUBMIT (submit=True) and STAGE_FOR_REVIEW (submit=False).
"""

import sys
import json
import subprocess
from pathlib import Path
from typing import Dict, Any, Optional

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from engine.config import (
    CANDIDATE_NAME,
    CANDIDATE_PERSONAL_EMAIL,
    CANDIDATE_PHONE,
    CANDIDATE_CURRENT_COMPANY,
    CANDIDATE_CURRENT_TITLE,
    ANS_COLLEGE,
    CANDIDATE_HONORS,
    EGO_BROWSER_MAIN_PROFILE_ID,
    DATA_DIR
)

MANATAL_SCRIPTS_DIR = DATA_DIR / "company_apply_procedures"
MANATAL_SCRIPTS_DIR.mkdir(parents=True, exist_ok=True)


def apply_to_manatal_job(
    url: str,
    resume_path: Optional[str] = None,
    submit: bool = True,
    task_space_name: str = "manatal_auto_apply"
) -> Dict[str, Any]:
    """
    Submits or stages an application on any Manatal careers-page.com portal.
    """
    print(f"\n[*] Launching Manatal Application Engine on Profile 1...")
    print(f"[*] Target URL: {url}")
    print(f"[*] Submission Mode: {'AUTO_SUBMIT' if submit else 'STAGE_FOR_REVIEW'}")

    apply_url = url if "/apply" in url else url.rstrip("/") + "/apply"

    if not resume_path or not Path(resume_path).exists():
        resume_path = str(PROJECT_ROOT / "master_resumes" / "RESUME_1_AI_ENGINEER.pdf")

    escaped_resume = json.dumps(str(resume_path))

    js_script = f"""
(async () => {{
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
        task = await taskSpace("{task_space_name}_runner", {{ profileId: "{EGO_BROWSER_MAIN_PROFILE_ID}" }});
      }}
    }}
  }} else {{
    task = await taskSpace("{task_space_name}", {{ profileId: "{EGO_BROWSER_MAIN_PROFILE_ID}" }});
  }}

  const page = task.page("p1");
  console.log("[Manatal] Navigating to apply page: {apply_url}");
  await page.goto("{apply_url}", {{ waitUntil: "domcontentloaded", timeout: 35000 }});
  await page.waitForTimeout(3000);

  // If redirected away from /apply, try clicking 'Apply now' on the job view page
  let currentUrl = await page.url();
  if (!currentUrl.includes("/apply")) {{
    console.log("[Manatal] Not on apply form, attempting to click 'Apply now'...");
    await page.evaluate(() => {{
      const btn = Array.from(document.querySelectorAll("button, a")).find(b => (b.innerText || "").toLowerCase().includes("apply now"));
      if (btn) btn.click();
    }});
    await page.waitForTimeout(3000);
  }}

  // Determine form theme: Modern (shadowRoot) vs Classic (standard DOM)
  let isModern = false;
  for (let i = 0; i < 5; i++) {{
    isModern = await page.evaluate(() => {{
      const root = document.getElementById("application-root");
      return !!(root && root.shadowRoot);
    }});
    if (isModern) break;
    await page.waitForTimeout(500);
  }}

  console.log(`[Manatal] Detected form architecture: ${{isModern ? "Modern (Shadow DOM)" : "Classic (Standard DOM)"}}`);

  if (isModern) {{
    // THEME 1: Modern React Shadow DOM
    const fillResult = await page.evaluate(({{ name, email }}) => {{
      const root = document.getElementById("application-root");
      const shadow = root.shadowRoot;

      function setReactInput(input, value) {{
        const nativeSetter = Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, "value").set;
        nativeSetter.call(input, value);
        input.dispatchEvent(new Event("input", {{ bubbles: true, composed: true }}));
        input.dispatchEvent(new Event("change", {{ bubbles: true, composed: true }}));
      }}

      const nameInput = shadow.querySelector("input[placeholder*='name'], input[placeholder*='Name']") ||
                       shadow.querySelectorAll("input[type='text']")[0];
      if (nameInput) setReactInput(nameInput, name);

      const emailInput = shadow.querySelector("input[placeholder*='@'], input[type='email']") ||
                        shadow.querySelectorAll("input[type='text']")[1];
      if (emailInput) setReactInput(emailInput, email);

      const chkBtn = shadow.querySelector("button[role='checkbox'], [data-testid='m-checkbox']");
      if (chkBtn && chkBtn.getAttribute("aria-checked") !== "true") {{
        chkBtn.click();
      }}

      return {{
        nameFilled: !!nameInput,
        emailFilled: !!emailInput,
        checkboxClicked: !!chkBtn
      }};
    }}, {{
      name: "{CANDIDATE_NAME}",
      email: "{CANDIDATE_PERSONAL_EMAIL}"
    }});

    if (!fillResult.nameFilled || !fillResult.emailFilled) {{
      console.log("===MANATAL_RESULT===");
      console.log(JSON.stringify({{ success: false, error: "Failed to populate shadow DOM inputs.", fillResult }}));
      console.log("===END_MANATAL_RESULT===");
      return;
    }}

    if ({str(submit).lower()}) {{
      await page.waitForTimeout(1000);
      await page.evaluate(() => {{
        const root = document.getElementById("application-root");
        const btn = Array.from(root.shadowRoot.querySelectorAll("button")).find(b => 
          (b.innerText || "").toLowerCase().includes("apply now") || b.type === "submit"
        );
        if (btn) btn.click();
      }});
      await page.waitForTimeout(4000);

      const postSubmit = await page.evaluate(() => {{
        const root = document.getElementById("application-root");
        const shadowText = root && root.shadowRoot ? root.shadowRoot.textContent : "";
        const bodyText = document.body.innerText;
        return {{ shadowText: shadowText.slice(0, 500), bodyText: bodyText.slice(0, 500) }};
      }});

      const fullSnippet = (postSubmit.shadowText + " " + postSubmit.bodyText).toLowerCase();
      const isSuccess = ["thank", "received", "submitted", "success"].some(w => fullSnippet.includes(w));

      console.log("===MANATAL_RESULT===");
      console.log(JSON.stringify({{
        success: isSuccess,
        submitted: true,
        theme: "modern",
        notes: "Direct application submitted via Manatal Modern theme.",
        details: postSubmit
      }}));
      console.log("===END_MANATAL_RESULT===");
    }} else {{
      console.log("===MANATAL_RESULT===");
      console.log(JSON.stringify({{ success: true, submitted: false, staged: true, theme: "modern" }}));
      console.log("===END_MANATAL_RESULT===");
    }}
  }} else {{
    // THEME 2: Classic Standard HTML DOM
    // 1. Upload Resume PDF
    try {{
      await page.setInputFiles("input[type='file']", {escaped_resume});
      console.log("[Manatal] Uploaded resume PDF via setInputFiles.");
    }} catch(e) {{
      console.log("[Manatal] Note on file upload: " + e.message);
    }}

    // 2. Fill text fields
    const fillClassic = await page.evaluate(({{ name, email, phone }}) => {{
      const nameEl = document.querySelector("input[placeholder*='Full Name'], input[placeholder*='name'], input[name*='name'], input[id*='field443061']");
      if (nameEl) nameEl.value = name;

      const emailEl = document.querySelector("input[placeholder*='Email'], input[placeholder*='email'], input[name*='email'], input[id*='field443062']");
      if (emailEl) emailEl.value = email;

      const phoneEl = document.querySelector("input[placeholder*='Phone'], input[placeholder*='phone'], input[name*='phone'], input[id*='field443063']");
      if (phoneEl) phoneEl.value = phone;

      const clEl = document.querySelector("textarea");
      if (clEl) {{
        clEl.value = "I am an {CANDIDATE_CURRENT_TITLE} at {CANDIDATE_CURRENT_COMPANY} and student at {ANS_COLLEGE} ({CANDIDATE_HONORS}). Experienced in production distributed systems, LLM agents, and high-scale data platforms. Eager to contribute directly to engineering impact.";
      }}

      const chk = document.querySelector("input[type='checkbox']");
      if (chk && !chk.checked) chk.click();

      return {{
        nameFilled: !!nameEl,
        emailFilled: !!emailEl,
        phoneFilled: !!phoneEl,
        chkClicked: !!chk
      }};
    }}, {{
      name: "{CANDIDATE_NAME}",
      email: "{CANDIDATE_PERSONAL_EMAIL}",
      phone: "{CANDIDATE_PHONE}"
    }});

    console.log("[Manatal] Classic fill status:", JSON.stringify(fillClassic));

    if ({str(submit).lower()}) {{
      await page.waitForTimeout(1000);
      await page.evaluate(() => {{
        const btn = document.querySelector("#submit-id-submit, button[type='submit'], input[type='submit']");
        if (btn) btn.click();
      }});
      await page.waitForTimeout(4000);

      const bodyText = await page.evaluate(() => document.body.innerText.slice(0, 600));
      const fullLow = bodyText.toLowerCase();
      const isSuccess = ["thank", "received", "submitted", "success"].some(w => fullLow.includes(w));

      console.log("===MANATAL_RESULT===");
      console.log(JSON.stringify({{
        success: isSuccess,
        submitted: true,
        theme: "classic",
        notes: "Direct application submitted via Manatal Classic theme.",
        confirmation_snippet: bodyText.slice(0, 200).replace(/\\s+/g, " ")
      }}));
      console.log("===END_MANATAL_RESULT===");
    }} else {{
      console.log("===MANATAL_RESULT===");
      console.log(JSON.stringify({{ success: true, submitted: false, staged: true, theme: "classic" }}));
      console.log("===END_MANATAL_RESULT===");
    }}
  }}
}})();
"""

    script_path = MANATAL_SCRIPTS_DIR / "_run_manatal_apply.js"
    script_path.write_text(js_script, encoding="utf-8")

    try:
        proc = subprocess.run(
            ["ego-browser", "nodejs"],
            stdin=open(script_path, "r"),
            capture_output=True,
            text=True,
            timeout=120
        )
        combined = (proc.stdout or "") + "\n" + (proc.stderr or "")

        if "===MANATAL_RESULT===" in combined:
            raw_res = combined.split("===MANATAL_RESULT===")[1].split("===END_MANATAL_RESULT===")[0].strip()
            return json.loads(raw_res)

        return {
            "success": False,
            "error": "No structured result from Manatal apply script.",
            "raw_output": combined[-600:]
        }
    except Exception as e:
        return {"success": False, "error": str(e)}


if __name__ == "__main__":
    test_url = "https://www.careers-page.com/quantum-strides-llc/job/638WV63W/apply"
    res = apply_to_manatal_job(test_url, submit=False)
    print("Result:", json.dumps(res, indent=2))
