#!/usr/bin/env python3
"""
Autonomous End-to-End Application Pipeline.
Extracts the orchestration pipeline out of cli.py to eliminate circular dependencies.
"""

import sys
import subprocess
from datetime import datetime
from pathlib import Path
from typing import Dict, Any, Optional, List

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from engine.config import assert_real_candidate_profile, EGO_BROWSER_MAIN_PROFILE_ID
from engine.db import (
    init_db,
    get_job_by_id,
    get_pending_priority_jobs,
    record_agent_dispatch,
    update_job_status,
    maybe_update_text_summary,
    update_text_summary
)
from engine.scraper import run_parallel_scraper
from engine.evaluator import run_evaluation_pipeline
from engine.chatgpt_consultant import consult_ai_which_to_apply
from engine.applier import detect_ats_type
from engine.procedure_registry import dispatch_application
from engine.submission_watcher import check_and_process_submissions

def run_pipeline_cycle(
    workers: int = 6,
    limit: int = 10,
    assert_candidate: bool = True,
    auto_submit: bool = True
) -> Dict[str, Any]:
    """
    Executes one complete end-to-end pipeline cycle:
    1. Parallel Scraping (Tech giants, ATS boards, YC, Remotive)
    2. LinkedIn ATS extraction
    3. Evaluation & filtering (Location guard, experience filter)
    4. AI Consultation in ego-browser
    5. Application Dispatch & Staging
    6. Submission Watching & State archiving
    """
    if assert_candidate:
        assert_real_candidate_profile()

    print("=" * 70)
    print("RUNNING END-TO-END AUTONOMOUS JOB FINDER & APPLIER PIPELINE")
    print("=" * 70)
    init_db()

    # Step 1: Scrape & Discover (Parallel scrapers + verified remote platforms)
    print("\n[Step 1/5] Parallel Scraping & Portal Sourcing...")
    run_parallel_scraper(max_workers=workers)

    # Step 1b: LinkedIn ATS Scraper (Runs via Profile 2 session)
    try:
        from engine.linkedin_scraper import run_linkedin_pipeline
        print("\n[Step 1b/5] LinkedIn ATS Discovery & Extraction...")
        run_linkedin_pipeline(profile_id="Profile 2")
    except Exception as e:
        print(f"[!] Warning: LinkedIn pipeline error: {e}")

    # Step 1c: Remote Matched & Contract Sourcing (Runs via Profile 1 session in ego-browser)
    try:
        from engine.remote_scraper import run_remote_sourcing_pipeline
        print("\n[Step 1c/5] Remote Matched & Contract ATS Discovery (Himalayas Matches)...")
        run_remote_sourcing_pipeline()
    except Exception as e:
        print(f"[!] Warning: Remote sourcing pipeline error: {e}")

    # Step 2: Light Fast Evaluator (Seniority & Experience Filter)
    print("\n[Step 2/5] Light Evaluator (Seniority & Experience Filter)...")
    evaluated_jobs = run_evaluation_pipeline()

    apply_limit = limit or 5

    # Filter to candidate jobs that passed evaluation
    candidate_jobs = [
        j for j in evaluated_jobs
        if (j.get("priority_level") in ("CRITICAL_PRIORITY", "HIGH_PRIORITY") and j.get("match_score", 0) >= 65)
        or (j.get("priority_level") == "NORMAL" and j.get("match_score", 0) >= 60 and j.get("decision") in ("AUTO_APPLY", "STAGE"))
    ]

    # If newly evaluated jobs are fewer than apply limit, backfill from top pending EVALUATED jobs in DB
    if len(candidate_jobs) < apply_limit:
        db_pending = get_pending_priority_jobs(limit=apply_limit * 3, min_score=60)
        seen_jids = {j["job_id"] for j in candidate_jobs}
        for dj in db_pending:
            if dj["job_id"] not in seen_jids:
                candidate_jobs.append(dict(dj))
                seen_jids.add(dj["job_id"])
            if len(candidate_jobs) >= apply_limit:
                break

    print(f"\n[*] Found {len(candidate_jobs)} priority early-career / remote contract jobs.")

    # Step 3: AI Consultation in ego-browser
    approved_job_ids = {}
    if candidate_jobs:
        print("\n[Step 3/5] Programmatic AI Consultation in ego-browser...")
        ai_decisions = consult_ai_which_to_apply(candidate_jobs, profile_id=EGO_BROWSER_MAIN_PROFILE_ID)
        approved_job_ids = {d["job_id"]: d for d in ai_decisions if (d.get("apply") or d.get("should_apply"))}
        print(f"[+] AI Approved {len(approved_job_ids)} jobs for application dispatch.")

    # Step 4: Application Dispatch & Staging Flow
    print("\n[Step 4/5] Application Dispatch & Staging...")
    dispatched_count = 0

    for job in candidate_jobs:
        if dispatched_count >= apply_limit:
            break

        jid = job["job_id"]
        if approved_job_ids and jid not in approved_job_ids:
            continue

        db_job = get_job_by_id(jid)
        if not db_job:
            continue

        co = db_job["company"]
        title = db_job["title"]
        url = db_job["url"]
        loc = db_job["location"] or ""
        status = db_job["status"]

        if status in ("APPLIED", "STAGED", "STAGED_FOR_REVIEW"):
            print(f"[*] Skipping [{co}] {title} (already {status})")
            continue

        if "mercor" in co.lower() and ("grant" in title.lower() or "benchmark" in title.lower()):
            print(f"[*] Skipping [{co}] {title} (User directive: keep Mercor benchmarks staged)")
            continue

        if "openai" in co.lower():
            print(f"[*] Skipping [{co}] {title} (Ashby 180-day 5-submission limit reached across OpenAI roles)")
            continue

        is_remote = "remote" in title.lower() or "contract" in title.lower() or "global" in loc.lower() or "remote" in loc.lower()

        # Check for tailored resume or evaluate if worthy of custom resume
        resume_dir = db_job.get("tailored_resume_dir")
        resume_pdf = None
        if resume_dir and Path(resume_dir).exists():
            pdfs = list(Path(resume_dir).glob("*.pdf"))
            if pdfs:
                resume_pdf = pdfs[0]

        ai_info = approved_job_ids.get(jid, {})
        is_worthy = (
            ai_info.get("is_worthy_of_custom_resume")
            or ai_info.get("custom_resume_required")
            or ai_info.get("needs_custom_claude_tailoring")
            or any(t in co.lower() for t in ["microsoft", "google", "apple", "amazon", "openai", "stripe", "scale ai", "databricks", "barclays"])
        )

        if is_worthy and not resume_pdf:
            print(f"[*] Role [{co}] {title} evaluated as WORTHY of custom resume. Triggering Claude Sonnet LaTeX tailoring...")
            try:
                from engine.claude_tailor import tailor_and_compile_resume_with_claude
                tailor_res = tailor_and_compile_resume_with_claude(db_job)
                if tailor_res and tailor_res.get("pdf_path") and Path(tailor_res["pdf_path"]).exists():
                    resume_pdf = Path(tailor_res["pdf_path"])
                    print(f"[+] Custom resume successfully compiled: {resume_pdf.name}")
            except Exception as e:
                print(f"[!] Warning: Custom resume compilation error ({e}). Falling back to master archetype.")

        if not resume_pdf:
            archetype = ai_info.get("recommended_master_resume") or ai_info.get("archetype") or "RESUME_1_AI_ENGINEER"
            resume_pdf = PROJECT_ROOT / "master_resumes" / f"{archetype}.pdf"
            if not resume_pdf.exists():
                resume_pdf = PROJECT_ROOT / "master_resumes" / "RESUME_1_AI_ENGINEER.pdf"
            print(f"[*] Standard role (not custom-worthy): Using master archetype {resume_pdf.name}")

        ats = detect_ats_type(url)
        should_submit = auto_submit or is_remote
        print(f"\n--> Processing [{co}] {title}")
        print(f"    Portal Type: {ats} | Flow: {'Auto-Submit' if should_submit else 'Stage in ego-browser'}")

        # Dispatch application via verified procedure registry
        res = dispatch_application(company=co, url=url, resume_path=str(resume_pdf), submit=should_submit)
        success = res.get("success", False) if isinstance(res, dict) else False

        if not success:
            print(f"[*] Standard engine returned non-success. Delegating [{co}] {title} to autonomous AGY worker agent...")
            from engine.agent_delegator import delegate_job_to_agent
            del_res = delegate_job_to_agent(
                job_id=jid,
                company=co,
                title=title,
                url=url,
                location=loc,
                submit=should_submit,
                archetype=Path(resume_pdf).stem if resume_pdf else "RESUME_1_AI_ENGINEER",
                sync=False
            )
            print(f"[+] Successfully delegated to AGY worker (PID {del_res.get('pid')}). Logging to {del_res.get('log_file')}")
            update_job_status(jid, "DISPATCHED", {
                "notes": f"Delegated to autonomous AGY worker agent with --dangerously-skip-permissions. Log: {Path(del_res.get('log_file', '')).name}"
            })
        else:
            try:
                dispatch_status = "SUBMITTED" if (should_submit and success) else "STAGED_FOR_REVIEW"
                record_agent_dispatch(
                    company=co,
                    job_id=jid,
                    agent_type=f"{ats}_applier",
                    conversation_id=f"auto-dispatch-{jid}",
                    status=dispatch_status,
                    role_title=title,
                    notes=f"Automated pipeline dispatch ({ats}). Resume: {Path(resume_pdf).name if resume_pdf else 'default'}. Success: {success}"
                )
                new_db_status = "APPLIED" if (should_submit and success) else "STAGED_FOR_REVIEW"
                update_job_status(jid, new_db_status, {
                    "applied_at": datetime.now().isoformat() if (should_submit and success) else None,
                    "notes": f"{new_db_status} via automated pipeline dispatch ({ats})"
                })
            except Exception as e:
                print(f"[!] Note: Could not record agent dispatch: {e}")

        dispatched_count += 1

    # Step 5: Submission Watcher check
    print("\n[Step 5/5] Checking Submissions & Archiving...")
    check_and_process_submissions()
    maybe_update_text_summary(force=True)

    return {
        "status": "SUCCESS",
        "evaluated_count": len(evaluated_jobs),
        "candidates_count": len(candidate_jobs),
        "approved_count": len(approved_job_ids),
        "dispatched_count": dispatched_count
    }


def process_pending_jobs_queue(limit: int = 5, auto_submit: bool = True) -> List[Dict[str, Any]]:
    """
    Continuous Reactive Queue Worker:
    1. If any jobs are in DISCOVERED status, immediately runs evaluation.
    2. If any priority jobs are in EVALUATED status, immediately applies or delegates them.
    3. Runs submission watcher to archive any completed submissions.
    """
    from engine.db import get_jobs_by_status, get_pending_priority_jobs, update_job_status, record_agent_dispatch
    from engine.procedure_registry import dispatch_application
    from engine.submission_watcher import check_and_process_submissions

    # 1. Any DISCOVERED jobs? Evaluate immediately!
    discovered = get_jobs_by_status("DISCOVERED")
    if discovered:
        print(f"[*] Queue Worker: Detected {len(discovered)} newly discovered jobs. Running JEV evaluation...")
        try:
            from engine.evaluator import run_evaluation_pipeline
            run_evaluation_pipeline()
        except Exception as e:
            print(f"[!] Warning during queue evaluation: {e}")

    # 2. Any pending priority jobs in EVALUATED?
    pending_priority = get_pending_priority_jobs(limit=limit)
    if not pending_priority:
        return []

    dispatched = []
    for row in pending_priority:
        db_job = dict(row)
        jid = db_job["job_id"]
        co = db_job["company"]
        title = db_job["title"]
        url = db_job["url"]
        loc = db_job.get("location") or ""
        status = db_job.get("status")

        if status in ("APPLIED", "STAGED", "STAGED_FOR_REVIEW", "DISPATCHED"):
            continue

        if "mercor" in co.lower() and ("grant" in title.lower() or "benchmark" in title.lower()):
            continue
        if "openai" in co.lower():
            continue

        is_remote = "remote" in title.lower() or "contract" in title.lower() or "global" in loc.lower() or "remote" in loc.lower()
        should_submit = auto_submit or is_remote

        # Resume selection based on custom resume worthiness
        resume_dir = db_job.get("tailored_resume_dir")
        resume_pdf = None
        if resume_dir and Path(resume_dir).exists():
            pdfs = list(Path(resume_dir).glob("*.pdf"))
            if pdfs:
                resume_pdf = pdfs[0]

        is_worthy = (
            db_job.get("needs_custom_claude_tailoring")
            or any(t in co.lower() for t in ["microsoft", "google", "apple", "amazon", "openai", "stripe", "scale ai", "databricks", "barclays"])
        )

        if is_worthy and not resume_pdf:
            print(f"[*] [Queue Worker] [{co}] {title} is WORTHY of a custom resume. Triggering Claude Sonnet LaTeX tailoring...")
            try:
                from engine.claude_tailor import tailor_and_compile_resume_with_claude
                tailor_res = tailor_and_compile_resume_with_claude(db_job)
                if tailor_res and tailor_res.get("pdf_path") and Path(tailor_res["pdf_path"]).exists():
                    resume_pdf = Path(tailor_res["pdf_path"])
                    print(f"[+] Custom tailored resume ready: {resume_pdf.name}")
            except Exception as e:
                print(f"[!] Warning: Claude tailoring error ({e}). Falling back to master archetype.")

        if not resume_pdf:
            arch = db_job.get("archetype") or "RESUME_1_AI_ENGINEER"
            resume_pdf = PROJECT_ROOT / "master_resumes" / f"{arch}.pdf"
            if not resume_pdf.exists():
                resume_pdf = PROJECT_ROOT / "master_resumes" / "RESUME_1_AI_ENGINEER.pdf"
            print(f"[*] [Queue Worker] Standard role: Using master archetype {resume_pdf.name}")

        ats = detect_ats_type(url)
        print(f"\n[Queue Worker] Processing priority job: [{co}] {title}")
        print(f"               Portal: {ats} | Submit Mode: {should_submit}")

        res = dispatch_application(company=co, url=url, resume_path=str(resume_pdf), submit=should_submit)
        success = res.get("success", False) if isinstance(res, dict) else False

        if not success:
            print(f"[*] Standard engine returned non-success. Delegating [{co}] {title} to autonomous AGY worker...")
            from engine.agent_delegator import delegate_job_to_agent
            del_res = delegate_job_to_agent(
                job_id=jid,
                company=co,
                title=title,
                url=url,
                location=loc,
                submit=should_submit,
                archetype=Path(resume_pdf).stem,
                sync=False
            )
            update_job_status(jid, "DISPATCHED", {
                "notes": f"Delegated to autonomous AGY worker agent with --dangerously-skip-permissions. Log: {Path(del_res.get('log_file', '')).name}"
            })
            dispatched.append({"job_id": jid, "company": co, "status": "DISPATCHED_TO_AGY"})
        else:
            new_status = "APPLIED" if should_submit else "STAGED_FOR_REVIEW"
            update_job_status(jid, new_status, {
                "applied_at": datetime.now().isoformat() if should_submit else None,
                "notes": f"{new_status} via automated pipeline queue dispatch ({ats})"
            })
            dispatched.append({"job_id": jid, "company": co, "status": new_status})

    if dispatched:
        check_and_process_submissions()
        maybe_update_text_summary(force=True)

    return dispatched
