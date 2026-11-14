#!/usr/bin/env python3
"""
Autonomous Batch Applier for LinkedIn Openings
Iterates through all unapplied LinkedIn jobs in jobs.db and executes direct submission
(--submit, no staging required) in Profile 2 (College Identity: Adarsh Jha, IIIT-Delhi).
"""

import sys
import time
import re
from pathlib import Path
from datetime import datetime

# Add project root to sys.path
BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR))

from engine.db import get_db_connection, update_job_status
from engine.linkedin_apply import apply_to_linkedin_job
from engine.config import EGO_BROWSER_COLLEGE_PROFILE_ID, assert_real_candidate_profile

def run_batch_linkedin_apply(limit: int = 50, delay_sec: int = 4):
    assert_real_candidate_profile()

    conn = get_db_connection()
    c = conn.cursor()

    # Query target jobs: prioritize linkedin_easy_apply source first, then linkedin_ats with direct view URLs
    c.execute("""
        SELECT job_id, company, title, url, source, status
        FROM jobs
        WHERE url LIKE 'https://www.linkedin.com/jobs/view/%'
          AND status NOT IN ('APPLIED', 'CLOSED', 'REJECTED')
        ORDER BY 
          CASE WHEN source = 'linkedin_easy_apply' THEN 0 ELSE 1 END,
          created_at DESC
        LIMIT ?;
    """, (limit,))
    jobs = [dict(row) for row in c.fetchall()]
    conn.close()

    print(f"==================================================================")
    print(f"[*] AUTONOMOUS LINKEDIN BATCH APPLIER (DIRECT SUBMIT MODE)")
    print(f"[*] Profile: {EGO_BROWSER_COLLEGE_PROFILE_ID} (College Identity: Adarsh Jha, IIIT-Delhi)")
    print(f"[*] Total target openings queued: {len(jobs)}")
    print(f"==================================================================\n")

    if not jobs:
        print("[*] No pending LinkedIn jobs found in jobs.db. All are applied or closed!")
        return

    applied_count = 0
    external_count = 0
    already_count = 0
    error_count = 0

    for idx, j in enumerate(jobs, 1):
        job_id = j["job_id"]
        company = j["company"]
        title = j["title"]
        url = j["url"]
        src = j["source"]

        print(f"\n------------------------------------------------------------------")
        print(f"[{idx}/{len(jobs)}] Processing: {company} — {title}")
        print(f"URL: {url} | Source: {src}")
        print(f"------------------------------------------------------------------")

        try:
            res = apply_to_linkedin_job(
                url_or_id=url,
                company_name=company,
                submit=True,
                profile_id=EGO_BROWSER_COLLEGE_PROFILE_ID,
                job_id_db=job_id
            )

            if res.get("submitted"):
                applied_count += 1
                if res.get("alreadyApplied"):
                    already_count += 1
                    print(f"[+] Confirmed ALREADY APPLIED on LinkedIn for {company} — marked APPLIED.")
                else:
                    print(f"[+] Successfully SUBMITTED live application for {company} — {title}!")
            elif not res.get("isEasyApply", True):
                external_count += 1
                print(f"[-] Skipped: Role requires external company ATS ({res.get('error')}).")
                # Update status in db to indicate external ATS needed
                update_job_status(
                    job_id=job_id,
                    status="SKIPPED",
                    details={"notes": f"[LinkedIn Scraper] External ATS redirect required: {res.get('error')}"},
                    refresh_summary=False
                )
            else:
                error_count += 1
                print(f"[!] Application did not reach submission: {res.get('error')}")

        except Exception as e:
            error_count += 1
            print(f"[!] Unexpected error applying to {company}: {e}")

        # Polite pacing between browser actions
        if idx < len(jobs):
            print(f"[*] Cooling down for {delay_sec}s before next application...")
            time.sleep(delay_sec)

    print(f"\n==================================================================")
    print(f"[*] BATCH RUN COMPLETE:")
    print(f"    - Total Processed: {len(jobs)}")
    print(f"    - Successfully Submitted / Confirmed Applied: {applied_count}")
    print(f"    - External ATS Redirects (Skipped): {external_count}")
    print(f"    - Errors / Incomplete: {error_count}")
    print(f"==================================================================")

if __name__ == "__main__":
    lim = int(sys.argv[1]) if len(sys.argv) > 1 else 30
    run_batch_linkedin_apply(limit=lim)
