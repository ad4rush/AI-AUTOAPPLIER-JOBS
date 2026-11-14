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
from engine.company_delegator_memory import normalize_company_slug

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
    archetype: str = "RESUME_1_AI_ENGINEER",
    is_resume: bool = False,
    previous_role: str = "",
    conversation_id: str = ""
) -> str:
    """
    Builds an exhaustive, context-complete task assignment prompt for the AGY subagent worker.
    Supports both fresh assignment prompts (with full candidate dossier) and returning worker
    prompts (resuming existing company sessions with portal memory & browser state continuity).
    Mandates lifelong procedure self-improvement, SKILL.md-style procedure persistence, and
    atomic database updates for every job applied or staged.
    """
    comp_slug = normalize_company_slug(company)

    if is_resume:
        prompt = f"""You are resuming your role as the dedicated autonomous Job Application Worker for candidate {CANDIDATE_NAME} at {company}.
You previously executed applications for {company} (Previous handled role: '{previous_role or "Initial Opening"}').
A NEW job opening has just opened up at {company}! Execute this application end-to-end autonomously.

=============================================================================
NEW JOB OPENING AT {company.upper()}
=============================================================================
- Job ID: {job_id}
- Company: {company} (Company Slug: {comp_slug})
- Role Title: {title}
- Location: {location or 'Remote / India'}
- Application URL: {url}
- Suggested Resume Archetype: master_resumes/{archetype}.pdf
- Submit Mode: {'SUBMIT IMMEDIATELY (Remote/Contract)' if submit else 'STAGE_AND_VALIDATE (Full-Time/On-Site)'}

=============================================================================
REUSE YOUR ESTABLISHED CONTEXT & ADVANTAGES
=============================================================================
1. Browser & Session Continuity:
   - Reuse your existing ego-browser Profile 1 session, task space (`apply_{comp_slug}`), cookies, and authentication state for {company}.
2. Portal Architecture Memory:
   - Reuse your established memory of {company}'s ATS portal layout (Eightfold, Greenhouse, Ashby, Lever, BambooHR, Workday, etc.).
   - Read from your existing procedure file: `data/company_apply_procedures/{comp_slug}.json` or `data/company_apply_procedures/{comp_slug}/SKILL.md`.
   - Reuse the answers you previously supplied for {company}'s custom screening questions, notice period, and salary expectations.
3. Candidate Verification & Anti-Placeholder Mandate:
   - Name: {CANDIDATE_NAME} | Email: {CANDIDATE_PERSONAL_EMAIL} | Phone: {CANDIDATE_PHONE}
   - Education: {ANS_DEGREE} in {ANS_MAJOR}, {ANS_COLLEGE} ({ANS_GRAD_YEAR}, CGPA: {ANS_CGPA})
   - Current Role: {CANDIDATE_CURRENT_TITLE} at {CANDIDATE_CURRENT_COMPANY}
   - When encountering any location preferences, ALWAYS SELECT ALL AVAILABLE LOCATIONS IN INDIA ({ANS_ALL_INDIA_LOCATIONS}).
   - Absolutely 0 dummy placeholders. Real candidate facts only.

=============================================================================
SELF-IMPROVING APPLICATION PROCEDURE & LIFELONG MEMORY MANDATE (CRITICAL)
=============================================================================
You are an intelligent, self-improving AI worker. You NEVER execute an application blindly or discard learned knowledge.
You MUST record and persist your entire application procedure so that your memory compounds across every application for {company}.

1. Pre-Application Discovery & Procedure Check:
   Before opening or touching any form, check and read existing procedure memory if available:
   - Machine JSON Cache: data/company_apply_procedures/{comp_slug}.json
   - Agent Skill Doc:    data/company_apply_procedures/{comp_slug}/SKILL.md (or data/company_apply_procedures/{comp_slug}_procedure.md)
   - Universal Q&A Cache: data/company_apply_procedures/qa_cache.json
   Reuse all memorized DOM selectors, screening question answers, auth quirks, and bypass notes.

2. Post-Application Persistence & Lifelong Memory Recording (MANDATORY):
   Immediately upon staging or submitting the application, you MUST update and save the apply procedure:
   a) Machine-Readable JSON Procedure:
      - Path: data/company_apply_procedures/{comp_slug}.json
      - Must include: company, ats_platform, last_url, known_fields, selectors, question_answers, notes.
      - Execute via Python CLI helper:
        python3 -c "from engine.procedure_memory import record_company_procedure; record_company_procedure('{company}', ats_platform='<ats>', url='{url}', fields_found=['<field1>', '<field2>'], notes='<quirks, modals, datepicker tips>', task_space='apply_{comp_slug}')"

   b) Agent Skill Markdown File (same style of path as skills / SKILL.md):
      - Paths: `data/company_apply_procedures/{comp_slug}/SKILL.md` AND `data/company_apply_procedures/{comp_slug}_procedure.md`
      - Must follow standard SKILL.md format with YAML frontmatter:
        ---
        name: apply_{comp_slug}
        description: Verified autonomous apply procedure, DOM selectors, authentication, and screening answers for {company}.
        company: {company}
        ats_platform: <ats_platform>
        task_space: apply_{comp_slug}
        last_updated: <ISO_TIMESTAMP>
        ---
        # {company} Application Procedure & Portal Knowledge
        ## 1. Portal Architecture & Authentication
        - ATS Platform: <ats>
        - Primary Apply URL: {url}
        - Browser Profile: Profile 1 (Main Profile)
        - Task Space: `apply_{comp_slug}`
        - Authentication Flow: (Google OAuth / email / direct)
        ## 2. Discovered Fields & DOM Selectors
        - Input selectors, dropdown triggers, file upload selector
        ## 3. Screening Questions & Candidate Answers
        - Verified answers for notice period, salary, authorization, and essay prompts
        ## 4. Execution Quirks & Modals
        - Modals to dismiss (cookies, privacy agreements), datepicker format
        ## 5. Step-by-Step Procedure

   c) Dedicated Company Delegator Worker Memory:
      - Persistently map your conversation session to {company} so future openings return directly to you:
        python3 -c "from engine.company_delegator_memory import save_company_delegator; save_company_delegator('{company}', '{conversation_id}', job_id='{job_id}', role_title='{title}', ats_platform='<ats>', task_space_name='apply_{comp_slug}')"

=============================================================================
MANDATORY DATABASE UPDATE FOR EVERY JOB APPLIED OR STAGED (CRITICAL)
=============================================================================
Every single job you apply to or stage MUST be permanently and atomically recorded in data/jobs.db.
NO job applied or staged must ever be left unrecorded in the database.

1. Update jobs table in data/jobs.db:
   Set:
   - status: '{'APPLIED' if submit else 'STAGED_FOR_REVIEW'}'
   - applied_at: ISO timestamp (e.g. datetime.now().isoformat())
   - tailored_resume_dir: exact path to resume used ('master_resumes/{archetype}.pdf')
   - notes: detailed on-page confirmation (e.g. redirect URL, confirmation number, submission banner text, or staging status)

   Execute via Python CLI helper:
   python3 -c "from engine.db import update_job_status; from datetime import datetime; update_job_status('{job_id}', '{'APPLIED' if submit else 'STAGED_FOR_REVIEW'}', details={{'applied_at': datetime.now().isoformat(), 'tailored_resume_dir': 'master_resumes/{archetype}.pdf', 'notes': 'Application verified and confirmed on {company} portal via ego-browser Profile 1.'}}, refresh_summary=True)"

2. Re-generate Human Dashboard Summary:
   python3 -c "from engine.db import update_text_summary; update_text_summary()"

3. Record Dispatch Log:
   Ensure completion is recorded in data/jobs.db table 'agent_dispatches'.

=============================================================================
EXECUTION STEPS
=============================================================================
1. Navigate to {url} in your established task space (`apply_{comp_slug}`) on Profile 1.
2. Fill all application fields cleanly, attach master_resumes/{archetype}.pdf.
3. If Remote/Contract: Submit immediately and verify on-page confirmation.
4. If Full-time/On-site or CAPTCHA required: 100% prefill and hand off / stage in ego-browser Profile 1.
5. Save procedure memory JSON & SKILL.md, save delegator memory, and update data/jobs.db.
6. Print Final JSON line:
   {{"success": true, "job_id": "{job_id}", "company": "{company}", "status": "{'APPLIED' if submit else 'STAGED_FOR_REVIEW'}", "resumed": true}}
"""
        return prompt.strip()

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
- Company: {company} (Company Slug: {comp_slug})
- Role Title: {title}
- Location: {location or 'Remote / India'}
- Application URL: {url}
- Suggested Resume Archetype: master_resumes/{archetype}.pdf
- Submit Mode: {'SUBMIT IMMEDIATELY (Remote/Contract)' if submit else 'STAGE_AND_VALIDATE (Full-Time/On-Site)'}

=============================================================================
SELF-IMPROVING APPLICATION PROCEDURE & LIFELONG MEMORY MANDATE (CRITICAL)
=============================================================================
You are an intelligent, self-improving AI worker. You NEVER execute an application blindly or discard learned knowledge.
You MUST record and persist your entire application procedure so that future worker instances can execute identically without re-discovering or guessing.

1. Pre-Application Discovery & Procedure Check:
   Before opening or touching any form, check and read existing procedure memory if available:
   - Machine JSON Cache: data/company_apply_procedures/{comp_slug}.json
   - Agent Skill Doc:    data/company_apply_procedures/{comp_slug}/SKILL.md (or data/company_apply_procedures/{comp_slug}_procedure.md)
   - Universal Q&A Cache: data/company_apply_procedures/qa_cache.json
   Reuse all memorized DOM selectors, screening question answers, auth quirks, and bypass notes.

2. Post-Application Persistence & Lifelong Memory Recording (MANDATORY):
   Immediately upon staging or submitting the application, you MUST update and save the apply procedure:
   a) Machine-Readable JSON Procedure:
      - Path: data/company_apply_procedures/{comp_slug}.json
      - Must include: company, ats_platform, last_url, known_fields, selectors, question_answers, notes.
      - Execute via Python CLI helper:
        python3 -c "from engine.procedure_memory import record_company_procedure; record_company_procedure('{company}', ats_platform='<ats>', url='{url}', fields_found=['<field1>', '<field2>'], notes='<quirks, modals, datepicker tips>', task_space='apply_{comp_slug}')"

   b) Agent Skill Markdown File (same style of path as skills / SKILL.md):
      - Paths: `data/company_apply_procedures/{comp_slug}/SKILL.md` AND `data/company_apply_procedures/{comp_slug}_procedure.md`
      - Must follow standard SKILL.md format with YAML frontmatter:
        ---
        name: apply_{comp_slug}
        description: Verified autonomous apply procedure, DOM selectors, authentication, and screening answers for {company}.
        company: {company}
        ats_platform: <ats_platform>
        task_space: apply_{comp_slug}
        last_updated: <ISO_TIMESTAMP>
        ---
        # {company} Application Procedure & Portal Knowledge
        ## 1. Portal Architecture & Authentication
        - ATS Platform: <ats>
        - Primary Apply URL: {url}
        - Browser Profile: Profile 1 (Main Profile)
        - Task Space: `apply_{comp_slug}`
        - Authentication Flow: (Google OAuth / email / direct)
        ## 2. Discovered Fields & DOM Selectors
        - Input selectors, dropdown triggers, file upload selector
        ## 3. Screening Questions & Candidate Answers
        - Verified answers for notice period, salary, authorization, and essay prompts
        ## 4. Execution Quirks & Modals
        - Modals to dismiss (cookies, privacy agreements), datepicker format
        ## 5. Step-by-Step Procedure

   c) Dedicated Company Delegator Worker Memory:
      - Persistently map your conversation session to {company} so future openings return directly to you:
        python3 -c "from engine.company_delegator_memory import save_company_delegator; save_company_delegator('{company}', '{conversation_id}', job_id='{job_id}', role_title='{title}', ats_platform='<ats>', task_space_name='apply_{comp_slug}')"

=============================================================================
MANDATORY DATABASE UPDATE FOR EVERY JOB APPLIED OR STAGED (CRITICAL)
=============================================================================
Every single job you apply to or stage MUST be permanently and atomically recorded in data/jobs.db.
NO job applied or staged must ever be left unrecorded in the database.

1. Update jobs table in data/jobs.db:
   Set:
   - status: '{'APPLIED' if submit else 'STAGED_FOR_REVIEW'}'
   - applied_at: ISO timestamp (e.g. datetime.now().isoformat())
   - tailored_resume_dir: exact path to resume used ('master_resumes/{archetype}.pdf')
   - notes: detailed on-page confirmation (e.g. redirect URL, confirmation number, submission banner text, or staging status)

   Execute via Python CLI helper:
   python3 -c "from engine.db import update_job_status; from datetime import datetime; update_job_status('{job_id}', '{'APPLIED' if submit else 'STAGED_FOR_REVIEW'}', details={{'applied_at': datetime.now().isoformat(), 'tailored_resume_dir': 'master_resumes/{archetype}.pdf', 'notes': 'Application verified and confirmed on {company} portal via ego-browser Profile 1.'}}, refresh_summary=True)"

2. Re-generate Human Dashboard Summary:
   python3 -c "from engine.db import update_text_summary; update_text_summary()"

3. Record Dispatch Log:
   Ensure completion is recorded in data/jobs.db table 'agent_dispatches'.

=============================================================================
STEP-BY-STEP EXECUTION INSTRUCTIONS
=============================================================================
1. Review procedure cache:
   Check if data/company_apply_procedures/{comp_slug}.json or data/company_apply_procedures/{comp_slug}/SKILL.md exists for known fields and answers.
2. Execute application:
   - For Ashby: Use `python3 cli.py apply-ashby --url "{url}" {'--submit' if submit else ''}`
   - For Greenhouse: Use `python3 cli.py apply-greenhouse --url "{url}" {'--submit' if submit else ''}`
   - For Lever: Use `python3 cli.py apply-lever --url "{url}" {'--submit' if submit else ''}`
   - For Amazon: Use `python3 engine/amazon_apply.py --url "{url}" {'--submit' if submit else ''}`
   - For other custom portals (Eightfold, Workday, BambooHR, etc.): Use ego-browser on Profile 1, navigate to the URL, fill all fields using candidate facts, resolve custom questions, attach master_resumes/{archetype}.pdf, and submit or stage.
3. Verify on-page confirmation:
   Confirm that the form was accepted (e.g. "Thank you for applying", "Application submitted", "summary?result=success", or 0 validation errors).
4. Update Database:
   Update data/jobs.db for job_id '{job_id}' using the command in the MANDATORY DATABASE UPDATE section above.
5. Record Procedure & Delegator Memory:
   Update data/company_apply_procedures/{comp_slug}.json, data/company_apply_procedures/{comp_slug}/SKILL.md, and call save_company_delegator.
6. Record Dispatch:
   Record dispatch outcome in data/jobs.db table 'agent_dispatches'.
7. Print Final Result:
   Print a single JSON line at the end:
   {{"success": true, "job_id": "{job_id}", "company": "{company}", "status": "{'APPLIED' if submit else 'STAGED_FOR_REVIEW'}"}}
"""
    return prompt.strip()
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
    Spawns or resumes an autonomous AGY worker with --dangerously-skip-permissions.
    Remembers and reuses dedicated company delegator conversations across new job openings,
    preserving full portal context, task spaces, and screening question memory.
    """
    assert_real_candidate_profile()

    from engine.company_delegator_memory import (
        get_company_delegator,
        save_company_delegator,
        BRAIN_DIR
    )

    is_resume = False
    previous_role = ""

    # 1. Lookup dedicated existing conversation for this company if none provided
    if not conversation_id:
        existing = get_company_delegator(company)
        if existing and existing.get("conversation_id"):
            conversation_id = existing["conversation_id"]
            is_resume = True
            previous_role = existing.get("last_role_title", "")
            print(f"\n[Delegator:Memory] Found existing dedicated worker for '{company}' (Convo ID: {conversation_id}). Resuming session for new opening!")
        else:
            print(f"\n[Delegator:Memory] No prior worker found for '{company}'. Starting fresh dedicated worker.")

    # 2. Build context prompt (resumption vs initial dossier)
    prompt = build_worker_prompt(
        company=company,
        title=title,
        url=url,
        job_id=job_id,
        location=location,
        submit=submit,
        archetype=archetype,
        is_resume=is_resume,
        previous_role=previous_role,
        conversation_id=conversation_id or ""
    )

    prompt = resolve_candidate_tokens(prompt)
    verify_script_zero_placeholders(prompt, "Agent Delegator Worker Prompt")

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
    print(f"            Mode: {'RESUMING_CONVERSATION' if is_resume else 'FRESH_WORKER'}")
    if conversation_id:
        print(f"            Reusing Conversation: {conversation_id}")
    print(f"            Command: agy -p <assignment> --effort high --dangerously-skip-permissions {'--conversation ' + conversation_id if conversation_id else ''}")
    print(f"            Log output: {log_file}")

    # Track pre-spawn brain directories to detect new session ID if starting fresh
    before_brains = set(p.name for p in BRAIN_DIR.iterdir() if p.is_dir()) if (not is_resume and BRAIN_DIR.exists()) else set()

    convo = conversation_id or f"delegated-{job_id}-{int(datetime.now().timestamp())}"

    # Record dispatch in DB
    try:
        record_agent_dispatch(
            company=company,
            job_id=job_id,
            agent_type="agy_autonomous_worker",
            conversation_id=convo,
            status="DISPATCHED",
            role_title=title,
            notes=f"Delegated via agy CLI ({'RESUMING' if is_resume else 'FRESH'}). Log: {log_file.name}"
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

            # Detect and save new session ID if fresh
            if not is_resume and BRAIN_DIR.exists():
                after_brains = set(p.name for p in BRAIN_DIR.iterdir() if p.is_dir())
                diff = after_brains - before_brains
                if diff:
                    convo = list(diff)[0]
                    save_company_delegator(company, convo, job_id, title)
            elif is_resume and conversation_id:
                save_company_delegator(company, conversation_id, job_id, title)

            return {
                "success": success,
                "job_id": job_id,
                "company": company,
                "returncode": proc.returncode,
                "log_file": str(log_file),
                "conversation_id": convo,
                "resumed": is_resume
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

        # Detect new brain directory shortly after launch if fresh
        import time
        if not is_resume and BRAIN_DIR.exists():
            time.sleep(1.2)
            after_brains = set(p.name for p in BRAIN_DIR.iterdir() if p.is_dir())
            diff = after_brains - before_brains
            if diff:
                convo = list(diff)[0]
                save_company_delegator(company, convo, job_id, title)
        elif is_resume and conversation_id:
            save_company_delegator(company, conversation_id, job_id, title)

        return {
            "success": True,
            "job_id": job_id,
            "company": company,
            "pid": proc.pid,
            "mode": "BACKGROUND_ASYNC",
            "log_file": str(log_file),
            "conversation_id": convo,
            "resumed": is_resume
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
