#!/usr/bin/env python3
"""
Autonomous Multi-Agent Task Delegator.
Delegates job applications and portal inspections to AGY worker CLI sessions
with FULL conversation context, candidate dossier, and --dangerously-skip-permissions.
"""

import sys
import os
import re
import json
import subprocess
from datetime import datetime
from pathlib import Path
from typing import Dict, Any, Optional, List

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from engine.config import (
    CANDIDATE_NAME,
    CANDIDATE_FIRST_NAME,
    CANDIDATE_LAST_NAME,
    CANDIDATE_EMAIL,
    CANDIDATE_PERSONAL_EMAIL,
    CANDIDATE_COLLEGE_EMAIL,
    CANDIDATE_PHONE,
    CANDIDATE_PHONE_PLAIN,
    CANDIDATE_LOCATION,
    CANDIDATE_CITY,
    CANDIDATE_LINKEDIN,
    CANDIDATE_GITHUB,
    CANDIDATE_CURRENT_COMPANY,
    CANDIDATE_CURRENT_TITLE,
    ANS_COLLEGE,
    ANS_DEGREE,
    ANS_MAJOR,
    ANS_GRAD_YEAR,
    ANS_CGPA,
    CANDIDATE_HONORS,
    CANDIDATE_PRODUCTION_HIGHLIGHTS,
    CANDIDATE_RESEARCH_HIGHLIGHTS,
    CANDIDATE_TARGET_ROLES,
    CANDIDATE_MISSION_AND_GOALS,
    CANDIDATE_EXCLUSIONS,
    ANS_ALL_INDIA_LOCATIONS,
    ANS_CURRENT_CTC,
    ANS_EXPECTED_CTC,
    ANS_HOURLY_RATE_USD,
    ANS_NOTICE_PERIOD,
    ANS_EARLIEST_START_DATE,
    ANS_WORK_AUTH_INDIA,
    ANS_SPONSORSHIP_INDIA,
    get_candidate_profile_prompt_block,
    EGO_BROWSER_MAIN_PROFILE_ID,
    DATA_DIR,
    LOGS_DIR,
    assert_real_candidate_profile,
    verify_script_zero_placeholders,
    resolve_candidate_tokens
)
from engine.db import get_job_by_id, record_agent_dispatch, update_job_status

LOGS_DIR.mkdir(parents=True, exist_ok=True)

# Default parent conversation ID if none specified
PARENT_CONVERSATION_ID = "6650d8c7-9a16-4c0f-ae23-bc21971d656b"

def build_worker_prompt(
    company: str,
    title: str,
    url: str,
    job_id: str,
    location: str = "",
    submit: bool = True,
    archetype: str = "RESUME_1_AI_ENGINEER"
) -> str:
    """
    Builds an exhaustive, context-complete task assignment prompt for the AGY subagent worker.
    Includes full candidate dossier, what candidate did, what candidate wants to apply for,
    what candidate wants to do, strict exclusions, security policies, and exact completion criteria.
    """
    prompt = f"""You are an autonomous Job Application Worker Agent for candidate {CANDIDATE_NAME}.
You have been delegated the specific job assignment below. Execute it end-to-end completely and autonomously.

=============================================================================
CANDIDATE DOSSIER & CONTEXT
=============================================================================
- Name: {CANDIDATE_NAME}
- First Name: {CANDIDATE_FIRST_NAME} | Last Name: {CANDIDATE_LAST_NAME}
- Email: {CANDIDATE_PERSONAL_EMAIL} (Personal) | {CANDIDATE_COLLEGE_EMAIL} (College/Academic)
- Phone: {CANDIDATE_PHONE} (Plain digits: {CANDIDATE_PHONE_PLAIN})
- Location / Address: {CANDIDATE_LOCATION} ({CANDIDATE_CITY}, India)
- LinkedIn: {CANDIDATE_LINKEDIN}
- GitHub: {CANDIDATE_GITHUB}
- Education: {ANS_DEGREE} in {ANS_MAJOR}, {ANS_COLLEGE} ({ANS_GRAD_YEAR}, CGPA: {ANS_CGPA})
- Current Role: {CANDIDATE_CURRENT_TITLE} at {CANDIDATE_CURRENT_COMPANY} (~9 months production: Jan-May intern, Jun-present full-time)
- Browser Environment: ego-browser Profile 1 (Profile ID: {EGO_BROWSER_MAIN_PROFILE_ID})

=============================================================================
WHAT THE CANDIDATE DID (PRODUCTION & RESEARCH HIGHLIGHTS)
=============================================================================
- Academic & Exam Honors: {CANDIDATE_HONORS}
- Production Achievements at {CANDIDATE_CURRENT_COMPANY}:
  {CANDIDATE_PRODUCTION_HIGHLIGHTS}
- Deep Learning & Systems Research at {ANS_COLLEGE}:
  {CANDIDATE_RESEARCH_HIGHLIGHTS}
- Core Tech Stack: Python, Java, C++, Go, Apache Spark, AWS Glue, Kafka CDC (Debezium), Apache Hudi, Amazon Athena, Docker, Kubernetes, PyTorch, FastAPI, RAG, AWS Nova Sonic Voice AI (600ms p95), MCP (Model Context Protocol).

=============================================================================
WHAT THE CANDIDATE WANTS TO APPLY FOR (TARGET ROLES)
=============================================================================
- Target Roles: {CANDIDATE_TARGET_ROLES}
- Compensation Expectations: Current CTC {ANS_CURRENT_CTC} | Expected CTC {ANS_EXPECTED_CTC} | US/Remote Contract Hourly: {ANS_HOURLY_RATE_USD}
- Notice Period / Joining: {ANS_NOTICE_PERIOD} ({ANS_EARLIEST_START_DATE})
- Work Authorization: Indian Citizen, legally authorized in India ({ANS_WORK_AUTH_INDIA}). No visa sponsorship required in India ({ANS_SPONSORSHIP_INDIA}). Open to US remote contract/W8-BEN roles.

=============================================================================
WHAT THE CANDIDATE WANTS TO DO (ENGINEERING MISSION & PHILOSOPHY)
=============================================================================
{CANDIDATE_MISSION_AND_GOALS}

=============================================================================
HARD EXCLUSIONS & ANTI-TARGETS (NEVER APPLY TO)
=============================================================================
- {CANDIDATE_EXCLUSIONS}
- If this assigned job matches any hard exclusion, immediately abort with status SKIPPED and record the exclusion reason.

=============================================================================
LOCATION SELECTION MANDATE (CRITICAL)
=============================================================================
When encountering any location preferences (especially on Microsoft Eightfold, Ashby, Greenhouse, or any multi-select location field),
ALWAYS SELECT ALL AVAILABLE LOCATIONS IN INDIA ({ANS_ALL_INDIA_LOCATIONS}).
Do not select just one city if multiple Indian locations are allowed.

=============================================================================
SECURITY & ANTI-PLACEHOLDER MANDATE (CRITICAL)
=============================================================================
1. ABSOLUTELY ZERO PLACEHOLDERS: Every single form field MUST be filled with real candidate facts.
   Never use generic placeholders, fake dummy numbers, or test emails.
   The in-browser audit and safety circuit breaker will permanently halt if any dummy value is detected.
2. Zero PII leaks to Git: Never commit compensation figures, real phone numbers, real residential addresses, or custom cover letters to git.
3. Master Resumes in master_resumes/ are 1-page strict fit.

=============================================================================
YOUR ASSIGNED JOB TARGET
=============================================================================
- Job ID: {job_id}
- Company: {company}
- Role Title: {title}
- Location: {location or 'Remote / India'}
- Application URL: {url}
- Suggested Resume Archetype: master_resumes/{archetype}.pdf
- Submit Mode: {'SUBMIT IMMEDIATELY (Remote/Contract)' if submit else 'STAGE_AND_VALIDATE (Full-Time/On-Site)'}

=============================================================================
STEP-BY-STEP EXECUTION INSTRUCTIONS
=============================================================================
1. Review procedure cache:
   Check if data/company_apply_procedures/{company.lower()}.json exists for known fields and answers.
2. Execute application:
   - For Ashby: Use `python3 cli.py apply-ashby --url "{url}" {'--submit' if submit else ''}`
   - For Greenhouse: Use `python3 cli.py apply-greenhouse --url "{url}" {'--submit' if submit else ''}`
   - For Lever: Use `python3 cli.py apply-lever --url "{url}" {'--submit' if submit else ''}`
   - For Amazon: Use `python3 engine/amazon_apply.py --url "{url}" {'--submit' if submit else ''}`
   - For other custom portals: Use ego-browser on Profile 1, navigate to the URL, fill all fields using candidate facts, resolve custom questions, attach master_resumes/{archetype}.pdf, and submit or stage.
3. Verify on-page confirmation:
   Confirm that the form was accepted (e.g. "Thank you for applying", "Application submitted", "summary?result=success", or 0 validation errors).
4. Update Database:
   Update data/jobs.db for job_id '{job_id}':
   Set status = '{'APPLIED' if submit else 'STAGED_FOR_REVIEW'}', applied_at = datetime.now().isoformat(), and add clear confirmation notes.
5. Record Dispatch:
   Record dispatch outcome in data/jobs.db table 'agent_dispatches'.
6. Print Final Result:
   Print a single JSON line at the end:
   {{"success": true, "job_id": "{job_id}", "company": "{company}", "status": "{'APPLIED' if submit else 'STAGED_FOR_REVIEW'}"}}
"""
    return prompt.strip()


def delegate_job_to_agent(
    job_id: str,
    company: str,
    title: str,
    url: str,
    location: str = "",
    submit: bool = True,
    archetype: str = "RESUME_1_AI_ENGINEER",
    conversation_id: Optional[str] = None,
    sync: bool = False,
    timeout_sec: int = 300
) -> Dict[str, Any]:
    """
    Spawns an autonomous AGY worker with --dangerously-skip-permissions,
    injecting the complete context dossier, workspace tools, and done criteria.
    """
    assert_real_candidate_profile()

    prompt = build_worker_prompt(
        company=company,
        title=title,
        url=url,
        job_id=job_id,
        location=location,
        submit=submit,
        archetype=archetype
    )

    prompt = resolve_candidate_tokens(prompt)
    verify_script_zero_placeholders(prompt, "Agent Delegator Worker Prompt")

    convo = conversation_id or f"delegated-{job_id}-{int(datetime.now().timestamp())}"
    log_file = LOGS_DIR / f"agent_worker_{re.sub(r'[^a-zA-Z0-9_]', '_', job_id)}.log"

    import shutil
    agy_bin = shutil.which("agy") or str(Path.home() / ".local/bin/agy")

    cmd = [
        agy_bin,
        "-p", prompt,
        "--effort", "high",
        "--dangerously-skip-permissions"
    ]
    if conversation_id:
        cmd.extend(["--conversation", conversation_id])

    print(f"\n[Delegator] Spawning AGY worker for [{company}] {title} (Job ID: {job_id})")
    print(f"            Command: agy -p <full_dossier> --effort high --dangerously-skip-permissions")
    print(f"            Log output: {log_file}")

    # Record dispatch in DB
    try:
        record_agent_dispatch(
            company=company,
            job_id=job_id,
            agent_type="agy_autonomous_worker",
            conversation_id=convo,
            status="DISPATCHED",
            role_title=title,
            notes=f"Delegated via agy CLI with --dangerously-skip-permissions. Log: {log_file.name}"
        )
    except Exception as e:
        print(f"[!] Warning recording dispatch: {e}")

    if sync:
        try:
            with open(log_file, "w", encoding="utf-8") as out:
                proc = subprocess.run(
                    cmd,
                    cwd=str(PROJECT_ROOT),
                    stdout=out,
                    stderr=subprocess.STDOUT,
                    text=True,
                    timeout=timeout_sec
                )
            success = proc.returncode == 0
            return {
                "success": success,
                "job_id": job_id,
                "company": company,
                "returncode": proc.returncode,
                "log_file": str(log_file),
                "conversation_id": convo
            }
        except subprocess.TimeoutExpired:
            return {
                "success": False,
                "job_id": job_id,
                "company": company,
                "error": f"Timed out after {timeout_sec}s",
                "log_file": str(log_file)
            }
        except Exception as ex:
            return {
                "success": False,
                "job_id": job_id,
                "company": company,
                "error": str(ex),
                "log_file": str(log_file)
            }
    else:
        # Non-blocking background process
        out_handle = open(log_file, "w", encoding="utf-8")
        proc = subprocess.Popen(
            cmd,
            cwd=str(PROJECT_ROOT),
            stdout=out_handle,
            stderr=subprocess.STDOUT,
            env=os.environ.copy(),
            close_fds=True,
            start_new_session=True
        )
        return {
            "success": True,
            "job_id": job_id,
            "company": company,
            "pid": proc.pid,
            "mode": "BACKGROUND_ASYNC",
            "log_file": str(log_file),
            "conversation_id": convo
        }


def delegate_batch_jobs(jobs: List[Any], submit: bool = True, max_concurrent: int = 2) -> List[Dict[str, Any]]:
    """Delegates a list of newly found jobs to AGY worker agents."""
    results = []
    for item in jobs[:max_concurrent]:
        job = dict(item) if not isinstance(item, dict) else item
        jid = job.get("job_id", "")
        co = job.get("company", "")
        title = job.get("title", "")
        url = job.get("url", "")
        loc = job.get("location", "")
        arch = job.get("archetype", "RESUME_1_AI_ENGINEER")

        res = delegate_job_to_agent(
            job_id=jid,
            company=co,
            title=title,
            url=url,
            location=loc,
            submit=submit,
            archetype=arch,
            sync=False
        )
        results.append(res)
    return results


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Delegate job application to AGY worker")
    parser.add_argument("--job-id", required=True, help="Job ID from jobs.db")
    parser.add_argument("--submit", action="store_true", help="Submit immediately")
    parser.add_argument("--sync", action="store_true", help="Run synchronously and wait for completion")
    parser.add_argument("--convo", help="Optional conversation ID to resume")
    args = parser.parse_args()

    job = get_job_by_id(args.job_id)
    if not job:
        print(f"[-] Error: Job ID '{args.job_id}' not found in database.")
        sys.exit(1)
    job = dict(job)

    res = delegate_job_to_agent(
        job_id=job["job_id"],
        company=job["company"],
        title=job["title"],
        url=job["url"],
        location=job.get("location", ""),
        submit=args.submit,
        conversation_id=args.convo,
        sync=args.sync
    )
    print(json.dumps(res, indent=2))
