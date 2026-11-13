#!/usr/bin/env python3
"""
Autonomous Universal micro1 Job Application Engine.
Applies or stages applications for micro1 roles (jobs.micro1.ai) via ego-browser on Profile 1.
Handles authentication (Google OAuth / email OTP), candidate info verification,
resume attachment, questionnaire answers, and submission verification.
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
    CANDIDATE_NAME,
    CANDIDATE_PERSONAL_EMAIL,
    CANDIDATE_PHONE,
    CANDIDATE_LINKEDIN,
    CANDIDATE_GITHUB,
    DATA_DIR
)
from engine.db import update_job_status, update_text_summary
from engine.email_reader import fetch_profile_emails

def apply_to_micro1_job(
    url: str,
    resume_path: Optional[str] = None,
    rate_usd: str = "75",
    submit: bool = True,
    task_space_name: str = "micro1_auto_apply"
) -> Dict[str, Any]:
    """
    Executes automated application flow for micro1 roles.
    """
    if not resume_path:
        resume_path = str(PROJECT_ROOT / "master_resumes" / "RESUME_1_AI_ENGINEER.pdf")
    resume_abs = str(Path(resume_path).resolve())

    # Build answers payload
    answers = {
        "rate": str(rate_usd),
        "portfolio": CANDIDATE_GITHUB,
        "python_exp": "3+ years production Python: PyTorch, Hugging Face, PEFT/LoRA, FastAPI, LangGraph, async pipelines, distributed backends.",
        "tools_exp": "Python, PyTorch, Hugging Face Transformers, vLLM, DeepSpeed, LoRA fine-tuning, automated LLM evaluation benchmarks.",
        "ai_training": "Implemented LoRA fine-tuning on PyTorch models achieving 75% parameter compression and 2x inference speedup. Developed automated eval harnesses for multi-agent conversational voice AI and Text-to-SQL.",
        "github_details": f"GitHub: {CANDIDATE_GITHUB}. Repos: 1) nova-sonic-voice: Production sub-600ms conversational voice AI backend with real-time RAG. 2) ontology-text2sql: High-accuracy Text-to-SQL engine with self-correcting query pipelines."
    }

    node_script = f"""
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
        task = await taskSpace("{task_space_name}_worker", {{ profileId: "{EGO_BROWSER_MAIN_PROFILE_ID}" }});
      }}
    }}
  }} else {{
    task = await taskSpace("{task_space_name}", {{ profileId: "{EGO_BROWSER_MAIN_PROFILE_ID}" }});
  }}

  const page = task.page("p1");
  console.log("[micro1] Navigating to: {url}");
  await page.goto("{url}", {{ waitUntil: "domcontentloaded", timeout: 35000 }});
  await page.waitForTimeout(3000);

  // Check if candidate details already shown
  let hasDetails = await page.evaluate(() => {{
    const text = document.body.innerText || "";
    return text.includes("Your details") && text.includes("Next");
  }});

  // If not logged in, attempt Google Sign-In or email OTP
  if (!hasDetails) {{
    console.log("[micro1] Not yet logged in. Checking Google Sign-In button...");
    const box = await page.evaluate(() => {{
      const f = document.querySelector("iframe[title*='Sign in with Google']");
      if (!f) return null;
      const r = f.getBoundingClientRect();
      return {{ x: r.left + r.width / 2, y: r.top + r.height / 2 }};
    }});

    if (box) {{
      console.log("[micro1] Clicking Google Sign-In button at coordinates...");
      await page.mouse.click(box.x, box.y);
      await page.waitForTimeout(4000);

      // Handle popup page if opened
      const p2 = task.page("p2");
      if (p2) {{
        try {{
          await p2.waitForTimeout(2000);
          console.log("[micro1] Google account chooser detected. Clicking account...");
          await p2.click("div[data-identifier='{CANDIDATE_PERSONAL_EMAIL}']");
          await p2.waitForTimeout(4000);
        }} catch(e) {{
          console.log("[micro1] Note on Google popup: " + e.message);
        }}
      }}
      await page.waitForTimeout(3000);
    }}
  }}

  // Check again for details screen
  hasDetails = await page.evaluate(() => {{
    const text = document.body.innerText || "";
    return text.includes("Your details") && text.includes("Next");
  }});

  if (hasDetails) {{
    console.log("[micro1] Active user profile detected on details screen.");
    
    // Upload resume if file input is available
    const hasFileInput = await page.evaluate(() => !!document.querySelector("input#file, input[type='file']"));
    if (hasFileInput) {{
      console.log("[micro1] Uploading resume: {resume_abs}");
      await page.setInputFiles("input#file, input[type='file']", "{resume_abs}");
      await page.waitForTimeout(2000);
    }}

    console.log("[micro1] Clicking Next to advance to questionnaire...");
    await page.click("button:has-text('Next')");
    await page.waitForTimeout(4000);
  }}

  // Now fill the questionnaire
  console.log("[micro1] Filling questionnaire fields...");
  const ans = {json.dumps(answers)};
  await page.evaluate((ans) => {{
    const setVal = (el, val) => {{
      const proto = Object.getPrototypeOf(el);
      const desc = Object.getOwnPropertyDescriptor(proto, "value");
      if (desc && desc.set) {{
        desc.set.call(el, val);
      }} else {{
        el.value = val;
      }}
      el.dispatchEvent(new Event("input", {{ bubbles: true }}));
      el.dispatchEvent(new Event("change", {{ bubbles: true }}));
    }};

    // Number input (Rate)
    const num = document.querySelector("form input[type='number']");
    if (num) setVal(num, ans.rate);

    // Radios (All Yes options)
    const radios = Array.from(document.querySelectorAll("form input[type='radio'][id*='_yes']"));
    radios.forEach(r => {{
      r.checked = true;
      r.dispatchEvent(new Event("change", {{ bubbles: true }}));
      r.click();
    }});

    // Text inputs & textareas
    const inps = Array.from(document.querySelectorAll("form input[type='text'], form textarea")).filter(i => !i.id.includes("select"));
    if (inps.length === 1) {{
      setVal(inps[0], ans.github_details);
    }} else if (inps.length >= 4) {{
      setVal(inps[0], ans.portfolio);
      setVal(inps[1], ans.python_exp);
      setVal(inps[2], ans.tools_exp);
      setVal(inps[3], ans.ai_training);
    }} else if (inps.length >= 2) {{
      setVal(inps[0], ans.github_details);
      setVal(inps[1], ans.tools_exp);
    }}
  }}, ans);
  await page.waitForTimeout(1000);

  // Handle multi-select dropdown if present
  const hasSelect = await page.evaluate(() => !!document.querySelector("[id*='react-select']"));
  if (hasSelect) {{
    console.log("[micro1] Selecting tool / language options in react-select...");
    for (const optName of ["Other", "Python", "Go"]) {{
      const selectInp = await page.$("[id*='react-select'] input, input[id*='react-select']");
      if (selectInp) {{
        try {{
          await page.click("[id*='react-select'] input, input[id*='react-select']");
          await page.waitForTimeout(300);
          await page.evaluate((name) => {{
            const opt = Array.from(document.querySelectorAll("[id*='option'], div[class*='option'], [role='option']")).find(o => (o.innerText || "").trim().toLowerCase() === name.toLowerCase());
            if (opt) opt.click();
          }}, optName);
          await page.waitForTimeout(300);
        }} catch(e) {{}}
      }}
    }}
  }}

  const validation = await page.evaluate(() => {{
    const btn = Array.from(document.querySelectorAll("button")).find(b => (b.innerText || "").trim().toLowerCase() === "submit");
    return {{
      submitFound: !!btn,
      submitDisabled: btn ? btn.disabled : true
    }};
  }});
  console.log("[micro1] Validation:", JSON.stringify(validation));

  if ({str(submit).lower()} && validation.submitFound && !validation.submitDisabled) {{
    console.log("[micro1] SUBMIT MODE: Clicking Submit...");
    await page.click("button:has-text('Submit')");
    await page.waitForTimeout(6000);

    const postState = await page.evaluate(() => ({{
      url: document.location.href,
      success: document.location.href.includes("/success") || (document.body.innerText || "").includes("one step away")
    }}));
    console.log("===MICRO1_RESULT===");
    console.log(JSON.stringify({{ success: postState.success, url: postState.url }}));
    console.log("===END_MICRO1_RESULT===");
  }} else {{
    console.log("[micro1] STAGED MODE: Ready for review.");
    console.log("===MICRO1_RESULT===");
    console.log(JSON.stringify({{ success: true, staged: true, url: await page.url() }}));
    console.log("===END_MICRO1_RESULT===");
  }}
}})();
"""

    script_file = DATA_DIR / "company_apply_procedures" / "_temp_micro1_apply.js"
    script_file.write_text(node_script, encoding="utf-8")

    try:
        proc = subprocess.run(["ego-browser", "nodejs"], stdin=open(script_file, "r"), capture_output=True, text=True, timeout=90)
        combined = proc.stdout + "\n" + proc.stderr
        if "===MICRO1_RESULT===" in combined:
            raw = combined.split("===MICRO1_RESULT===")[1].split("===END_MICRO1_RESULT===")[0].strip()
            return json.loads(raw)
        return {"success": False, "error": combined[:600]}
    except Exception as e:
        return {"success": False, "error": str(e)}

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="micro1 Autonomous Apply Engine")
    parser.add_argument("--url", required=True, help="micro1 job post URL")
    parser.add_argument("--resume", help="Path to PDF resume")
    parser.add_argument("--rate", default="75", help="Hourly rate in USD")
    parser.add_argument("--submit", action="store_true", help="Auto-submit")
    args = parser.parse_args()

    res = apply_to_micro1_job(args.url, resume_path=args.resume, rate_usd=args.rate, submit=args.submit)
    print(json.dumps(res, indent=2))
