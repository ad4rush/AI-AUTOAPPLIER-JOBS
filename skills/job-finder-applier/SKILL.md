---
name: job-finder-applier
description: Autonomous job hunting, resume tailoring, and multi-company auto-apply platform. Executes deterministic auto-applications on Microsoft, Stripe, Ashby, Greenhouse, and Lever portals, integrates real-time ChatGPT consultation in ego-browser Profile 1, Claude Sonnet 3.5 resume tailoring, MCP terminal agent runner, and persistent 24/7 daemon watcher.
---

# Master Job Finder, Tailorer & Auto-Applier Platform Guide

## 1. System Overview & Core Architecture

This autonomous platform continuously monitors, scrapes, evaluates, dynamically tailors LaTeX resumes for, and auto-applies to top software and AI engineering positions for the candidate.

- **Repository Root:** `/Users/adarsh/job_finder_applier`
- **CLI Entrypoint:** [`cli.py`](file:///Users/adarsh/job_finder_applier/cli.py)
- **Database:** SQLite at [`data/jobs.db`](file:///Users/adarsh/job_finder_applier/data/jobs.db) with WAL mode enabled.
- **Persistent Daemon:** macOS `launchd` service `com.adarsh.ai_auto_applier` running 24/7 via `~/Library/LaunchAgents/com.adarsh.ai_auto_applier.plist`.
- **MCP Server:** [`engine/mcp/agy_terminal_mcp.py`](file:///Users/adarsh/job_finder_applier/engine/mcp/agy_terminal_mcp.py) registered in `~/.gemini/config/mcp_config.json`.

### Non-Negotiable Operational Policies:
1. **Zero Credential Hardcoding:** All candidate details (name, email, phone, LinkedIn, GitHub, city, CTC) dynamically resolve from `.env` via `engine/config.py`. Never hardcode candidate data in scripts or templates. Never push `.env` to remote GitHub.
2. **Two-Tier Submission Policy:**
   - **Remote Contracts / Freelance (Himalayas, Mercor, Turing, Alignerr, Outlier):** Approved for immediate **`AUTO_SUBMIT`**.
   - **Full-Time India Roles (Microsoft, Stripe, Barclays, Scale AI, Databricks, Tier-1):** Enforce **`STAGE_AND_VALIDATE`**. The engine fills 100% of the form and uploads the tailored resume into an active ego-browser taskSpace, leaving the final 1-click submit button enabled for user review.
3. **Submission Watcher:** The 24/7 daemon checks ego-browser every 10 seconds. When the user clicks submit, it detects the confirmation URL/DOM, archives the exact submitted resume to `applied_jobs/`, and updates the SQLite status to `APPLIED`.

---

## 2. Ego-Browser Profiles & Jargon Matrix

Ego-browser (ego-lite) maintains dedicated Chromium profiles to isolate logins and avoid re-authentication prompts:

| Profile Identifier | User Jargon / Account | Intended Services & Portals |
|---|---|---|
| **`Profile 1`** | **"Main Account" / "Personal Profile"** (`CANDIDATE_PERSONAL_EMAIL` in `.env`) | ChatGPT (`chatgpt.com`), Mercor, DataAnnotation Tech, Turing, Alignerr, Outlier, Microsoft Careers, Personal Gmail, Amazon, Stripe. |
| **`Profile 2`** | **"College Profile"** (`CANDIDATE_COLLEGE_EMAIL` in `.env`) | LinkedIn (`linkedin.com/jobs`), College Gmail, Overleaf LaTeX Editor (`overleaf.com`), Academic / University applications, Research portals. |
| **`Default`** | **"Daily Workload"** (`job_applier_workload`) | High-volume ATS scrapers (Greenhouse, Ashby, Lever), non-authenticated career boards, daily batch staging. |

### CLI Profile Commands:
```bash
# List all services and their assigned profiles
python3 cli.py list-accounts

# Open a service directly in its assigned profile
python3 cli.py switch-account --service chatgpt
python3 cli.py switch-account --service mercor
python3 cli.py switch-account --service linkedin
python3 cli.py switch-account --service personal_gmail
python3 cli.py switch-account --service college_gmail

# Check recent emails from an inbox
python3 cli.py check-emails --profile personal --limit 5
python3 cli.py check-emails --profile college --limit 5
```

---

## 3. Master Resumes & Specialization Archetypes

All master templates are stored in [`master_resumes/`](file:///Users/adarsh/job_finder_applier/master_resumes) and compile strictly to **exactly 1 page** via Tectonic XeTeX:

### 3.1 The 4 Specialization Archetypes
1. **`RESUME_1_AI_ENGINEER.tex`** (`master_resumes/RESUME_1_AI_ENGINEER.tex`):
   - **Domain:** AI Engineering, GenAI, LLM Systems, Multi-Agent Orchestration, RAG.
   - **Key Focus:** AWS Nova Sonic voice AI agent (p95 <600ms), Lambda prompt caching (70%+ cost savings, 57% review drop), Text-to-SQL MCP engine on Athena, PyTorch document intelligence (OCR/LoRA 8-bit), R-BERT fine-tuning (6 F1 points).
2. **`RESUME_2_DATA_ENGINEER.tex`** (`master_resumes/RESUME_2_DATA_ENGINEER.tex`):
   - **Domain:** Data Platform, Distributed Lakehouse, Near-Real-Time CDC & ETL/ELT.
   - **Key Focus:** Apache Spark, AWS Glue, Kafka CDC (Debezium), Apache Hudi, Parquet, billions of records, Zero-KTLO automation (94% to 99.8% Glue reliability, $300/day savings), Same-AZ Kafka routing ($5,000+/month saved).
3. **`RESUME_3_SWE_BACKEND.tex`** (`master_resumes/RESUME_3_SWE_BACKEND.tex`):
   - **Domain:** Backend Software Engineering, High-Throughput Microservices, Distributed Systems.
   - **Key Focus:** FastAPI REST APIs, Go/Python microservices, Docker, Kubernetes telemetry (MTTD cut by 40%), Neo4j knowledge graph, ACID transactions, PostgreSQL, Redis caching.
4. **`RESUME_4_GENERAL_ENGINEERING.tex`** (`master_resumes/RESUME_4_GENERAL_ENGINEERING.tex`):
   - **Domain:** General Software Engineering, Core Algorithms, Full-Stack Foundation.
   - **Key Focus:** Full-stack development, CS fundamentals, competitive programming, and engineering foundation.

### 3.2 Master Candidate Dossier
- **Path:** [`master_resume/MASTER_PROFILE.md`](file:///Users/adarsh/job_finder_applier/master_resume/MASTER_PROFILE.md)
- Contains complete verified metrics, numbers, KAM note details, grant amounts, and comprehensive technical tools.

### 3.3 Tailoring Policy (When to Tailor vs Direct Use)
- **Only tailor a new resume when:**
  1. The role is a Tier-1 company FTE position (Microsoft, Stripe, OpenAI, Scale AI, Databricks, Barclays, Google, etc.).
  2. The role is a high-suitability, well-funded remote contract role.
- **Otherwise:** Pick the best matching master specialization archetype directly (`RESUME_1_AI_ENGINEER.tex` through `RESUME_4_GENERAL_ENGINEERING.tex`), dynamically inject candidate credentials from `.env`, and compile to PDF via Tectonic.

### 3.4 Claude Sonnet 3.5 Tailoring Prompt Guidelines
When tailoring via Claude Sonnet 3.5:
- **Strict 1-Page Vertical Density:** The content must fill 95% to 100% of the single page vertically.
- **ZERO Whitespace Gaps:** Absolutely no awkward empty gaps at the bottom.
- **ZERO Page-2 Spillover:** Overflow onto page 2 by even 1 line is a failure.
- **Heavy Metric Bolding:** Bold every quantified metric, number, percentage, and dollar figure (`\textbf{...}`).
- **Tool Keyword Bolding:** Bold high-leverage frameworks matching the JD.
- **TeX Escaping:** Always escape `\&`, `\%`, `\$`.

```bash
# Tailor a resume using Claude Sonnet 3.5
python3 cli.py tailor-claude --company Inngest --job-id inngest_distributed_systems_eng
```

---

## 4. ChatGPT Consultation Engine (Profile 1)

The platform queries the candidate's authenticated ChatGPT session in **Profile 1** (Personal Profile) to screen jobs and generate punchy, metric-grounded application answers:

- **Codepath:** [`engine/chatgpt_consultant.py`](file:///Users/adarsh/job_finder_applier/engine/chatgpt_consultant.py)
- **Key Functions:**
  - `query_chatgpt(prompt, timeout_sec)`: General query against live ChatGPT composer.
  - `generate_application_pitch(company, title, jd)`: Generates 3-sentence application pitch.
  - `ask_chatgpt_for_application_answers(form_questions, company, title, jd)`: Generates strict JSON form answers.

```bash
# Consult ChatGPT from CLI
python3 cli.py consult-chatgpt --prompt "What are the 3 strongest points in candidate profile for an Inngest Distributed Systems Engineer role?"

# Generate custom pitch
python3 cli.py generate-pitch --company Inngest --title "Distributed Systems Engineer"
```

---

## 5. Procedure Memorization Registry

The engine memorizes each company's exact application procedure, ATS engine, authentication quirks, and custom question answers:

- **Codepath:** [`engine/procedure_registry.py`](file:///Users/adarsh/job_finder_applier/engine/procedure_registry.py)
- **Commands:**
```bash
# List all memorized company procedures
python3 cli.py list-procedures

# View procedure details for a company
python3 cli.py show-procedure --company Microsoft
python3 cli.py show-procedure --company Stripe

# Record or update an application procedure
python3 cli.py record-procedure \
  --company "Inngest" \
  --ats "ashby" \
  --policy "STAGE_AND_VALIDATE" \
  --archetype "RESUME_3_SWE_BACKEND" \
  --notes "FastAPI, distributed queues, Event-driven background jobs"
```

---

## 6. Agent Dispatch & Conversation Thread Tracking

Whenever an agent (AGY subagent, Claude tailor, or browser worker) works on a company's role, the conversation ID is tracked in SQLite table `agent_dispatches` in [`data/jobs.db`](file:///Users/adarsh/job_finder_applier/data/jobs.db):

- **Purpose:** When subsequent roles for that same company appear in the future, the agent can query prior dispatches and resume that exact conversation thread (`agy --conversation <id>`).

```bash
# Record an agent dispatch
python3 cli.py record-dispatch \
  --company "Inngest" \
  --convo "inngest-session-4410" \
  --agent "ashby_applier" \
  --role "Distributed Systems Engineer" \
  --status "ACTIVE" \
  --notes "Staged in taskSpace p1, waiting for user submit"

# List previous dispatches for a company
python3 cli.py list-dispatches --company Inngest
python3 cli.py list-dispatches --limit 20
```

---

## 7. AGY Terminal MCP Server

The MCP server exposes autonomous agent execution, ChatGPT consultation, Claude tailoring, and procedure dispatch tools to Antigravity agents:

- **Script:** [`engine/mcp/agy_terminal_mcp.py`](file:///Users/adarsh/job_finder_applier/engine/mcp/agy_terminal_mcp.py)
- **Configuration:** [`/Users/adarsh/.gemini/config/mcp_config.json`](file:///Users/adarsh/.gemini/config/mcp_config.json)
- **Stdio Transport:** Speaks JSON-RPC 2.0. Standard output is strictly reserved for JSON-RPC messages; all logs write to `sys.stderr`.

### Available MCP Tools:
1. `spawn_agy_worker`: Spawns an unattended AGY subagent (`agy -p ... --dangerously-skip-permissions`) in `/Users/adarsh/job_finder_applier`. Supports `--conversation <id>` to resume company threads.
2. `consult_chatgpt`: Direct query to candidate's authenticated ChatGPT session in Profile 1.
3. `generate_application_pitch`: Generates 3-sentence application pitch via ChatGPT.
4. `apply_to_job`: Executes automated application flow using memorized procedure.
5. `tailor_resume_claude`: Generates 1-page ATS LaTeX resume via Claude Sonnet 3.5 and compiles via Tectonic.
6. `switch_browser_account`: Opens target service in designated profile (`Profile 1`, `Profile 2`, `Default`).
7. `check_inbox_emails`: Reads recent emails from personal or college Gmail.
8. `record_apply_procedure`: Memorizes new company application procedure in registry.
9. `track_agent_dispatch`: Records agent dispatch and conversation ID into `agent_dispatches`.
10. `get_company_dispatches`: Queries prior conversation IDs for a company.

---

## 8. Startup Persistence (`launchd`)

The autonomous watcher and scraper daemon runs persistently via macOS `launchd`:

- **Plist Location:** `~/Library/LaunchAgents/com.adarsh.ai_auto_applier.plist`
- **Configuration:** `RunAtLoad=true`, `KeepAlive=true`.
- **Startup Command:** `/usr/bin/python3 /Users/adarsh/job_finder_applier/cli.py daemon --interval 4.5 --jitter 0.75 --watcher-interval 10.0`
- **Stdout Log:** [`data/daemon_stdout.log`](file:///Users/adarsh/job_finder_applier/data/daemon_stdout.log)
- **Stderr Log:** [`data/daemon_stderr.log`](file:///Users/adarsh/job_finder_applier/data/daemon_stderr.log)

```bash
# Verify daemon status
launchctl list | grep adarsh

# Reload daemon if needed
launchctl unload ~/Library/LaunchAgents/com.adarsh.ai_auto_applier.plist
launchctl load -w ~/Library/LaunchAgents/com.adarsh.ai_auto_applier.plist
```
