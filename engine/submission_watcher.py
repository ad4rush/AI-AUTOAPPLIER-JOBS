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
import re
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

from engine.config import DB_PATH, APPLIED_JOBS_DIR, RESUMES_GENERATED_DIR, DATA_DIR
from engine.db import update_job_status, update_text_summary, get_all_jobs

APPLIED_JOBS_DIR.mkdir(parents=True, exist_ok=True)
STAGED_REGISTRY_FILE = DATA_DIR / "staged_applications.json"

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

KNOWN_ATS_DOMAINS = [
    "greenhouse.io", "ashbyhq.com", "lever.co", "workday.com",
    "myworkdayjobs.com", "smartrecruiters.com", "icims.com",
    "darwinbox.com", "taleo.net", "brassring.com", "workable.com",
    "jobvite.com", "bamboohr.com", "breezy.hr", "careers.microsoft.com",
    "apple.com", "amazon.jobs", "google.com", "stripe.com",
    "zohorecruit.com", "zohorecruit.in", "jobs.dover.com", "dover.com",
    "himalayas.app", "weworkremotely.com"
]

SUCCESS_PATTERNS = [
    "thank you for applying",
    "thanks for applying",
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
    "application confirmation",
    "submission confirmed",
    "[submitted]",
    "[submission_confirmed]",
    "application has been sent",
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

# JavaScript injection hook that appliers inject before handing off the form
INJECTION_HOOK_SCRIPT = """
window.__job_staged = true;
window.__submission_fired = false;
function markSubmission() {
  window.__submission_fired = true;
  if (!document.title.includes("[SUBMITTED]")) {
    document.title = "[SUBMITTED] " + document.title;
  }
}
window.addEventListener("submit", markSubmission, true);
document.querySelectorAll("form").forEach(f => f.addEventListener("submit", markSubmission, true));
document.querySelectorAll("button, input[type='submit']").forEach(b => {
  const t = (b.innerText || b.value || "").toLowerCase();
  if (t.includes("submit") || t.includes("apply") || t.includes("send") || t.includes("interested")) {
    b.addEventListener("click", () => {
      setTimeout(markSubmission, 800);
    }, true);
  }
});
const origFetch = window.fetch;
if (origFetch) {
  window.fetch = async function(...args) {
    const res = await origFetch.apply(this, args);
    if (res && res.ok && args[1] && (args[1].method === "POST" || args[1].method === "PUT")) {
      markSubmission();
    }
    return res;
  };
}
const origSend = window.XMLHttpRequest?.prototype?.send;
if (origSend) {
  window.XMLHttpRequest.prototype.send = function(...args) {
    this.addEventListener("load", function() {
      if (this.status >= 200 && this.status < 300) {
        markSubmission();
      }
    });
    return origSend.apply(this, args);
  };
}
"""

def register_staged_application(
    job_id: str,
    company: str,
    title: str,
    url: str,
    resume_path: Optional[str] = None,
    task_space_name: Optional[str] = None
) -> Dict[str, Any]:
    """
    Registers an active application staging event.
    Updates SQLite status to STAGED_FOR_REVIEW and records in staged_applications.json.
    """
    entry = {
        "job_id": job_id,
        "company": company,
        "title": title,
        "url": url,
        "resume_path": resume_path or "",
        "task_space_name": task_space_name or "",
        "staged_at": datetime.now().isoformat(),
        "status": "STAGED_FOR_REVIEW"
    }

    # 1. Update SQLite
    update_job_status(job_id, "STAGED_FOR_REVIEW", {
        "applied_at": None,
        "notes": f"Staged for 1-click review in ego-browser ({task_space_name or 'portal'})"
    })

    # 2. Persist in registry
    registry = load_staged_registry()
    registry[job_id] = entry
    try:
        with open(STAGED_REGISTRY_FILE, "w", encoding="utf-8") as f:
            json.dump(registry, f, indent=2)
    except Exception:
        pass

    print(f"[+] [STAGING HOOK] Registered {company} — {title} (ID: {job_id}) as STAGED_FOR_REVIEW.")
    return entry

def load_staged_registry() -> Dict[str, Dict[str, Any]]:
    if STAGED_REGISTRY_FILE.exists():
        try:
            with open(STAGED_REGISTRY_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return {}
    return {}

def remove_from_staged_registry(job_id: str):
    registry = load_staged_registry()
    if job_id in registry:
        del registry[job_id]
        try:
            with open(STAGED_REGISTRY_FILE, "w", encoding="utf-8") as f:
                json.dump(registry, f, indent=2)
        except Exception:
            pass

def check_taskspace_submission(space_id: int) -> Dict[str, Any]:
    """
    Evaluates an ego-browser taskSpace to see if its page is on a confirmation state.
    Safely handles closed or destroyed taskSpaces without throwing unhandled exceptions.
    """
    node_script = f"""
try {{
  const task = await taskSpace({space_id});
  if (!task) {{
    console.log(JSON.stringify({{ closed: true }}));
    return;
  }}
  const page = task.page("p1");
  if (!page) {{
    console.log(JSON.stringify({{ closed: true }}));
    return;
  }}

  const url = await page.url();
  const title = await page.title();

  const detection = await page.evaluate((patterns) => {{
    const text = (document.body?.innerText || "").toLowerCase();
    const matched = patterns.find(p => text.includes(p));
    
    // Check if form submit button exists
    const submitBtns = Array.from(document.querySelectorAll('button, input[type="submit"]'))
      .filter(b => {{
        const t = (b.innerText || b.value || "").toLowerCase();
        return t.includes("submit application") || t.includes("submit") || t.includes("apply now");
      }});
    
    // Check injected staging hook
    const hookFired = !!(window.__submission_fired);

    return {{
      hasSuccessText: !!matched,
      matchedText: matched || null,
      submitButtonCount: submitBtns.length,
      hookFired: hookFired,
      bodySnippet: text.slice(0, 300)
    }};
  }}, {json.dumps(SUCCESS_PATTERNS)});

  console.log(JSON.stringify({{
    url,
    title,
    ...detection
  }}));
}} catch (err) {{
  console.log(JSON.stringify({{ closed: true, error: err.message }}));
}}
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

def find_staged_job_for_space(space_name: str, current_url: str, tab_titles: Optional[List[str]] = None) -> Optional[Dict[str, Any]]:
    """
    Matches an ego-browser taskSpace, URL, or recent tab titles back to a staged/tailored job in jobs.db.
    Works dynamically for any company taskSpace (e.g. nvidia_apply_p1, adobe_apply_p1).
    """
    conn = sqlite3.connect(DB_PATH, timeout=30.0)
    conn.execute("PRAGMA journal_mode=WAL;")
    conn.row_factory = sqlite3.Row
    c = conn.cursor()
    c.execute(
        "SELECT * FROM jobs WHERE status IN ('STAGED', 'STAGED_FOR_REVIEW', 'TAILORED', 'EVALUATED')"
    )
    staged = [dict(r) for r in c.fetchall()]
    conn.close()

    space_name_lower = space_name.lower()
    space_company = WATCHED_TASK_SPACES.get(space_name, "").lower()
    # Extract prefix if space name is formatted like <company>_apply_*
    prefix_company = space_name_lower.split("_")[0] if "_" in space_name_lower else space_name_lower
    combined_titles = " ".join(tab_titles or []).lower()
    url_lower = (current_url or "").lower()

    # Match by URL or by company or by title in open tabs
    for job in staged:
        job_url = job.get("url", "").lower()
        job_company = job.get("company", "").lower()
        job_title = job.get("title", "").lower()

        # 1. Direct URL match or substring match
        if url_lower and job_url and (job_url in url_lower or url_lower in job_url):
            return job

        # 2. Company domain match in URL (e.g. nvidia in nvidia.wd5.myworkdayjobs.com)
        if job_company and len(job_company) >= 3 and (job_company in url_lower or f"/{job_company}/" in url_lower):
            return job

        # 3. Dynamic space name match (e.g. nvidia in nvidia_apply_p1)
        if job_company and (job_company in space_name_lower or prefix_company == job_company):
            return job

        # 4. Static dictionary fallback
        if space_company and space_company in job_company:
            return job

        # 5. Tab titles match
        if combined_titles:
            if job_company and len(job_company) > 3 and job_company in combined_titles:
                return job
            clean_t = re.sub(r"[^a-z0-9]", " ", job_title).strip()
            words = [w for w in clean_t.split() if len(w) > 3][:3]
            if words and all(w in combined_titles for w in words):
                return job

    # Fallback: check all staged if only 1 exists
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
        for m_name in ["RESUME_1_AI_ENGINEER.pdf", "RESUME_4_GENERAL_ENGINEERING.pdf", "RESUME_4_GENERAL.pdf"]:
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

def check_and_process_submissions(check_emails: bool = False) -> List[Dict[str, Any]]:
    """
    Runs a single inspection cycle across all open ego-browser taskSpaces.
    Fast-paths out immediately with 0 CPU overhead if no jobs are staged for review.
    Returns list of processed/applied jobs.
    """
    # 0. Fast-path check: If no jobs are currently staged in DB, do zero work
    try:
        conn = sqlite3.connect(DB_PATH, timeout=5.0)
        c = conn.cursor()
        c.execute("SELECT count(*) FROM jobs WHERE status IN ('STAGED', 'STAGED_FOR_REVIEW')")
        staged_count = c.fetchone()[0]
        conn.close()
        if staged_count == 0:
            return []
    except Exception:
        pass

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
        try:
            s_name = sp.get("name") or ""
            s_id = sp.get("id")
            tab_titles = sp.get("recentTabTitles", [])

            # 1. Non-invasive title confirmation detection from Chromium metadata
            has_title_confirmation = False
            matched_title = ""
            for title_text in tab_titles:
                t_lower = title_text.lower()
                for p in SUCCESS_PATTERNS:
                    if p in t_lower:
                        has_title_confirmation = True
                        matched_title = title_text
                        break
                if has_title_confirmation:
                    break

            is_candidate_space = (
                s_name in WATCHED_TASK_SPACES or
                "apply" in s_name.lower() or
                "stage" in s_name.lower() or
                "job" in s_name.lower() or
                has_title_confirmation or
                any(any(portal in t.lower() for portal in ["greenhouse", "ashby", "lever", "microsoft", "workday", "smartrecruiters", "zoho", "dover", "himalaya"]) for t in tab_titles)
            )
            if not is_candidate_space:
                continue

            # 2. Try deep DOM inspection if agent has control
            result = check_taskspace_submission(s_id)
            url = result.get("url", "").lower() if result and not result.get("error") else ""
            is_known_portal = any(d in url for d in KNOWN_ATS_DOMAINS)
            has_success_url = is_known_portal and any(frag in url for frag in SUCCESS_URL_FRAGMENTS) if url else False
            has_success_text = result.get("hasSuccessText", False) if result else False
            has_hook_fired = result.get("hookFired", False) and result.get("submitButtonCount", 1) == 0 if result else False

            is_submitted = has_success_url or has_success_text or has_title_confirmation or has_hook_fired

            if is_submitted:
                job = find_staged_job_for_space(s_name, url, tab_titles=tab_titles)
                if job:
                    job_id = job["job_id"]
                    company = job["company"]
                    title = job["title"]
                    conf_src = "URL pattern" if has_success_url else ("Tab Title: " + matched_title if has_title_confirmation else ("Hook Fired" if has_hook_fired else result.get("matchedText")))
                    print(f"\n🎉 [WATCHER] SUBMISSION DETECTED for {company} — {title} (ID: {job_id})!")
                    print(f"    URL: {url or 'Detected via Chromium Tab'}")
                    print(f"    Confirmation: {conf_src}")

                    # Archive resume
                    archived_path = archive_applied_job(job)
                    print(f"    Archived to: {archived_path}")

                    # Update DB
                    update_job_status(job_id, "APPLIED", details={
                        "applied_at": datetime.now().isoformat(),
                        "notes": f"Submission confirmed via watcher ({conf_src})"
                    })
                    remove_from_staged_registry(job_id)
                    print(f"    Database status updated to APPLIED.")

                    applied_results.append({
                        "job_id": job_id,
                        "company": company,
                        "title": title,
                        "archived_path": archived_path
                    })
        except Exception as e:
            # Per-space exception isolation: never halt watcher for other portals
            print(f"[!] Warning: Watcher error checking space {sp.get('name', 'unknown')}: {e}")
            continue

    # 3. Check incoming email receipts as a foolproof backstop (only when explicitly requested)
    if check_emails:
        try:
            email_applied = check_email_confirmations_for_staged_jobs()
            if email_applied:
                applied_results.extend(email_applied)
        except Exception:
            pass

    if applied_results:
        update_text_summary()

    return applied_results

def check_email_confirmations_for_staged_jobs() -> List[Dict[str, Any]]:
    """
    Checks recent inbox emails for application receipts (Greenhouse, Ashby, Lever, Workday)
    and cross-references them against pending STAGED_FOR_REVIEW / TAILORED jobs.
    Guarantees detection even if the candidate closed their browser tab immediately after clicking submit.
    """
    conn = sqlite3.connect(DB_PATH, timeout=30.0)
    conn.execute("PRAGMA journal_mode=WAL;")
    conn.row_factory = sqlite3.Row
    c = conn.cursor()
    c.execute(
        "SELECT * FROM jobs WHERE status IN ('STAGED', 'STAGED_FOR_REVIEW', 'TAILORED')"
    )
    pending_jobs = [dict(r) for r in c.fetchall()]
    conn.close()

    if not pending_jobs:
        return []

    applied_from_email = []
    try:
        from engine.email_reader import fetch_profile_emails
        # Check both Personal (Profile 1) and College (Profile 2) inboxes
        for inbox_profile in ["personal", "college"]:
            try:
                emails_res = fetch_profile_emails(profile_key=inbox_profile, limit=10)
                emails = emails_res.get("emails", [])
                
                for email in emails:
                    subject = (email.get("subject") or "").lower()
                    sender = (email.get("sender") or "").lower()
                    body = (email.get("body_snippet") or "").lower()

                    is_receipt = any(k in subject for k in [
                        "thank you for applying", "application received", "received your application",
                        "your application to", "application confirmation", "thanks for applying",
                        "application submitted", "has been received", "confirming your application",
                        "thank you for your interest"
                    ]) or any(k in sender for k in ["greenhouse", "ashby", "lever", "myworkday", "smartrecruiters", "workday", "jobvite", "zoho", "zohorecruit", "dover", "cloudflare"])

                    if not is_receipt:
                        continue

                    for job in pending_jobs:
                        co = job.get("company", "").lower()
                        if co and len(co) >= 3 and (co in subject or co in sender or co in body):
                            job_id = job["job_id"]
                            print(f"\n🎉 [WATCHER EMAIL CONFIRMATION ({inbox_profile.upper()})] Matched {job['company']} via email receipt: '{email.get('subject')}'")
                            archived = archive_applied_job(job)
                            update_job_status(job_id, "APPLIED", details={
                                "applied_at": datetime.now().isoformat(),
                                "notes": f"Submission confirmed via {inbox_profile} email receipt: '{email.get('subject')}'"
                            })
                            remove_from_staged_registry(job_id)
                            applied_from_email.append({
                                "job_id": job_id,
                                "company": job["company"],
                                "title": job["title"],
                                "archived_path": archived,
                                "signal": f"EMAIL_RECEIPT_{inbox_profile.upper()}"
                            })
                            break
            except Exception as e_prof:
                # Isolate profile failure so personal doesn't block college or vice versa
                continue
    except Exception:
        pass

    return applied_from_email

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
