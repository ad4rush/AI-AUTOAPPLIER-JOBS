---
name: job-finder-applier
description: Autonomous job hunting, resume tailoring, and multi-company auto-apply platform for Adarsh Kumar Jha (IIIT-Delhi CS & AI 2026, TBO.com AI Engineer). Executes deterministic auto-applications on Microsoft, Stripe, Ashby, Greenhouse, and Lever portals, integrates real-time ChatGPT consultation in ego-browser Profile 1, and enforces strict two-flow location and seniority filtering.
---

# Job Finder & Auto-Applier Platform Guide

## 1. System Overview & Core Purpose
This autonomous platform continuously monitors, scrapes, evaluates, dynamically tailors LaTeX resumes for, and auto-applies to top software/AI engineering positions for candidate **Adarsh Kumar Jha**.

- **Repository Root:** `/Users/adarsh/job_finder_applier`
- **CLI Entrypoint:** [`cli.py`](file:///Users/adarsh/job_finder_applier/cli.py)
- **Candidate Profile:**
  - **Full Legal Name:** Adarsh Kumar Jha | **Preferred Name:** Adarsh Jha
  - **Education:** B.Tech in Computer Science & AI from IIIT-Delhi (Graduated 2026, GPA: 8.2/10)
  - **Current Role:** AI Engineer (Production Engineering) at TBO.com (~9 months total experience: Jan-May 2026 Intern -> Jun 2026-Present Full-Time)
  - **Current Base:** Bengaluru / Delhi NCR, India; works in Gurugram at TBO.com (`Delhi / Gurgaon, India`)
  - **Current CTC:** ₹20 LPA | **Target CTC:** ₹24–30+ LPA
  - **Notice Period:** 15–30 days / Immediate joiner
  - **Work Authorization:** Indian Citizen. Legally authorized in India (Yes). No visa sponsorship needed (No).
  - **Key Credentials:** GATE 2026 CS/IT AIR 252 | JEE Mains 99.5%ile (AIR 4778) | Codeforces Specialist (`ad4rsh`) | Deep Learning Specialization
  - **Key Tech Stack:** Python, Java, C++, Apache Spark, AWS Glue, Kafka CDC (Debezium), Apache Hudi, Parquet, Amazon Athena, Docker, Kubernetes, FastAPI, PyTorch, RAG, LLM Agents.
  - **Contact & Links:** Configured via `.env` (`CANDIDATE_EMAIL`, `CANDIDATE_PHONE`, `CANDIDATE_LINKEDIN`, `CANDIDATE_GITHUB`)

---

## 2. The Strict Two-Flow Evaluation Policy

Every discovered role must pass through one of two strict operational flows in [`engine/evaluator.py`](file:///Users/adarsh/job_finder_applier/engine/evaluator.py) and [`engine/config.py`](file:///Users/adarsh/job_finder_applier/engine/config.py):

### Flow 1: India-Based Roles Only
- **Permitted Locations:** Strictly Bengaluru / Bangalore, Hyderabad, Gurgaon / Gurugram, Delhi NCR, Noida, Pune, Mumbai, Chennai.
- **Disqualified Locations:** Reject all foreign on-site roles (e.g., Redmond, San Francisco, London, Sydney, Singapore).
- **Target Seniority:** Strictly early-career (0–1 years, 0–2 years, SDE-1, SWE-1, Associate, New Grad).
- **Seniority Filter:** Reject roles requiring 3+ years of experience, Senior, Staff, Principal, Lead, or PhD.
- **Tier 1 Fast-Track:** Early career roles at Tier 1 companies (Microsoft, Stripe, OpenAI, Scale AI, Databricks) are prioritized for auto-application.

### Flow 2: Reputable Global Remote Contract Roles
- **Permitted Portals/Roles:** Global remote contract / freelance positions from reputable companies (scraped from Himalayas, WeWorkRemotely, Remotive, Ashby boards for OpenAI/Cursor/Mercor/LangChain).
- **Quality Standard:** Filter for well-funded startups or top tech firms. Reject low-pay spam and sketchy outsourcing agencies.

---

## 3. Verified Multi-Company Auto-Apply Suite

All auto-appliers run deterministically via **ego-browser** on **Profile 1 ("Main Profile")**, with zero manual DOM manipulation required.

### 3.1 Microsoft Careers (Eightfold.ai Engine)
- **File:** [`engine/microsoft_apply.py`](file:///Users/adarsh/job_finder_applier/engine/microsoft_apply.py)
- **Command:** `python3 cli.py apply-microsoft --url <JOB_ID_OR_URL> [--resume <PATH>] [--submit]`
- **Live Tested:** Microsoft Software Engineer (Commerce Platform - Hyderabad) [Job ID: `1970393557050960`]. Form validated 100% complete (`submitBtnEnabled: true, unfilledCount: 0`).

### 3.2 Stripe Careers (Greenhouse Embed Engine)
- **File:** [`engine/stripe_apply.py`](file:///Users/adarsh/job_finder_applier/engine/stripe_apply.py)
- **Command:** `python3 cli.py apply-stripe --url <TOKEN_OR_URL> [--resume <PATH>] [--submit]`
- **Live Tested:** Stripe Software Engineer (New Grad - Bangalore) [Token: `8130876`]. Form validated 100% complete (`submitBtnEnabled: true, errorsCount: 0`).

### 3.3 Ashby HQ Engine (OpenAI, Cursor, Mercor, LangChain)
- **File:** [`engine/ashby_apply.py`](file:///Users/adarsh/job_finder_applier/engine/ashby_apply.py)
- **Command:** `python3 cli.py apply-ashby --url <URL> [--resume <PATH>] [--submit]`
- **Live Tested:** OpenAI Partner AI Deployment Engineer - AWS (`https://jobs.ashbyhq.com/openai/87989505-81e5-4513-bba0-5f00bb064216`). Form validated 100% complete (`submitBtnEnabled: true, submitText: 'Submit Application'`).

### 3.4 Greenhouse Universal Engine (Scale AI, Databricks, Brex, Vercel, Anthropic)
- **File:** [`engine/greenhouse_apply.py`](file:///Users/adarsh/job_finder_applier/engine/greenhouse_apply.py)
- **Command:** `python3 cli.py apply-greenhouse --url <URL> [--company <NAME>] [--resume <PATH>] [--submit]`
- **Live Tested:** Scale AI Software Engineer (`https://job-boards.greenhouse.io/scaleai/jobs/4684808005`). Form validated 100% complete (`submitBtnEnabled: true, errorsCount: 0`).

### 3.5 Lever Engine (Palantir, Atlassian, Sentry, Benchling)
- **File:** [`engine/lever_apply.py`](file:///Users/adarsh/job_finder_applier/engine/lever_apply.py)
- **Command:** `python3 cli.py apply-lever --url <URL> [--resume <PATH>] [--submit]`
- **Live Tested:** Palantir Job Opening (`https://jobs.lever.co/palantir/6ed76ce8-4156-4b60-b120-403538bd66cd`). Form validated 100% complete (`submitBtnEnabled: true`).

### 3.6 Unified Batch Application Engine
- **Command:** `python3 cli.py apply-all [--limit N] [--auto-tailor] [--submit]`
- Automatically auto-detects platform type, checks for or generates tailored resumes, and executes verified staging/submission in sequence.

---

## 4. ChatGPT Consultation API Flow (Profile 1)

Implemented in [`engine/chatgpt_consultant.py`](file:///Users/adarsh/job_finder_applier/engine/chatgpt_consultant.py):
- **`ask_chatgpt_for_application_answers()`**: Answers custom application forms in strict JSON using the user's master profile dossier and JD.
- **`review_tailored_resume_with_chatgpt()`**: Reviews tailored LaTeX resumes, scores ATS keyword match (0–100), and outputs `READY_TO_APPLY` verdict.

---

## 5. Dynamic Resume Tailoring & Account Switching Flow

Implemented in [`engine/claude_tailor.py`](file:///Users/adarsh/job_finder_applier/engine/claude_tailor.py) and [`engine/account_rotator.py`](file:///Users/adarsh/job_finder_applier/engine/account_rotator.py):
- Claude 3.5 Sonnet generates tailored LaTeX code based on target JD and master profile.
- Multiple Claude accounts configured in `.env` (`CLAUDE_ACCOUNTS`) automatically rotate when free-tier rate limits are hit.
- Tectonic compiles XeTeX to PDF.
- Page count is strictly checked via `mdls -name kMDItemNumberOfPages`. Auto-tunes spacing if $>1$ page to guarantee **strict 1 page**.

---

## 6. CLI Command Quick Reference

| Command | Platform / Function | Example |
|---|---|---|
| `python3 cli.py init` | DB schema & environment setup | `python3 cli.py init` |
| `python3 cli.py find` | Parallel scraper across all boards | `python3 cli.py find --workers 8` |
| `python3 cli.py eval` | Run JEV matcher with strict 0-2 yr & India filters | `python3 cli.py eval --all` |
| `python3 cli.py tailor` | Tailor resumes with Claude round-robin & Tectonic | `python3 cli.py tailor --limit 3` |
| `python3 cli.py apply-microsoft` | Auto-apply to Microsoft opening (Eightfold) | `python3 cli.py apply-microsoft --url 1970393557050960` |
| `python3 cli.py apply-stripe` | Auto-apply to Stripe opening (Greenhouse Embed) | `python3 cli.py apply-stripe --url 8130876` |
| `python3 cli.py apply-ashby` | Auto-apply to Ashby openings (OpenAI, Cursor, etc.) | `python3 cli.py apply-ashby --url https://jobs.ashbyhq.com/openai/...` |
| `python3 cli.py apply-greenhouse` | Auto-apply to Greenhouse openings (Scale AI, etc.) | `python3 cli.py apply-greenhouse --url https://job-boards.greenhouse.io/...` |
| `python3 cli.py apply-lever` | Auto-apply to Lever openings (Palantir, etc.) | `python3 cli.py apply-lever --url https://jobs.lever.co/palantir/...` |
| `python3 cli.py apply-all` | Batch auto-apply across all supported boards | `python3 cli.py apply-all --limit 5` |
| `python3 cli.py status` | Print pipeline dashboard summary | `python3 cli.py status` |
| `python3 cli.py watch` | Run periodic monitoring daemon with jitter | `python3 cli.py watch --once` |
| `python3 cli.py watch-submissions` | Monitor ego-browser taskSpaces & archive submitted applications | `python3 cli.py watch-submissions --once` |

---

## 7. Master Resume Archetypes (`master_resumes/`)

Strictly 1-page XeTeX/Tectonic compiled master resumes:
1. `RESUME_1_AI_ENGINEER.pdf`: Focus on AWS Nova Sonic, RAG, prompt caching, text-to-sql, R2C, R-BERT.
2. `RESUME_2_DATA_ENGINEER.pdf`: Focus on Spark, AWS Glue, Kafka CDC, Hudi lakehouse, same-AZ cost savings ($5k/mo).
3. `RESUME_3_SWE_BACKEND.pdf`: Focus on FastAPI, Docker, Kubernetes, Custom Linux Shell/Mini-OS in C, ACID e-commerce.
4. `RESUME_4_GENERAL_ADARSH_JHA.pdf`: Generalist baseline profile.

---

## 8. Applied Jobs Archiving (`applied_jobs/`)

When applications are submitted:
- Exact submitted resume PDF is archived into `applied_jobs/<company>_<job_id>/resume.pdf`.
- `metadata.json` records confirmation timestamp and posting details.
- Database `status` updates to `APPLIED`.
