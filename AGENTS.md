# AGENTS.md — Autonomous Agent Directives for Job Finder & Applier

This file defines the core operating instructions and behavioral protocols for any autonomous AI agent (including AGY CLI agents run via `agy --dangerously-skip-permissions` or subagents) executing inside this repository.

## 1. Operating Environment & Workspaces
- **Project Directory:** `/Users/adarsh/job_finder_applier`
- **CLI Commands:** Use `/usr/bin/python3 cli.py <command>` or `python3 cli.py <command>`
- **Database:** `data/jobs.db` (SQLite)
- **Active Browser:** ego-browser (ego-lite) running on macOS

## 2. Browser Profile Routing Matrix
Whenever you automate websites or check status, ALWAYS route to the correct profile:
- **`Profile 1` ("Main Account" / `CANDIDATE_PERSONAL_EMAIL` from `.env`):**
  - ChatGPT (`chatgpt.com`)
  - Mercor (`work.mercor.com`)
  - Turing (`turing.com`)
  - Alignerr (`app.alignerr.com`)
  - Outlier (`outlier.ai`)
  - DataAnnotation (`dataannotation.tech`)
  - Microsoft Careers (`apply.careers.microsoft.com`)
  - Personal Gmail (`mail.google.com`)
- **`Profile 2` ("College Profile" / `CANDIDATE_COLLEGE_EMAIL` from `.env`):**
  - LinkedIn (`linkedin.com/jobs`)
  - College Gmail (`mail.google.com`)
  - Overleaf LaTeX Web Editor (`overleaf.com`)
  - Academic & Research Portals
- **`Default` ("Daily Workload" / `job_applier_workload`):**
  - General scrapers (Ashby, Greenhouse, Lever)
  - Daily pipeline runs

## 3. Candidate Information & Credential Safety (STRICT)
- **Local-Only Resumes (100% Gitignored):** `master_resumes/` and `master_resume/` are strictly local to the machine and must NEVER be tracked in git or pushed to GitHub. The GitHub repository contains only clean engine code.
- **Local Master Resumes Contain 100% Real Credentials:** On the local machine, `master_resumes/*.tex` and their compiled PDFs (`RESUME_1_AI_ENGINEER.pdf`, etc.) are pre-compiled with the candidate's real credentials loaded dynamically from `.env`.
- **Zero Dummy Placeholders Mandate:** Dummy placeholders (`Candidate Name`, `5550199000`, `+1-555-0199`, `candidate@example.com`, `Tech City`, `username`) are STRICTLY FORBIDDEN from ever appearing in any form submission, resume, cover letter, API payload, or cached procedure.
- **Triple-Layer Anti-Placeholder Circuit Breakers:**
  1. **Layer 1 (Import & Pre-Apply Assertion):** Every apply engine imports and calls `assert_real_candidate_profile()` to verify that `.env` and `config.py` have real candidate values loaded and 0 placeholders.
  2. **Layer 2 (Pre-Dispatch Script Audit):** Every generated browser script passes through `verify_script_zero_placeholders(script, context)` before being written or executed in ego-browser.
  3. **Layer 3 (In-Browser DOM Audit):** Every form automation script executes an in-browser `placeholderAudit` via `page.evaluate()` scanning all `input`, `textarea`, and `select` values for forbidden placeholder tokens before validation or submission. If any placeholder is found, execution immediately aborts with a critical error.
- **Mandatory Runtime Dynamic Loading:** All candidate context dynamically loads at runtime from `.env` via `engine.config` (e.g. `CANDIDATE_NAME`, `CANDIDATE_EMAIL`, `CANDIDATE_PHONE`, `CANDIDATE_CURRENT_COMPANY`, `ANS_COLLEGE`, `get_candidate_profile_prompt_block()`). Future agents must NEVER reintroduce static placeholder fallbacks.
- **Pre-Push Security Auditing:** Always verify zero personal PII leaks (`git grep -i "<real_name>" engine/`) prior to committing. Never push `.env` to remote repositories.
- Run `python3 cli.py check-profile` to verify that active candidate credentials are 100% loaded and all circuit breakers pass.

## 4. Master Resumes & Tailoring Policy
The repository contains 4 pre-compiled, gold-standard specialization resumes in `master_resumes/`:
1. `RESUME_1_AI_ENGINEER.tex`: AI / GenAI, LLMs, Agents, RAG, PyTorch.
2. `RESUME_2_DATA_ENGINEER.tex`: Data Platform, Spark, Glue, Kafka CDC, Hudi, Lakehouse.
3. `RESUME_3_SWE_BACKEND.tex`: Backend SWE, Distributed Systems, FastAPI, Go, Microservices.
4. `RESUME_4_GENERAL_ENGINEERING.tex`: General SDE, Algorithms, CS fundamentals.

### Rules for Resumes:
- **Strict 1-Page Layout:** Every resume must compile to EXACTLY 1 page.
- **Zero Whitespace Gaps:** Content must fill 95-100% of the single page. Zero gap at bottom.
- **Zero Page-2 Overflow:** If it spills to page 2 by even 1 line, it is rejected.
- **When to Tailor:** Only tailor a new resume using Claude Sonnet 3.5 (`python3 cli.py tailor-claude`) if the company is a Tier-1 tech giant (Microsoft, Google, Apple, Amazon, OpenAI, Stripe, Scale AI, Databricks, Barclays, Anthropic, Meta) or >=$75/hr / >=₹30 LPA role. Otherwise, use the gold master resume archetype.

## 5. ChatGPT Consultation & Memory Priming
ChatGPT serves as the high-speed reasoning engine and application copilot across ego-browser profiles:
- **One-Time Memory Priming Mandate:** ChatGPT profiles (`Profile 1`, `Default`, `Profile 2`) are primed **ONCE** with the candidate's complete master profile dossier (`master_resume/MASTER_PROFILE.md`) to retain candidate context permanently in memory (`chatgpt.com` native account memory).
- Subsequent prompts must **NOT** redundantly re-paste the entire resume or master dossier; agents simply reference the memorized profile anchor (using `get_candidate_profile_prompt_block()` for concise runtime anchors).
- To verify or re-prime ChatGPT profiles, run: `python3 cli.py prime-chatgpt` (or `--force`).
- **To screen candidates or evaluate whole JDs:**
  - Use `python3 cli.py consult-chatgpt --prompt "<prompt>"`
  - Or evaluate a whole JD: `python3 cli.py consult-chatgpt --company "<co>" --title "<title>" --jd "<path_or_text>"`
  - Or generate a pitch: `python3 cli.py generate-pitch --company <co> --title <title>`
- Never guess custom application questions when ChatGPT can answer using the candidate's memorized master dossier.

## 6. Multi-Select Location Rule (All-India Mandate)
- **Multi-Select India Coverage:** Whenever applying to any job (especially on Microsoft Eightfold portal, Ashby, Greenhouse, Lever, etc.) where location selection supports multi-select options, agents MUST select **ALL** available locations in India:
  - Bengaluru / Bangalore
  - Hyderabad
  - Noida
  - Gurugram / Gurgaon
  - Pune
  - Mumbai
  - Delhi / NCR
  - Chennai
  - Kolkata
  - India (All Locations / Remote)
- Never select only a single city if multiple Indian locations can be checked simultaneously.

## 7. Apply Procedures & Memorization
Every time you apply or encounter a new portal:
- Check existing procedures: `python3 cli.py show-procedure --company <co>`
- Record new procedures: `python3 cli.py record-procedure --company <co> --ats <ats> --policy <policy>`
- Submission Policy:
  - **Remote Contracts:** `AUTO_SUBMIT` (safe to auto-submit).
  - **India Full-Time:** `STAGE_AND_VALIDATE` (fill 100%, stage in ego-browser, let candidate click final submit).

## 8. Tracking Agent Dispatches & Conversation IDs
- Record every company dispatch into SQLite:
  `python3 cli.py record-dispatch --company "<company>" --convo "<conversation_id>" --agent "<agent_type>" --role "<role>" --status "ACTIVE"`
- When a new role for a company arrives in the future, check prior dispatches:
  `python3 cli.py list-dispatches --company "<company>"`
- Reopen prior conversation threads using `agy --conversation <conversation_id>` so previous company context is preserved.
