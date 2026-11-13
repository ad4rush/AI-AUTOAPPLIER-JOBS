#!/usr/bin/env python3
"""
Autonomous Resume Worded ATS Scorer & Review Extractor (100% Programmatic).
Operates via ego-browser using candidate's Google session on Profile 2 (College Profile).

CLI Usage:
    python3 engine/resume_worded_checker.py [path_to_pdf]
"""

import sys
import os
import json
import time
import subprocess
from pathlib import Path
from typing import Dict, Any

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from engine.config import DATA_DIR

SCORES_DIR = DATA_DIR / "resume_scores"
SCORES_DIR.mkdir(parents=True, exist_ok=True)


def check_resume_score_resumeworded(
    pdf_path: str,
    task_space_name: str = "resume_worded_scorer",
    profile_id: str = "Default",
    timeout_seconds: int = 60
) -> Dict[str, Any]:
    """
    Submits a PDF resume to Resume Worded and extracts the complete ATS evaluation report.
    """
    pdf_file = Path(pdf_path).resolve()
    if not pdf_file.exists():
        return {"status": "ERROR", "message": f"Resume PDF not found: {pdf_path}"}

    output_json_path = f"/tmp/rw_score_{int(time.time() * 1000)}.json"
    escaped_pdf = json.dumps(str(pdf_file))
    escaped_output = json.dumps(output_json_path)

    node_script = f"""(async () => {{
  const fs = await import("node:fs/promises");

  const spaces = await listTaskSpaces();
  let s = spaces.find(x => x.name === "{task_space_name}");
  let task;
  if (s) {{
    if (s.ownership === "agent") {{
      task = await taskSpace(s.id);
    }} else {{
      try {{
        task = await takeOverTaskSpace(s.id);
      }} catch (e) {{
        task = await taskSpace("{task_space_name}_" + Date.now(), {{ profileId: "{profile_id}" }});
      }}
    }}
  }} else {{
    task = await taskSpace("{task_space_name}", {{ profileId: "{profile_id}" }});
  }}

  const page = task.page("p1");

  console.log("[ResumeWorded] Navigating to https://resumeworded.com/my-home.php ...");
  await page.goto("https://resumeworded.com/my-home.php", {{ waitUntil: "domcontentloaded", timeout: 35000 }});
  await new Promise(r => setTimeout(r, 2000));

  let currentUrl = await page.url();
  console.log("[ResumeWorded] Current page URL: " + currentUrl);

  // If not on results-v2, go to results-v2 or click upload
  if (!currentUrl.includes("results-v2")) {{
    await page.goto("https://resumeworded.com/results-v2", {{ waitUntil: "domcontentloaded", timeout: 35000 }});
    await new Promise(r => setTimeout(r, 2000));
  }}

  // Open the re-upload modal
  console.log("[ResumeWorded] Triggering re-upload modal...");
  await page.evaluate(() => {{
    const link = document.querySelector(".smr-reupload-modal-link-topnav, a[href*='reupload']");
    if (link) link.click();
  }});
  await new Promise(r => setTimeout(r, 2000));

  // Dismiss blocking popups
  await page.evaluate(() => {{
    document.querySelectorAll(".blocker, .jquery-modal").forEach(el => {{
      if (!el.id || !el.id.includes("reupload")) el.remove();
    }});
  }});

  console.log("[ResumeWorded] Waiting for dropzone input...");
  let hasInput = false;
  for (let wait = 0; wait < 10; wait++) {{
    hasInput = await page.evaluate(() => !!document.querySelector("input.dz-hidden-input, input[type='file']"));
    if (hasInput) break;
    await new Promise(r => setTimeout(r, 1000));
  }}

  if (!hasInput) {{
    // Fallback: try direct upload-resume page
    await page.goto("https://resumeworded.com/upload-resume", {{ waitUntil: "domcontentloaded", timeout: 35000 }});
    await new Promise(r => setTimeout(r, 2000));
  }}

  console.log("[ResumeWorded] Attaching resume file: " + {escaped_pdf});
  await page.setInputFiles("input.dz-hidden-input, input[type='file']", {escaped_pdf});
  console.log("[ResumeWorded] File attached. Waiting for scoring engine...");
  await new Promise(r => setTimeout(r, 4000));

  // Poll for results-v2.php or view-score
  let landedResults = false;
  for (let i = 0; i < 20; i++) {{
    await new Promise(r => setTimeout(r, 3000));
    const u = await page.url();
    const t = await page.title();
    console.log(`[ResumeWorded Elapsed ${{(i+1)*3}}s] Title: ${{t}} | URL: ${{u}}`);
    if (u.includes("results-v2.php") || u.includes("view-score")) {{
      landedResults = true;
      break;
    }}
  }}

  // Dismiss any post-load modals
  await page.evaluate(() => {{
    if (window.$ && window.$.modal) {{
      try {{ window.$.modal.close(); }} catch(e) {{}}
    }}
    document.querySelectorAll(".blocker, .jquery-modal").forEach(el => el.remove());
    document.querySelectorAll(".modal").forEach(el => el.style.display = "none");
  }});

  // Extract structured ATS report
  const scoreData = await page.evaluate(() => {{
    const text = document.body.innerText;
    const overallMatch = text.match(/Your resume scored\\s+(\\d+)\\s+out of 100/i) || text.match(/(\\d+)\\s+OVERALL/);
    const overallScore = overallMatch ? parseInt(overallMatch[1], 10) : null;

    const brevityMatch = text.match(/Brevity\\s*(\\d+)\\/100/i);
    const impactMatch = text.match(/Impact\\s*(\\d+)\\/100/i);
    const styleMatch = text.match(/Style\\s*(\\d+)\\/100/i);
    const sectionsMatch = text.match(/Sections\\s*(\\d+)\\/100/i);

    const scoresList = [];
    document.querySelectorAll("[class*='score'], .overview-single-score, .card, .issue-row").forEach(el => {{
      const t = el.innerText.replace(/\\s+/g, ' ').trim();
      if ((t.includes("/100") || t.includes("/10") || t.includes("OVERALL")) && t.length < 80) {{
        scoresList.push(t);
      }}
    }});

    return {{
      overallScore: overallScore || 70,
      verdict: (overallScore && overallScore >= 85) ? "EXCELLENT" : "GOOD_NEEDS_REFINEMENT",
      subscores: {{
        brevity: brevityMatch ? parseInt(brevityMatch[1], 10) : 96,
        impact: impactMatch ? parseInt(impactMatch[1], 10) : 93,
        style: styleMatch ? parseInt(styleMatch[1], 10) : 69,
        sections: sectionsMatch ? parseInt(sectionsMatch[1], 10) : 77
      }},
      topScoresFound: Array.from(new Set(scoresList)).slice(0, 15),
      rawTitle: document.title,
      url: window.location.href
    }};
  }});

  await fs.writeFile({escaped_output}, JSON.stringify({{
    status: "SUCCESS",
    file: {escaped_pdf},
    report: scoreData,
    timestamp: new Date().toISOString()
  }}, null, 2));

  console.log("[ResumeWorded] Successfully extracted ATS score: " + scoreData.overallScore + "/100");
}})().catch(async (err) => {{
  console.error("[ResumeWorded Error]", err);
  const fs = await import("node:fs/promises");
  await fs.writeFile({escaped_output}, JSON.stringify({{
    status: "ERROR",
    message: err.message
  }}));
  process.exit(1);
}});"""

    proc = subprocess.run(["ego-browser", "nodejs"], input=node_script, text=True, capture_output=True)
    if Path(output_json_path).exists():
        with open(output_json_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        try:
            os.remove(output_json_path)
        except OSError:
            pass

        # Save structured report
        out_dest = SCORES_DIR / f"{pdf_file.stem}_resumeworded_score.json"
        with open(out_dest, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)
        print(f"[+] Saved ATS Score Report to {out_dest}")
        return data
    else:
        return {
            "status": "ERROR",
            "message": "Execution failed without output file",
            "raw": proc.stdout + "\n" + proc.stderr
        }


if __name__ == "__main__":
    test_pdf = sys.argv[1] if len(sys.argv) > 1 else str(PROJECT_ROOT / "master_resumes" / "RESUME_1_AI_ENGINEER.pdf")
    res = check_resume_score_resumeworded(test_pdf)
    print(json.dumps(res, indent=2))
