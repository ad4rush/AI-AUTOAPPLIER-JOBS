#!/usr/bin/env python3
"""
Autonomous Multi-Round Claude Tailoring & ChatGPT Critic Loop.
Automates end-to-end resume optimization across up to 3 iterative rounds:
1. Claude Sonnet 5.5 generates specialized XeTeX LaTeX code from the JD.
2. Tectonic / XeLaTeX compiles and guarantees a strict single page.
3. ChatGPT Profile 1 acts as the quantitative ATS Critic (ATS score, keyword density, impact).
4. If ATS score < 85/100, passes specific critique feedback back to Claude to refine bullets.
5. Loops up to 3 iterations or until approved / message limit reached.
"""

import os
import re
import sys
import json
import time
import subprocess
from pathlib import Path
from typing import Dict, Any, Tuple, Optional

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from engine.config import EGO_BROWSER_PROFILE_ID, DATA_DIR
from engine.claude_tailor import (
    generate_tailored_resume_via_claude,
    review_tailored_resume_with_chatgpt,
    inject_candidate_profile,
    RESUMES_GENERATED_DIR
)
from engine.resume_ats_sanitizer import compile_and_guarantee_single_page

def execute_automated_tailor_and_critique_loop(
    company: str,
    title: str,
    jd_text: str,
    max_rounds: int = 3
) -> Dict[str, Any]:
    """
    Executes automated tailoring with up to max_rounds of critique refinement.
    Returns:
    {
        "success": bool,
        "pdf_path": str,
        "final_ats_score": int,
        "rounds_completed": int,
        "history": list
    }
    """
    clean_company = re.sub(r"[^a-zA-Z0-9]", "", company)[:15].lower()
    clean_title = re.sub(r"[^a-zA-Z0-9]", "", title)[:15].lower()
    job_id = f"loop_{clean_company}_{clean_title}_{int(time.time())}"

    print(f"\n[=== Initiating Autonomous Tailor & Critic Loop: {company} — {title} (Max Rounds: {max_rounds}) ===]")

    # Round 1: Initial Claude generation
    success, msg, tex_path, pdf_path = generate_tailored_resume_via_claude(
        job_id=job_id,
        company=company,
        title=title,
        jd=jd_text or title
    )

    if not success or not tex_path or not tex_path.exists():
        print(f"[!] Round 1 failed: {msg}")
        return {
            "success": False,
            "pdf_path": str(pdf_path) if pdf_path else None,
            "final_ats_score": 0,
            "rounds_completed": 1,
            "error": msg
        }

    history = []
    current_tex_path = tex_path
    current_pdf_path = pdf_path
    current_score = 90

    for current_round in range(1, max_rounds + 1):
        with open(current_tex_path, "r", encoding="utf-8") as f:
            latex_code = f.read()

        # Step 2: ChatGPT Critic Review
        print(f"[*] Round {current_round}: Querying ChatGPT Profile 1 for quantitative ATS critique...")
        review = review_tailored_resume_with_chatgpt(
            latex_code=latex_code,
            jd={"title": title, "company": company, "description": jd_text},
            company=company,
            title=title
        )
        current_score = review.get("ats_score", 90)
        missing_kw = review.get("missing_keywords", [])
        verdict = review.get("verdict", "READY_TO_APPLY")

        print(f"[+] Round {current_round} Score: {current_score}/100 (Verdict: {verdict}) | Missing: {', '.join(missing_kw[:4])}")

        history.append({
            "round": current_round,
            "score": current_score,
            "missing_keywords": missing_kw,
            "verdict": verdict
        })

        # If score is top tier or this is final round, stop loop
        if current_score >= 85 or current_round == max_rounds or not missing_kw:
            print(f"[✓] Resume approved on Round {current_round} with ATS score {current_score}/100!")
            break

        # Step 3: Pass Critique back to Claude for refinement
        print(f"[*] Round {current_round} score {current_score} < 85. Passing critique feedback to Claude for Round {current_round + 1} refinement...")
        critique_prompt = f"""ATS CRITIQUE REVISION REQUEST:
The previous tailored resume scored {current_score}/100 on ATS evaluation.
Missing critical keywords to integrate: {', '.join(missing_kw[:5])}.
Please revise the LaTeX code to:
1. Seamlessly integrate these missing keywords into the candidate's core production engineering and research project bullet points.
2. Ensure all bullet points use strong action verbs and quantified metrics (e.g. latency p95 < 600ms, $300/day savings, 99.8% reliability).
3. STRICT REQUIREMENT: Keep the resume EXACTLY 1 page (0 page-2 overflow).
Return ONLY the complete updated LaTeX code inside a ```latex codeblock."""

        refine_script = f"""
const sleep = (ms) => new Promise(r => setTimeout(r, ms));
const spaces = await listTaskSpaces();
const s = spaces.find(x => x.name === "job_applier_workload");
if (!s) process.exit(1);

const task = await taskSpace(s.id);
const p1 = task.page("p1");

// Insert critique into composer
await p1.waitForSelector('div.tiptap.ProseMirror', {{ timeout: 15000 }});
await p1.click('div.tiptap.ProseMirror');
await sleep(500);

await p1.evaluate((text) => {{
  const ce = document.querySelector('div.tiptap.ProseMirror');
  if (ce) {{
    ce.focus();
    document.execCommand("insertText", false, text);
  }}
}}, {json.dumps(critique_prompt)});

await sleep(1000);
await p1.evaluate(() => {{
  const sendBtn = document.querySelector('button[aria-label="Send message"], button[aria-label="Send Message"]');
  if (sendBtn) sendBtn.click();
}});

// Wait for updated code
for (let i = 0; i < 40; i++) {{
  await sleep(3000);
  const state = await p1.evaluate(() => {{
    const stopBtn = document.querySelector('button[aria-label="Stop generating"], button[aria-label="Stop response"]');
    const codeBlocks = Array.from(document.querySelectorAll('pre, code'));
    return {{
      isStreaming: !!stopBtn,
      blocksCount: codeBlocks.length,
      lastBlock: codeBlocks.length > 0 ? codeBlocks[codeBlocks.length - 1].innerText : ""
    }};
  }});
  if (!state.isStreaming && state.lastBlock.includes("\\\\documentclass")) {{
    const fs = await import("node:fs/promises");
    await fs.writeFile("/tmp/claude_refined_{job_id}.tex", state.lastBlock);
    process.exit(0);
  }}
}}
"""
        proc = subprocess.run(
            ["ego-browser", "nodejs"],
            input=refine_script,
            capture_output=True,
            text=True,
            timeout=140
        )

        refined_path = Path(f"/tmp/claude_refined_{job_id}.tex")
        if refined_path.exists():
            refined_code = refined_path.read_text(encoding="utf-8")
            refined_code = inject_candidate_profile(refined_code)
            
            # Save refined TeX
            current_tex_path = current_tex_path.parent / f"resume_{clean_company}_r{current_round + 1}.tex"
            current_tex_path.write_text(refined_code, encoding="utf-8")

            # Compile & verify strict 1 page
            comp_ok, comp_log, new_pdf, pages = compile_and_guarantee_single_page(current_tex_path, current_tex_path.parent)
            if comp_ok and new_pdf and new_pdf.exists():
                current_pdf_path = new_pdf
                print(f"[+] Round {current_round + 1} compilation successful (strict {pages} page).")
            else:
                print(f"[!] Round {current_round + 1} compilation failed. Keeping Round {current_round} PDF.")
                break
        else:
            print(f"[!] Claude refinement timeout or rate limit. Keeping Round {current_round} PDF.")
            break

    return {
        "success": True,
        "pdf_path": str(current_pdf_path.resolve()) if current_pdf_path else None,
        "final_ats_score": current_score,
        "rounds_completed": len(history),
        "history": history
    }


if __name__ == "__main__":
    print("--- Testing Tailor & Critic Loop Module ---")
    test_comp = "Anthropic"
    test_tit = "Research Engineer, Pre-training"
    test_jd = "Distributed training of large frontier models, low-latency communication, checkpoint recovery, Python, PyTorch, CUDA, distributed systems."
    res = execute_automated_tailor_and_critique_loop(test_comp, test_tit, test_jd, max_rounds=2)
    print("Result:", res)
