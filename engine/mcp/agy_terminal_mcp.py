#!/usr/bin/env python3
"""
Model Context Protocol (MCP) Server: AGY Terminal & Autonomous Applier Runner.
Speaks standard JSON-RPC 2.0 over stdio transport.
Exposes autonomous agent execution (agy --dangerously-skip-permissions),
ChatGPT Profile 1 queries, Claude resume tailoring, and company dispatch tracking.

CRITICAL PROTOCOL RULE:
Standard output (sys.stdout) is strictly reserved for JSON-RPC messages.
All logs, debug output, and tracebacks MUST be written to sys.stderr.
"""

import sys
import os
import json
import logging
import subprocess
import contextlib
from pathlib import Path
from typing import Dict, Any, Optional

PROJECT_ROOT = Path(os.getenv("JOB_APPLIER_ROOT", Path(__file__).resolve().parent.parent.parent)).resolve()
sys.path.insert(0, str(PROJECT_ROOT))

from engine.config import (
    CANDIDATE_NAME,
    CANDIDATE_CURRENT_COMPANY,
    CANDIDATE_CURRENT_TITLE,
    ANS_COLLEGE,
    CANDIDATE_HONORS
)

# Configure logging strictly to stderr
logging.basicConfig(
    stream=sys.stderr,
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] [mcp-agy-terminal]: %(message)s"
)
logger = logging.getLogger("mcp-agy-terminal")

TOOLS = [
    {
        "name": "spawn_agy_worker",
        "description": "Spawns an unattended AGY subagent CLI session (`agy -p ... --dangerously-skip-permissions`) in the job_finder_applier workspace to execute complex multi-step application, form inspection, or research tasks.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "task_prompt": {
                    "type": "string",
                    "description": "Clear instruction and prompt to execute with the AGY agent."
                },
                "working_dir": {
                    "type": "string",
                    "description": "Working directory (defaults to repository root).",
                    "default": str(PROJECT_ROOT)
                },
                "conversation_id": {
                    "type": "string",
                    "description": "Optional conversation ID to resume a previous conversation thread for this company."
                },
                "dangerously_skip_permissions": {
                    "type": "boolean",
                    "description": "Auto-approve all tool permission requests without prompting (default true).",
                    "default": True
                },
                "effort": {
                    "type": "string",
                    "enum": ["low", "medium", "high", "xhigh", "max"],
                    "description": "Reasoning effort level (defaults to high).",
                    "default": "high"
                },
                "timeout_sec": {
                    "type": "integer",
                    "description": "Maximum seconds to wait for agent turn (defaults to 300).",
                    "default": 300
                }
            },
            "required": ["task_prompt"]
        }
    },
    {
        "name": "consult_chatgpt",
        "description": "Directly queries the candidate's authenticated ChatGPT session in ego-browser Profile 1 for company application answers, custom pitches, or JD screening.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "prompt": {
                    "type": "string",
                    "description": "Prompt or question to ask ChatGPT."
                },
                "timeout_sec": {
                    "type": "integer",
                    "description": "Maximum execution timeout in seconds.",
                    "default": 90
                }
            },
            "required": ["prompt"]
        }
    },
    {
        "name": "generate_application_pitch",
        "description": "Asks ChatGPT in Profile 1 to generate a punchy 3-sentence application pitch grounded in candidate experience metrics.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "company": {"type": "string", "description": "Target company name."},
                "title": {"type": "string", "description": "Role title."},
                "jd": {"type": "string", "description": "Job description or relevant skills."}
            },
            "required": ["company", "title"]
        }
    },
    {
        "name": "apply_to_job",
        "description": "Executes an automated application flow for a job using its memorized procedure in `procedure_registry.py`.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "url": {"type": "string", "description": "Application URL."},
                "company": {"type": "string", "description": "Company name."},
                "submit": {"type": "boolean", "description": "Whether to auto-submit (remote contracts only).", "default": False},
                "resume_path": {"type": "string", "description": "Optional path to tailored PDF resume."}
            },
            "required": ["url"]
        }
    },
    {
        "name": "tailor_resume_claude",
        "description": "Generates a 1-page ATS LaTeX resume customized to the JD via Claude Sonnet 5.5 and compiles it to PDF via Tectonic with zero whitespace gap and zero page-2 overflow.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "job_id": {"type": "string", "description": "Job ID in database."},
                "company": {"type": "string", "description": "Company name."},
                "title": {"type": "string", "description": "Role title."}
            },
            "required": ["job_id", "company", "title"]
        }
    },
    {
        "name": "switch_browser_account",
        "description": "Opens the target service in its assigned ego-browser profile (Profile 1 for personal/contracts/ChatGPT, Profile 2 for LinkedIn/college, Default for daily workload).",
        "inputSchema": {
            "type": "object",
            "properties": {
                "service": {
                    "type": "string",
                    "description": "Service name ('chatgpt', 'mercor', 'linkedin', 'turing', 'alignerr', 'outlier', 'gmail-personal', 'gmail-college')."
                },
                "url": {"type": "string", "description": "Optional URL to open."}
            },
            "required": ["service"]
        }
    },
    {
        "name": "check_inbox_emails",
        "description": "Fetches recent emails (subject, sender, timestamp, snippet) from personal Gmail (Profile 1) or college Gmail (Profile 2).",
        "inputSchema": {
            "type": "object",
            "properties": {
                "profile": {
                    "type": "string",
                    "enum": ["personal", "college"],
                    "description": "Inbox to check."
                },
                "limit": {
                    "type": "integer",
                    "description": "Maximum number of emails to retrieve (default 5).",
                    "default": 5
                }
            },
            "required": ["profile"]
        }
    },
    {
        "name": "record_apply_procedure",
        "description": "Memorizes or updates an application procedure for a company into the engine's procedure registry.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "company": {"type": "string", "description": "Company name."},
                "domain": {"type": "string", "description": "Company domain."},
                "ats_platform": {"type": "string", "description": "ATS platform name (greenhouse, ashby, lever, workday, custom)."},
                "submission_policy": {
                    "type": "string",
                    "enum": ["AUTO_SUBMIT", "STAGE_AND_VALIDATE"],
                    "description": "Submission policy."
                },
                "notes": {"type": "string", "description": "Procedure details and question answers."}
            },
            "required": ["company", "domain", "ats_platform", "submission_policy"]
        }
    },
    {
        "name": "track_agent_dispatch",
        "description": "Records an agent dispatch into SQLite `agent_dispatches` table so subsequent roles for that company can reopen that conversation thread.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "company": {"type": "string", "description": "Target company name."},
                "conversation_id": {"type": "string", "description": "AGY or chat conversation ID."},
                "agent_type": {"type": "string", "description": "Agent type or role (e.g. master_applier, claude_tailor)."},
                "job_id": {"type": "string", "description": "Optional job ID."},
                "role_title": {"type": "string", "description": "Optional role title."},
                "status": {"type": "string", "description": "Status (ACTIVE, COMPLETED, FAILED).", "default": "ACTIVE"},
                "notes": {"type": "string", "description": "Optional notes or outcome."}
            },
            "required": ["company", "conversation_id", "agent_type"]
        }
    },
    {
        "name": "get_company_dispatches",
        "description": "Retrieves all previous agent dispatches, conversation IDs, and statuses for a target company to enable reopening prior threads.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "company": {"type": "string", "description": "Company name to search."}
            },
            "required": ["company"]
        }
    },
    {
        "name": "list_jobs",
        "description": "Lists jobs from the database filtered by status (e.g. EVALUATED, TAILORED, STAGED_FOR_REVIEW, APPLIED), priority, or company.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "status": {"type": "string", "description": "Optional status filter (e.g. EVALUATED, TAILORED, STAGED_FOR_REVIEW, APPLIED)."},
                "priority": {"type": "string", "description": "Optional priority level (CRITICAL_PRIORITY, HIGH_PRIORITY)."},
                "limit": {"type": "integer", "description": "Max jobs to return (default 20).", "default": 20}
            }
        }
    },
    {
        "name": "get_job_details",
        "description": "Retrieves complete details for a specific job from jobs.db including raw JD, scores, and application paths.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "job_id": {"type": "string", "description": "Job ID to retrieve."}
            },
            "required": ["job_id"]
        }
    },
    {
        "name": "get_daemon_status",
        "description": "Checks the 24/7 background launchd daemon status, recent activity, and submission watcher status.",
        "inputSchema": {
            "type": "object",
            "properties": {}
        }
    },
    {
        "name": "gemini_batch_answer",
        "description": "Queries the candidate's Gemini API key pool (GEMINI_KEY_1..5) in thread-safe round-robin rotation. Deterministically answers a batch of job application questions in a single sub-second JSON call (temperature=0.0), grounded in candidate master profile (Lakehouse CDC, CS & AI, Nova Sonic Voice AI, Text-to-SQL AST), and automatically persists answers into universal Q&A memory.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "questions": {
                    "type": "array",
                    "description": "List of question objects with 'id' and 'question', or list of question strings.",
                    "items": {
                        "type": "object",
                        "properties": {
                            "id": {"type": "string", "description": "Unique question or field identifier."},
                            "question": {"type": "string", "description": "Question text."}
                        },
                        "required": ["id", "question"]
                    }
                },
                "company": {
                    "type": "string",
                    "description": "Target company name (e.g. Anthropic, Stripe, GitLab)."
                },
                "job_title": {
                    "type": "string",
                    "description": "Target role title."
                },
                "jd_snippet": {
                    "type": "string",
                    "description": "Optional job description snippet for domain tailoring."
                }
            },
            "required": ["questions"]
        }
    },
    {
        "name": "evaluate_job_ai",
        "description": "Submits a full target job description to ChatGPT in Profile 1 for rigorous evaluation against candidate's master dossier. Evaluates should_apply (boolean), fit_score (0-100), custom_resume_required (strictly true only for Tier-1 or >=$75/hr contracts), and selects the optimal 1-page master resume archetype (RESUME_1_AI_ENGINEER, RESUME_2_DATA_ENGINEER, RESUME_3_SWE_BACKEND, RESUME_4_GENERAL_ENGINEERING).",
        "inputSchema": {
            "type": "object",
            "properties": {
                "company": {"type": "string", "description": "Target company name."},
                "title": {"type": "string", "description": "Target job title."},
                "jd_text": {"type": "string", "description": "Full job description text or summary."},
                "salary_info": {"type": "string", "description": "Optional stated salary or hourly rate."},
                "location": {"type": "string", "description": "Location or Remote status."}
            },
            "required": ["company", "title"]
        }
    },
    {
        "name": "find_remote_jobs",
        "description": "Autonomous Remote & Contract Job Discovery. Scrapes personalized matches from Himalayas (Profile 1), resolves outbound redirects to real employer ATS destination URLs (Greenhouse, Ashby, Manatal, Rippling, etc.), and ingests them into jobs.db.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "pages": {"type": "integer", "description": "Number of match pages to scan (default 2).", "default": 2},
                "limit": {"type": "integer", "description": "Maximum candidate URLs to resolve (default 5).", "default": 5}
            }
        }
    },
    {
        "name": "delegate_job_worker",
        "description": "Delegates an autonomous application or inspection task to an AGY CLI subagent with --dangerously-skip-permissions, complete candidate dossier, and isolated log tracking.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "job_id": {"type": "string", "description": "Job ID from database."},
                "company": {"type": "string", "description": "Target company name."},
                "title": {"type": "string", "description": "Role title."},
                "url": {"type": "string", "description": "Target application URL."},
                "location": {"type": "string", "description": "Role location or Remote."},
                "submit": {"type": "boolean", "description": "True to auto-submit (remote contracts), False to stage.", "default": True},
                "archetype": {"type": "string", "description": "Master resume archetype (default RESUME_1_AI_ENGINEER).", "default": "RESUME_1_AI_ENGINEER"}
            },
            "required": ["job_id", "company", "title", "url"]
        }
    }
]

def handle_spawn_agy_worker(args: Dict[str, Any]) -> str:
    raw_prompt = args.get("task_prompt", "")
    working_dir = args.get("working_dir", str(PROJECT_ROOT))
    convo_id = args.get("conversation_id")
    effort = args.get("effort", "high")
    timeout_sec = args.get("timeout_sec", 300)

    # Prepend full candidate context dossier if not already present
    context_prefix = (
        f"You are an autonomous AGY subagent operating for {CANDIDATE_NAME} ({ANS_COLLEGE}, {CANDIDATE_HONORS}, {CANDIDATE_CURRENT_TITLE} at {CANDIDATE_CURRENT_COMPANY}).\n"
        f"Workspace: {PROJECT_ROOT} | Ego-browser: Profile 1 | Database: data/jobs.db\n"
        f"Rules: Strict 1-page XeTeX resumes, zero PII leaks to git, auto-approve and execute.\n\n"
    )
    if CANDIDATE_NAME not in raw_prompt:
        full_prompt = context_prefix + raw_prompt
    else:
        full_prompt = raw_prompt

    cmd = ["agy", "-p", full_prompt, "--effort", effort, "--dangerously-skip-permissions"]
    if convo_id:
        cmd.extend(["--conversation", convo_id])

    logger.info(f"Spawning AGY worker: {' '.join(cmd[:5])} ... in {working_dir}")
    try:
        proc = subprocess.run(
            cmd,
            cwd=working_dir,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=timeout_sec
        )
        combined = f"STDOUT:\n{proc.stdout}\nSTDERR:\n{proc.stderr}\nEXIT CODE: {proc.returncode}"
        return combined[:15000]
    except subprocess.TimeoutExpired:
        return f"Error: AGY worker execution timed out after {timeout_sec}s."
    except Exception as e:
        return f"Error spawning AGY worker: {str(e)}"

def handle_consult_chatgpt(args: Dict[str, Any]) -> str:
    from engine.chatgpt_consultant import query_chatgpt
    prompt = args.get("prompt", "")
    timeout_sec = args.get("timeout_sec", 90)
    logger.info(f"Querying ChatGPT in Profile 1 (prompt len: {len(prompt)})...")
    res = query_chatgpt(prompt, timeout_seconds=timeout_sec)
    return res or "No response received from ChatGPT."

def handle_generate_application_pitch(args: Dict[str, Any]) -> str:
    from engine.chatgpt_consultant import generate_application_pitch
    company = args.get("company", "")
    title = args.get("title", "")
    jd = args.get("jd", "")
    logger.info(f"Generating pitch for {company} — {title}...")
    res = generate_application_pitch(company, title, jd)
    if isinstance(res, (dict, list)):
        return json.dumps(res, indent=2)
    return str(res or "Pitch generation failed.")

def handle_apply_to_job(args: Dict[str, Any]) -> str:
    url = args.get("url", "")
    company = args.get("company", "")
    submit = args.get("submit", False)
    resume = args.get("resume_path")

    cmd = ["/usr/bin/python3", str(PROJECT_ROOT / "cli.py"), "apply", "--url", url]
    if company:
        cmd.extend(["--company", company])
    if submit:
        cmd.append("--submit")
    if resume:
        cmd.extend(["--resume", resume])

    logger.info(f"Running application command: {' '.join(cmd)}")
    try:
        proc = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, timeout=120)
        return proc.stdout + "\n" + proc.stderr
    except Exception as e:
        return f"Error executing apply command: {str(e)}"

def handle_tailor_resume_claude(args: Dict[str, Any]) -> str:
    from engine.claude_tailor import generate_tailored_resume_via_claude
    from engine.db import get_job_by_id
    job_id = args.get("job_id", "")
    company = args.get("company", "")
    title = args.get("title", "")

    job = get_job_by_id(job_id)
    jd_text = ""
    if job and job["raw_jd_path"] and Path(job["raw_jd_path"]).exists():
        with open(job["raw_jd_path"], "r", encoding="utf-8") as f:
            jd_text = f.read()

    logger.info(f"Tailoring resume for {company} — {title} (Job ID: {job_id})...")
    success, msg, tex_path, pdf_path = generate_tailored_resume_via_claude(
        job_id, company, title, jd_text
    )
    return f"Success: {success}\nMessage: {msg}\nTeX: {tex_path}\nPDF: {pdf_path}"

def handle_switch_browser_account(args: Dict[str, Any]) -> str:
    from engine.account_switcher import switch_to_account_service
    service = args.get("service", "")
    url = args.get("url")
    logger.info(f"Switching browser account for service: {service}")
    res = switch_to_account_service(service, custom_url=url)
    return json.dumps(res, indent=2)

def handle_check_inbox_emails(args: Dict[str, Any]) -> str:
    from engine.email_reader import fetch_profile_emails
    profile = args.get("profile", "personal")
    limit = args.get("limit", 5)
    logger.info(f"Fetching {limit} emails from {profile} profile...")
    emails = fetch_profile_emails(profile_key=profile, limit=limit)
    return json.dumps(emails, indent=2)

def handle_record_apply_procedure(args: Dict[str, Any]) -> str:
    from engine.procedure_memory import record_company_procedure
    company = args.get("company", "")
    domain = args.get("domain", "")
    ats = args.get("ats_platform", "")
    policy = args.get("submission_policy", "STAGE_AND_VALIDATE")
    notes = args.get("notes", "")

    rec = record_company_procedure(
        company=company,
        domain=domain,
        ats_platform=ats,
        submission_policy=policy,
        notes=notes
    )
    return f"Successfully recorded procedure for {company}:\n{json.dumps(rec, indent=2)}"

def handle_track_agent_dispatch(args: Dict[str, Any]) -> str:
    from engine.db import record_agent_dispatch
    company = args.get("company", "")
    convo_id = args.get("conversation_id", "")
    agent_type = args.get("agent_type", "")
    job_id = args.get("job_id", "")
    role_title = args.get("role_title", "")
    status = args.get("status", "ACTIVE")
    notes = args.get("notes", "")

    dispatch_id = record_agent_dispatch(
        company=company,
        job_id=job_id,
        agent_type=agent_type,
        conversation_id=convo_id,
        status=status,
        role_title=role_title,
        notes=notes
    )
    return f"Recorded agent dispatch ID {dispatch_id} for company '{company}' with conversation ID '{convo_id}'."

def handle_get_company_dispatches(args: Dict[str, Any]) -> str:
    from engine.db import get_dispatches_by_company
    company = args.get("company", "")
    rows = get_dispatches_by_company(company)
    data = [dict(r) for r in rows]
    return json.dumps(data, indent=2)

def handle_list_jobs(args: Dict[str, Any]) -> str:
    from engine.db import get_all_jobs
    status_filter = args.get("status")
    priority_filter = args.get("priority")
    limit = args.get("limit", 20)
    all_jobs = get_all_jobs()
    res = []
    for j in all_jobs:
        if status_filter and j["status"] != status_filter:
            continue
        if priority_filter and j["priority_level"] != priority_filter:
            continue
        res.append({
            "job_id": j["job_id"],
            "company": j["company"],
            "title": j["title"],
            "location": j["location"],
            "status": j["status"],
            "priority": j["priority_level"],
            "match_score": j["match_score"],
            "company_tier": j["company_tier"],
            "url": j["url"]
        })
        if len(res) >= limit:
            break
    return json.dumps(res, indent=2)

def handle_get_job_details(args: Dict[str, Any]) -> str:
    from engine.db import get_job_by_id
    job_id = args.get("job_id", "")
    job = get_job_by_id(job_id)
    if not job:
        return f"Job ID '{job_id}' not found."
    data = dict(job)
    return json.dumps(data, indent=2)

def handle_get_daemon_status(args: Dict[str, Any]) -> str:
    service_label = os.getenv("LAUNCHD_SERVICE_LABEL", "com.candidate.ai_auto_applier")
    proc = subprocess.run(["launchctl", "list"], stdout=subprocess.PIPE, text=True)
    is_running = service_label in proc.stdout
    log_path = PROJECT_ROOT / "data" / "daemon_stdout.log"
    recent_logs = ""
    if log_path.exists():
        try:
            lines = log_path.read_text(encoding="utf-8").splitlines()
            recent_logs = "\n".join(lines[-20:])
        except Exception:
            pass
    return json.dumps({
        "daemon_service": service_label,
        "is_active_in_launchd": is_running,
        "recent_logs": recent_logs
    }, indent=2)

def handle_gemini_batch_answer(args: Dict[str, Any]) -> str:
    from engine.gemini_batch_client import query_questions_batch
    raw_questions = args.get("questions", [])
    company = args.get("company", "")
    job_title = args.get("job_title", "")
    jd_snippet = args.get("jd_snippet", "")

    formatted = []
    for idx, q in enumerate(raw_questions, 1):
        if isinstance(q, dict):
            formatted.append({"id": str(q.get("id", f"q_{idx}")), "question": str(q.get("question", ""))})
        elif isinstance(q, str):
            formatted.append({"id": f"q_{idx}", "question": q})

    answers = query_questions_batch(formatted, company=company, job_title=job_title, jd_snippet=jd_snippet)
    return json.dumps({
        "success": True,
        "company": company,
        "job_title": job_title,
        "total_questions": len(formatted),
        "answers": answers
    }, indent=2)

def handle_evaluate_job_ai(args: Dict[str, Any]) -> str:
    from engine.chatgpt_consultant import evaluate_job_with_chatgpt
    company = args.get("company", "")
    title = args.get("title", "")
    jd_text = args.get("jd_text", "")
    salary_info = args.get("salary_info", "")
    location = args.get("location", "")
    logger.info(f"Evaluating job with ChatGPT: {company} — {title}...")
    res = evaluate_job_with_chatgpt(
        company=company,
        title=title,
        jd_text=jd_text,
        salary_info=salary_info,
        location=location
    )
    return json.dumps(res, indent=2)

def handle_find_remote_jobs(args: Dict[str, Any]) -> str:
    from engine.remote_scraper import scrape_and_resolve_himalayas_matches
    pages = args.get("pages", 2)
    limit = args.get("limit", 5)
    logger.info(f"Finding remote jobs from Himalayas (pages={pages}, limit={limit})...")
    jobs = scrape_and_resolve_himalayas_matches(pages=pages, max_resolve=limit)
    return json.dumps({
        "success": True,
        "succeeded_count": len(jobs),
        "jobs": jobs
    }, indent=2)

def handle_delegate_job_worker(args: Dict[str, Any]) -> str:
    from engine.agent_delegator import delegate_job_to_agent
    job_id = args.get("job_id", "")
    company = args.get("company", "")
    title = args.get("title", "")
    url = args.get("url", "")
    location = args.get("location", "")
    submit = args.get("submit", True)
    archetype = args.get("archetype", "RESUME_1_AI_ENGINEER")
    logger.info(f"Delegating job {job_id} to autonomous AGY worker...")
    res = delegate_job_to_agent(
        job_id=job_id,
        company=company,
        title=title,
        url=url,
        location=location,
        submit=submit,
        archetype=archetype,
        sync=False
    )
    return json.dumps(res, indent=2)

DISPATCH_MAP = {
    "spawn_agy_worker": handle_spawn_agy_worker,
    "consult_chatgpt": handle_consult_chatgpt,
    "generate_application_pitch": handle_generate_application_pitch,
    "apply_to_job": handle_apply_to_job,
    "tailor_resume_claude": handle_tailor_resume_claude,
    "switch_browser_account": handle_switch_browser_account,
    "check_inbox_emails": handle_check_inbox_emails,
    "record_apply_procedure": handle_record_apply_procedure,
    "track_agent_dispatch": handle_track_agent_dispatch,
    "get_company_dispatches": handle_get_company_dispatches,
    "list_jobs": handle_list_jobs,
    "get_job_details": handle_get_job_details,
    "get_daemon_status": handle_get_daemon_status,
    "gemini_batch_answer": handle_gemini_batch_answer,
    "evaluate_job_ai": handle_evaluate_job_ai,
    "find_remote_jobs": handle_find_remote_jobs,
    "delegate_job_worker": handle_delegate_job_worker,
}

def send_response(response: Dict[str, Any]):
    line = json.dumps(response)
    sys.stdout.write(line + "\n")
    sys.stdout.flush()

def read_next_json_rpc_message() -> Optional[Dict[str, Any]]:
    """
    Reads the next JSON-RPC message supporting both:
    1. Line-delimited JSON (NDJSON)
    2. Header-delimited framing (Content-Length: <n>\r\n\r\n{...})
    """
    first_line = sys.stdin.readline()
    if not first_line:
        return None
    line_clean = first_line.strip()
    if not line_clean:
        return {}
    if line_clean.lower().startswith("content-length:"):
        parts = line_clean.split(":", 1)
        length = int(parts[1].strip())
        while True:
            header_line = sys.stdin.readline()
            if not header_line or header_line in ("\r\n", "\n", ""):
                break
        payload = sys.stdin.read(length)
        return json.loads(payload)
    return json.loads(line_clean)

def main():
    logger.info("Starting AGY Terminal MCP Server (dual-mode transport)...")
    while True:
        try:
            req = read_next_json_rpc_message()
            if req is None:
                break
            if not req:
                continue
        except Exception as e:
            logger.error(f"Malformed JSON received: {e}")
            continue

        method = req.get("method")
        msg_id = req.get("id")
        params = req.get("params", {})

        if method == "initialize":
            send_response({
                "jsonrpc": "2.0",
                "id": msg_id,
                "result": {
                    "protocolVersion": "2024-11-05",
                    "capabilities": {
                        "tools": {}
                    },
                    "serverInfo": {
                        "name": "job-applier-terminal",
                        "version": "1.0.0"
                    }
                }
            })
        elif method == "notifications/initialized":
            logger.info("Client initialization acknowledged.")
        elif method == "tools/list":
            send_response({
                "jsonrpc": "2.0",
                "id": msg_id,
                "result": {
                    "tools": TOOLS
                }
            })
        elif method == "tools/call":
            tool_name = params.get("name")
            tool_args = params.get("arguments", {})
            handler = DISPATCH_MAP.get(tool_name)
            if not handler:
                send_response({
                    "jsonrpc": "2.0",
                    "id": msg_id,
                    "error": {
                        "code": -32601,
                        "message": f"Method or tool '{tool_name}' not found"
                    }
                })
            else:
                try:
                    with contextlib.redirect_stdout(sys.stderr):
                        res_raw = handler(tool_args)
                    if isinstance(res_raw, (dict, list)):
                        res_text = json.dumps(res_raw, indent=2)
                    elif not isinstance(res_raw, str):
                        res_text = str(res_raw)
                    else:
                        res_text = res_raw

                    send_response({
                        "jsonrpc": "2.0",
                        "id": msg_id,
                        "result": {
                            "content": [
                                {
                                    "type": "text",
                                    "text": res_text
                                }
                            ]
                        }
                    })
                except Exception as e:
                    logger.exception(f"Error executing tool {tool_name}: {e}")
                    send_response({
                        "jsonrpc": "2.0",
                        "id": msg_id,
                        "result": {
                            "content": [
                                {
                                    "type": "text",
                                    "text": f"Tool execution failed: {str(e)}"
                                }
                            ],
                            "isError": True
                        }
                    })
        elif method == "ping":
            send_response({"jsonrpc": "2.0", "id": msg_id, "result": {}})
        else:
            if msg_id is not None:
                send_response({
                    "jsonrpc": "2.0",
                    "id": msg_id,
                    "error": {
                        "code": -32601,
                        "message": f"Unhandled method '{method}'"
                    }
                })

if __name__ == "__main__":
    main()
