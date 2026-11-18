#!/usr/bin/env python3
"""
Autonomous Quota-Aware Batch Runner for High-Priority Tech Giants.
- Strictly deploys workers ONLY when the active account has sufficient credits (>= 15%).
- Intelligently rotates across vaulted AGY OAuth accounts when credits run low.
- If all accounts are depleted, calculates exact refill timestamp (e.g. 05:45 IST) and enters a smart scheduled sleep.
- Filters exclusively for Big Companies / Tier-1 Tech Giants with high match scores (>= 70).
- Enforces MAX_CONCURRENT = 5, 15-minute worker timeouts, and strict on-page submit confirmations.
"""

import sys
import os
import re
import time
import json
import sqlite3
import subprocess
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, Any, List, Optional

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from engine.config import (
    CANDIDATE_NAME,
    CANDIDATE_EMAIL,
    CANDIDATE_PERSONAL_EMAIL,
    assert_real_candidate_profile,
    DATA_DIR,
    LOGS_DIR
)
from engine.db import get_job_by_id, update_job_status, update_text_summary
from engine.quota_manager import (
    check_quota,
    ensure_quota_or_rotate,
    list_vaulted_accounts,
    switch_to_account,
    get_active_account_email,
    ensure_remote_control_account
)
from engine.agent_delegator import delegate_job_to_agent
from engine.dedup import check_application

DB_PATH = DATA_DIR / "jobs.db"
MAX_CONCURRENT_WORKERS = 5
DEFAULT_WORKER_TIMEOUT = 900.0  # 15 minutes
LAUNCH_STAGGER_SEC = 10.0
MIN_CREDIT_PERCENT = 15

# Tier-1 and Top-Tier Target Companies
BIG_COMPANY_PATTERNS = [
    r"microsoft", r"google", r"apple", r"amazon", r"stripe", r"meta",
    r"barclays", r"caterpillar", r"bain", r"ibm", r"supabase", r"canonical",
    r"gitlab", r"airbnb", r"atlassian", r"snowflake", r"mongodb", r"palantir",
    r"scale\s*ai", r"databricks", r"turing", r"outlier", r"alignerr",
    r"dataannotation", r"anthropic", r"cisco", r"oracle", r"adobe", r"air\s*arabia"
]


def is_big_company(company_name: str) -> bool:
    """Checks if the company matches the high-priority Tech Giant list."""
    if not company_name:
        return False
    c_lower = company_name.lower().strip()
    return any(re.search(pat, c_lower) for pat in BIG_COMPANY_PATTERNS)


def get_top_priority_jobs(min_score: int = 70, limit: int = 15) -> List[Dict[str, Any]]:
    """
    Selects high-match score, big-company jobs from data/jobs.db that are EVALUATED
    and have not yet been applied to or closed. Filters out duplicate company+title postings.
    """
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    c = conn.cursor()

    # Pre-fetch existing applied jobs to prevent duplicates
    c.execute("SELECT company, title, canonical_hash FROM jobs WHERE status IN ('APPLIED', 'CLOSED')")
    applied_keys = set()
    for r in c.fetchall():
        co_s = re.sub(r'[^a-zA-Z0-9]', '', (r['company'] or '').lower())
        ti_s = re.sub(r'[^a-zA-Z0-9]', '', (r['title'] or '').lower())
        applied_keys.add((co_s, ti_s))
        if r['canonical_hash']:
            applied_keys.add(r['canonical_hash'])

    query = """
    SELECT job_id, company, title, match_score, company_tier, url, source, canonical_hash
    FROM jobs
    WHERE status = 'EVALUATED' AND match_score >= ?
      AND job_id NOT IN (SELECT job_id FROM apply_claims WHERE state = 'SUBMITTED')
    ORDER BY match_score DESC
    """
    c.execute(query, (min_score,))
    rows = c.fetchall()
    conn.close()

    big_jobs = []
    other_jobs = []

    for r in rows:
        job = dict(r)
        co_s = re.sub(r'[^a-zA-Z0-9]', '', (job['company'] or '').lower())
        ti_s = re.sub(r'[^a-zA-Z0-9]', '', (job['title'] or '').lower())
        c_hash = job.get('canonical_hash')

        if (co_s, ti_s) in applied_keys or (c_hash and c_hash in applied_keys):
            continue

        # Strict multi-layer dedup check
        decision = check_application(
            company=job.get("company", ""),
            title=job.get("title", ""),
            url=job.get("url", ""),
            job_id=job.get("job_id", ""),
            delegating=True
        )
        if not decision.allowed:
            if decision.reason == "DUPLICATE":
                try:
                    update_job_status(
                        job["job_id"],
                        "APPLIED",
                        details={"notes": f"Dedup sync: {decision.detail}"},
                        refresh_summary=False
                    )
                except Exception:
                    pass
            continue

        if is_big_company(job["company"]):
            big_jobs.append(job)
        else:
            other_jobs.append(job)

    # Big companies first, then highest match scores
    selected = (big_jobs + other_jobs)[:limit]
    return selected


def run_quota_aware_cycle(
    min_score: int = 70,
    max_jobs: int = 10,
    submit: bool = True,
    auto_sleep_until_refill: bool = False
) -> Dict[str, Any]:
    """
    Executes a quota-aware application run:
    1. Audits current credits via `/usage`.
    2. Rotates accounts if credits < 15%.
    3. If all depleted, either sleeps until refill or exits cleanly with refill countdown.
    4. Deploys up to MAX_CONCURRENT_WORKERS (capped at 5) with 15m timeout.
    """
    assert_real_candidate_profile()

    print("\n" + "=" * 75)
    print("🚀 INITIALIZING QUOTA-AWARE BIG-COMPANY RUNNER")
    print("=" * 75)

    # 1. Quota Check & Intelligent Account Rotation
    quota_res = ensure_quota_or_rotate(min_pct=MIN_CREDIT_PERCENT)
    if not quota_res.get("can_deploy"):
        refill_str = quota_res.get("earliest_refill_time_str", "Unknown")
        refill_sec = quota_res.get("earliest_refill_seconds", 0)
        mins = refill_sec // 60
        secs = refill_sec % 60

        print(f"\n[!] INSUFFICIENT CREDITS: {quota_res['message']}")
        print(f"[*] Earliest Quota Refill: {refill_str} (in {mins}m {secs}s)")

        if auto_sleep_until_refill and refill_sec > 0:
            print(f"[*] Auto-sleep requested. System entering low-power sleep for {mins}m {secs}s...")
            time.sleep(refill_sec + 15)  # Sleep until refill + 15s buffer
            print("[+] Quota refill time reached! Waking up system and re-checking credits...")
            return run_quota_aware_cycle(min_score, max_jobs, submit, auto_sleep_until_refill=False)
        else:
            return {
                "success": False,
                "status": "QUOTA_EXHAUSTED",
                "earliest_refill": refill_str,
                "seconds_to_refill": refill_sec,
                "account": quota_res.get("account")
            }

    active_email = quota_res.get("account")
    credit_pct = quota_res.get("gemini_5h_pct")
    print(f"[+] Active Account: {active_email} (Available Gemini Credits: {credit_pct}%)")

    # 2. Select Jobs
    target_jobs = get_top_priority_jobs(min_score=min_score, limit=max_jobs)
    if not target_jobs:
        print("[*] No high-priority jobs currently pending application in jobs.db.")
        return {"success": True, "deployed": 0, "status": "NO_JOBS_PENDING"}

    print(f"[*] Selected {len(target_jobs)} top-match jobs for application:")
    for j in target_jobs:
        print(f"    - [{j['match_score']}] {j['company']} — {j['title']} (URL: {j['url'][:60]})")

    # 3. Rate-Limited Dispatch Queue (Max 5 concurrent)
    active_workers: Dict[str, Dict[str, Any]] = {}
    job_queue = list(target_jobs)
    completed_jobs = []

    print(f"\n[*] Launching batch queue (MAX_CONCURRENT={MAX_CONCURRENT_WORKERS}, TIMEOUT={DEFAULT_WORKER_TIMEOUT}s)...")

    while job_queue or active_workers:
        # Fill available slots up to MAX_CONCURRENT_WORKERS
        while len(active_workers) < MAX_CONCURRENT_WORKERS and job_queue:
            job = job_queue.pop(0)
            jid = job["job_id"]
            co = job["company"]
            title = job["title"]
            url = job["url"]

            # Launch stagger
            if active_workers:
                time.sleep(LAUNCH_STAGGER_SEC)

            print(f"\n[*] Spawning dedicated worker: [{co}] {title} (Job ID: {jid})")
            dispatch_res = delegate_job_to_agent(
                company=co,
                title=title,
                url=url,
                job_id=jid,
                submit=submit,
                sync=False
            )

            if dispatch_res.get("success") and "pid" in dispatch_res:
                pid = dispatch_res["pid"]
                active_workers[jid] = {
                    "pid": pid,
                    "company": co,
                    "title": title,
                    "start_time": time.time(),
                    "log_file": dispatch_res.get("log_file"),
                    "job_id": jid
                }
                print(f"[+] Worker live: PID {pid} for [{co}] {title}")
            else:
                print(f"[!] Failed to spawn worker for [{co}]: {dispatch_res.get('error')}")

        time.sleep(5.0)

        # Monitor active workers
        now = time.time()
        for jid in list(active_workers.keys()):
            w = active_workers[jid]
            pid = w["pid"]
            elapsed = now - w["start_time"]
            co = w["company"]

            # Check if process is still running or zombie
            is_running = True
            try:
                res_pid, _ = os.waitpid(pid, os.WNOHANG)
                if res_pid == pid:
                    is_running = False
                elif res_pid == 0:
                    is_running = True
            except ChildProcessError:
                try:
                    os.kill(pid, 0)
                    state_out = subprocess.check_output(["ps", "-o", "state=", "-p", str(pid)], text=True).strip()
                    if state_out.startswith("Z"):
                        is_running = False
                    else:
                        is_running = True
                except Exception:
                    is_running = False
            except OSError:
                is_running = False

            if not is_running:
                print(f"[+] Worker for [{co}] finished naturally after {int(elapsed)}s.")
                completed_jobs.append(jid)
                del active_workers[jid]
            elif elapsed > DEFAULT_WORKER_TIMEOUT:
                print(f"[!] Worker for [{co}] timed out after {int(elapsed)}s. Terminating PID {pid}...")
                try:
                    os.kill(pid, 15)  # SIGTERM
                except Exception:
                    pass
                completed_jobs.append(jid)
                del active_workers[jid]

    print("\n" + "=" * 75)
    print(f"🏁 BATCH CYCLE COMPLETE: {len(completed_jobs)} jobs processed.")
    print("=" * 75)

    update_text_summary()
    # Always restore Remote Control account
    ensure_remote_control_account()
    return {
        "success": True,
        "completed_count": len(completed_jobs),
        "account_used": active_email
    }


def run_continuous_applier(
    min_score: int = 70,
    batch_size: int = 5,
    submit: bool = True
):
    """
    Continuously applies to high-match score jobs until all target jobs are applied.
    Automatically rotates accounts when credits fall below 15%, auto-sleeps across refill
    windows when all accounts are depleted, and wakes up to resume applying until completion.
    Always restores the primary account for Remote Control during sleeps and between batches.
    """
    print("\n" + "=" * 75)
    print("🔁 STARTING CONTINUOUS AUTONOMOUS APPLIER")
    print(f"[*] Filters: Match Score >= {min_score} | Batch Size: {batch_size} | Auto-Submit: {submit}")
    print("=" * 75)

    cycle = 1
    while True:
        pending = get_top_priority_jobs(min_score=min_score, limit=1)
        if not pending:
            print(f"\n🎉 [COMPLETE] No more pending EVALUATED jobs with match score >= {min_score} in jobs.db!")
            break

        print(f"\n[ContinuousApplier] --- Starting Application Cycle #{cycle} ---")
        try:
            res = run_quota_aware_cycle(
                min_score=min_score,
                max_jobs=batch_size,
                submit=submit,
                auto_sleep_until_refill=True
            )
            print(f"[ContinuousApplier] Cycle #{cycle} result: {res}")
            if res and res.get("status") == "QUOTA_EXHAUSTED":
                wait_sec = max(60, res.get("seconds_to_refill", 3600))
                print(f"[ContinuousApplier] All accounts depleted. Sleeping for {wait_sec // 60}m {wait_sec % 60}s until refill at {res.get('earliest_refill')}...")
                time.sleep(wait_sec + 10)
        except Exception as e:
            print(f"[ContinuousApplier] Cycle #{cycle} error: {e}")
            time.sleep(10)
        finally:
            ensure_remote_control_account()

        cycle += 1
        time.sleep(5)


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Quota-Aware Big-Company Batch Runner")
    parser.add_argument("--min-score", type=int, default=70, help="Minimum match score threshold (default: 70)")
    parser.add_argument("--limit", type=int, default=10, help="Max jobs to process (default: 10)")
    parser.add_argument("--submit", action="store_true", default=True, help="Auto-submit applications")
    parser.add_argument("--auto-sleep", action="store_true", help="Auto-sleep until refill time if credits low")
    parser.add_argument("--continuous", action="store_true", help="Run continuously until all qualified jobs are applied")

    args = parser.parse_args()
    if args.continuous:
        run_continuous_applier(
            min_score=args.min_score,
            batch_size=args.limit,
            submit=args.submit
        )
    else:
        run_quota_aware_cycle(
            min_score=args.min_score,
            max_jobs=args.limit,
            submit=args.submit,
            auto_sleep_until_refill=args.auto_sleep
        )
