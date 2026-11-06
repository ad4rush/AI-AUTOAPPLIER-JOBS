#!/usr/bin/env python3
"""
Submission Detector & Application Watcher for Job Finder & Applier Platform.
Monitors active ego-browser taskSpaces (microsoft_auto_apply, ashby_auto_apply,
greenhouse_auto_apply, greenhouse_inspection, stripe_auto_apply, lever_auto_apply).

Upon detecting user submission:
1. Verifies confirmation URL or success DOM confirmation message.
2. Identifies matching job in jobs.db (currently in STAGED_FOR_REVIEW status).
3. Archives the submitted tailored resume into applied_jobs/<company>_<job_id>/resume.pdf.
4. Updates jobs.db status to 'APPLIED' with current applied_at timestamp.
5. Re-generates data/jobs_found_and_applied.txt dashboard summary.
"""

import sys
import time
import json
import shutil
import sqlite3
import subprocess
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Any, Optional

# Ensure project root is in sys.path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from engine.config import DB_PATH, APPLIED_JOBS_DIR, RESUMES_GENERATED_DIR
from engine.db import update_job_status, update_text_summary, get_all_jobs

APPLIED_JOBS_DIR.mkdir(parents=True, exist_ok=True)

WATCHED_TASK_SPACES = {
    "microsoft_auto_apply": "microsoft",
    "ashby_auto_apply": "ashby",
    "greenhouse_auto_apply": "greenhouse",
    "greenhouse_inspection": "greenhouse",
    "stripe_auto_apply": "stripe",
    "lever_auto_apply": "lever",
    "remote_contract_auto_apply": "mercor",
    "aiprise_auto_apply": "aiprise",
    "rippling_auto_apply": "rippling",
}

SUCCESS_PATTERNS = [
    "thank you for applying",
    "application submitted",
    "your application has been submitted",
    "thanks for submitting your application",
    "your application has been received",
    "we've received your application",
    "application received",
    "successfully submitted",
    "your application was submitted",
    "thank you for your interest",
    "2 of 2 steps done 100%",
    "application submitted on",
    "submitted on",
]

SUCCESS_URL_FRAGMENTS = [
    "confirmation",
    "submitted",
    "thanks",
    "thank-you",
    "success",
    "view-applications",
    "application-submitted",
]

def check_taskspace_submission(space_id: int) -> Dict[str, Any]:
    """
    Evaluates an ego-browser taskSpace to see if its page is on a confirmation state.
    """
    node_script = f"""
const task = await taskSpace({space_id});
const page = task.page("p1");

const url = await page.url();
const title = await page.title();

const detection = await page.evaluate((patterns) => {{
  const text = (document.body?.innerText || "").toLowerCase();
  const matched = patterns.find(p => text.includes(p));
  
  // Also check if submit button still exists
  const submitBtns = Array.from(document.querySelectorAll('button, input[type="submit"]'))
    .filter(b => {{
      const t = (b.innerText || b.value || "").toLowerCase();
      return t.includes("submit application") || t.includes("submit") || t.includes("apply now");
    }});
  
  return {{
    hasSuccessText: !!matched,
    matchedText: matched || null,
    submitButtonCount: submitBtns.length,
    bodySnippet: text.slice(0, 300)
  }};
}}, {json.dumps(SUCCESS_PATTERNS)});

console.log(JSON.stringify({{
  url,
  title,
  ...detection
}}));
"""
    try:
        proc = subprocess.run(
            ["ego-browser", "nodejs"],
            input=node_script,
            text=True,
            capture_output=True,
            timeout=15
        )
        output_text = (proc.stdout or "") + "\n" + (proc.stderr or "")
        for line in output_text.splitlines():
            line = line.strip()
            if line.startswith("{") and line.endswith("}"):
                try:
                    return json.loads(line)
                except Exception:
                    continue
    except Exception as e:
        return {"error": str(e)}

    return {"error": "No JSON output from ego-browser"}

def find_staged_job_for_space(space_name: str, current_url: str) -> Optional[Dict[str, Any]]:
    """
    Matches an ego-browser taskSpace or URL back to a STAGED_FOR_REVIEW job in jobs.db.
    """
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    c = conn.cursor()
    c.execute(
        "SELECT * FROM jobs WHERE status IN ('STAGED_FOR_REVIEW', 'EVALUATED')"
    )
    staged = [dict(r) for r in c.fetchall()]
    conn.close()

    space_company = WATCHED_TASK_SPACES.get(space_name, "").lower()

    # Match by URL or by company
    for job in staged:
        job_url = job.get("url", "").lower()
        job_company = job.get("company", "").lower()

        if current_url and (job_url in current_url.lower() or current_url.lower() in job_url):
            return job
        if space_company and space_company in job_company:
            return job

    # Fallback: check all staged
    if staged and len(staged) == 1:
        return staged[0]

    return None

def archive_applied_job(job: Dict[str, Any]) -> str:
    """
    Copies the tailored resume into applied_jobs/<company>_<job_id>/resume.pdf
    and writes metadata.json.
    """
    company_slug = "".join(c if c.isalnum() else "_" for c in job.get("company", "company")).strip("_")
    job_id_slug = "".join(c if c.isalnum() else "_" for c in job.get("job_id", "job")).strip("_")
    dest_dir = APPLIED_JOBS_DIR / f"{company_slug}_{job_id_slug}"
    dest_dir.mkdir(parents=True, exist_ok=True)

    tailored_path = job.get("tailored_resume_dir")
    resume_copied = False

    if tailored_path and Path(tailored_path).is_file():
        shutil.copy2(tailored_path, dest_dir / "resume.pdf")
        resume_copied = True
    elif tailored_path and Path(tailored_path).is_dir():
        pdfs = list(Path(tailored_path).glob("*.pdf"))
        if pdfs:
            shutil.copy2(pdfs[0], dest_dir / "resume.pdf")
            resume_copied = True

    # If not copied yet, look in master resumes
    if not resume_copied:
        for m_name in ["RESUME_1_AI_ENGINEER.pdf", "RESUME_4_GENERAL_ADARSH_JHA.pdf"]:
            m_path = PROJECT_ROOT / "master_resumes" / m_name
            if m_path.exists():
                shutil.copy2(m_path, dest_dir / "resume.pdf")
                resume_copied = True
                break

    meta = {
        "job_id": job.get("job_id"),
        "company": job.get("company"),
        "title": job.get("title"),
        "url": job.get("url"),
        "applied_at": datetime.now().isoformat(),
        "resume_archived": resume_copied,
    }
    with open(dest_dir / "metadata.json", "w", encoding="utf-8") as f:
        json.dump(meta, f, indent=2)

    return str(dest_dir)

def check_and_process_submissions() -> List[Dict[str, Any]]:
    """
    Runs a single inspection cycle across all open ego-browser taskSpaces.
    Returns list of processed/applied jobs.
    """
    # 1. Get current taskSpaces
    proc = subprocess.run(
        ["ego-browser", "nodejs", "-e", "const s = await listTaskSpaces(); console.log(JSON.stringify(s));"],
        capture_output=True,
        text=True
    )
    output_all = (proc.stdout or "") + "\n" + (proc.stderr or "")
    spaces = []
    for line in output_all.splitlines():
        line = line.strip()
        if line.startswith("[") and line.endswith("]"):
            try:
                spaces = json.loads(line)
                break
            except Exception:
                continue

    applied_results = []

    for sp in spaces:
        s_name = sp.get("name")
        s_id = sp.get("id")
        if s_name not in WATCHED_TASK_SPACES:
            continue

        result = check_taskspace_submission(s_id)
        if "error" in result:
            continue

        url = result.get("url", "").lower()
        has_success_url = any(frag in url for frag in SUCCESS_URL_FRAGMENTS)
        has_success_text = result.get("hasSuccessText", False)

        is_submitted = has_success_url or has_success_text

        if is_submitted:
            job = find_staged_job_for_space(s_name, url)
            if job:
                job_id = job["job_id"]
                company = job["company"]
                title = job["title"]
                print(f"\n🎉 [WATCHER] SUBMISSION DETECTED for {company} — {title} (ID: {job_id})!")
                print(f"    URL: {url}")
                print(f"    Confirmation: {'URL pattern match' if has_success_url else result.get('matchedText')}")

                # Archive resume
                archived_path = archive_applied_job(job)
                print(f"    Archived to: {archived_path}")

                # Update DB
                update_job_status(job_id, "APPLIED", details={"applied_at": datetime.now().isoformat(), "notes": f"Submission confirmed via ego-browser watcher ({url})"})
                print(f"    Database status updated to APPLIED.")

                applied_results.append({
                    "job_id": job_id,
                    "company": company,
                    "title": title,
                    "archived_path": archived_path
                })

    if applied_results:
        update_text_summary()

    return applied_results

def run_submission_watcher_loop(interval_sec: float = 6.0, max_cycles: Optional[int] = None):
    """
    Continuously monitors ego-browser taskSpaces for submissions.
    """
    print(f"👀 [WATCHER] Application Submission Watcher started (polling every {interval_sec}s)...")
    print(f"    Monitoring taskSpaces: {', '.join(WATCHED_TASK_SPACES.keys())}")
    print("    Press Ctrl+C to stop.\n")

    cycles = 0
    while True:
        try:
            cycles += 1
            processed = check_and_process_submissions()
            if processed:
                for p in processed:
                    print(f"    [+] Successfully tracked submission: {p['company']} ({p['job_id']})")

            if max_cycles and cycles >= max_cycles:
                break

            time.sleep(interval_sec)
        except KeyboardInterrupt:
            print("\n[!] Watcher stopped by user.")
            break
        except Exception as e:
            print(f"[!] Watcher iteration error: {e}")
            time.sleep(interval_sec)

if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Watch ego-browser task spaces for job submissions")
    parser.add_argument("--once", action="store_true", help="Run once and exit")
    parser.add_argument("--interval", type=float, default=6.0, help="Check interval in seconds")
    parser.add_argument("--cycles", type=int, help="Max cycles to run")
    args = parser.parse_args()

    if args.once:
        results = check_and_process_submissions()
        print(f"Processed {len(results)} submitted applications.")
    else:
        run_submission_watcher_loop(interval_sec=args.interval, max_cycles=args.cycles)
