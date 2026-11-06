# Autonomous Job Finder, Tailorer & Applier Platform

An autonomous, multi-tier job discovery, AI matching (JEV), dynamic Claude LaTeX resume tailoring, referral generation, and auto-apply execution engine designed for high-scale tech applications.

---

## 1. Directory Structure Map

```
/Users/adarsh/job_finder_applier/
├── README.md                            # Comprehensive architectural documentation & operational guide
├── cli.py                               # Master CLI orchestrator (find, eval, tailor, apply, pipeline, status)
├── master_resume/                       # Master source of truth for candidate qualifications
│   ├── MASTER_PROFILE.md                # Exhaustive dossier: every project, metric, achievement, and skill
│   ├── overleaf_source/                 # Original extracted Overleaf workspace (all 22 versions preserved intact)
│   └── templates/                       # Base LaTeX templates, apMod.sty, and graphical branding assets
├── data/                                # State persistence, idempotency, and logs
│   ├── jobs.db                          # SQLite database (deduplication, state machine, metrics)
│   ├── jobs_found_and_applied.txt       # Real-time human-readable tracker across all statuses
│   ├── raw_jobs/                        # Daily raw job dumps categorized by date
│   │   └── YYYY-MM-DD/                  # e.g., raw_jobs/2026-11-01/<company>_<job_id>.json
│   └── applied_jobs/                    # Permanent archive of submitted applications & tailored PDFs
│       └── <company>_<job_id>/          # Contains application_status.json and submitted PDF
├── resumes_generated/                   # Tailored resumes synthesized per job posting
│   └── <company>_<job_id>/              # Individual workspace for each tailored position:
│       ├── resume_<company>_<id>.tex    # Generated custom LaTeX source code
│       ├── resume_<company>_<id>.pdf    # Compiled crisp 1-page ATS PDF
│       ├── metadata.json                # Job metadata, compilation logs, keyword matches
│       ├── tailoring_prompt.txt         # Exact prompt dispatched to Claude
│       └── run_claude.js                # Browser automation script used for generation
└── engine/                              # Core engineering modules
    ├── __init__.py
    ├── config.py                        # Company tiers, candidate metadata, account credentials, paths
    ├── db.py                            # SQLite connection, indexing, schema, state transitions, text export
    ├── scraper.py                       # Parallel multi-board scraper (Greenhouse, Lever, Ashby, LinkedIn)
    ├── evaluator.py                     # JEV (Job Evaluation), skill taxonomy matching, priority scoring
    ├── claude_tailor.py                 # Claude browser controller, account rotation, LaTeX synthesis
    ├── latex_compiler.py                # Local offline Tectonic compiler
    ├── applier.py                       # ATS detector, auto-fill form filler, file upload, manual fallback
    └── referral_drafter.py              # LinkedIn invite notes (<=300 chars) & 1st-degree referral pitches
```

---

## 2. Feasibility Assessment & Technical Verification

### 2.1 Auto-Apply Feasibility via Ego-Browser
- **Greenhouse / Lever / Ashby Portals:** **High Feasibility.** These ATS platforms have consistent DOM structures (`#first_name`, `#last_name`, `#email`, `#phone`, `input[type="file"]`, `urls[LinkedIn]`). Ego-browser easily automates DOM population and handles file uploads via `page.waitForFileChooser` and `chooser.setFiles(pdf_path)`.
- **Workday / Custom Portals:** **Assisted Feasibility.** Workday requires multi-step account creation, email verification codes, and multi-page wizards. The engine auto-detects these portals, auto-fills standard fields, and if anti-bot challenges or deep authentication are required, marks the job as `MANUAL_APPLY_NOTIFIED` and prepares an instant 1-click package with the tailored resume PDF.
- **Anti-Bot & CAPTCHA Resilience:** When Cloudflare Turnstile or CAPTCHAs are detected, the system safely falls back without crashing, logs the event, and packages the application for rapid 1-click user submission.

### 2.2 Claude Dynamic Resume Tailoring & 4-Account Rotation
- **User Trust Alignment:** Adarsh explicitly prioritizes Claude for dynamic resume generation.
- **Account Pool:** Multi-account rotation pool configured via `.env` (`CLAUDE_ACCOUNTS`) to automatically cycle accounts when free-tier rate limits are reached.
- **Dynamic Rotation Protocol:** When Claude detects that an account has depleted its usage window:
  1. It triggers sign-out from `https://claude.ai/login`.
  2. Clicks "Continue with Google".
  3. Selects the next account from the circular list using `div[data-identifier="..."]`.
  4. Clicks "Continue" on the Google consent popup.
  5. Automatically resumes tailoring on `https://claude.ai/new`.

### 2.3 Local Offline LaTeX Compilation
- Powered by `tectonic` (installed at `/opt/homebrew/bin/tectonic`).
- Standalone, lightning-fast XeTeX engine that compiles tailored resumes directly to PDF in under **1 second** with zero external cloud dependencies.

---

## 3. Deduplication & Idempotency Strategy

1. **Canonical Hash Fingerprinting:**
   - Every posting is fingerprinted using a SHA-256 hash:
     $$\text{canonical\_hash} = \text{SHA-256}(\text{company} + \text{title} + \text{clean\_url})$$
   - Guaranteed deduplication across scrapers and scheduled runs.
2. **State Machine Lifecycle in SQLite (`data/jobs.db`):**
   - `DISCOVERED`: Ingested into database, raw JD saved in daily snapshot.
   - `EVALUATED`: Scored via JEV (0-100), tiered (Tier 1 / 2 / 3), priority assigned.
   - `SKIPPED`: Filtered out (Tier 3 company or score < 50%).
   - `TAILORED`: 1-page custom LaTeX generated and compiled to PDF in `resumes_generated/`.
   - `REFERRAL_DRAFTED`: LinkedIn invite note (<300 chars) & 1st-degree referral pitch ready.
   - `APPLYING`: Auto-apply workflow dispatched in ego-browser.
   - `APPLIED`: Application submitted, archived to `data/applied_jobs/`.
   - `MANUAL_APPLY_NOTIFIED`: Custom form/CAPTCHA detected, tailored resume ready for user.

---

## 4. Candidate Positioning & Company Tiering (JEV)

- **Candidate:** Adarsh Kumar Jha, AI Engineer (Production Engineering) at TBO.com (Travel Boutique Online).
- **Core Strengths:**
  - Lakehouse at scale: Apache Spark, AWS Glue (94% to 99.8% reliability, $300/day savings), Kafka CDC (Debezium), Apache Hudi, Amazon Athena, $5,000+/mo cross-AZ savings.
  - Production GenAI: Low-latency conversational AI (AWS Nova Sonic, 600ms p95 latency), ontology-grounded Text-to-SQL agent, Claude MCP server, Lambda prompt caching (70%+ cost reduction).
  - Academic & Competitive: GATE 2026 AIR 252 (CS/IT), JEE Mains 99.5 percentile (AIR 4778), Codeforces Specialist.
- **Company Tiers:**
  - **Tier 1 (Priority):** Databricks, Anthropic, Google, Microsoft, Apple, NVIDIA, Meta, OpenAI, Snowflake, Uber, Stripe, Amazon, Cisco, Salesforce, Zomato, Meesho, Swiggy, Flipkart, Cred, Razorpay, etc.
  - **Tier 2 (Target):** High-growth scaleups (Ramp, Brex, Notion, Figma, Glean, Pinecone, Modal, Vercel, Supabase, etc.).
  - **Tier 3 (Skip / Low Priority):** Companies below current compensation/scale or mismatched stacks.

---

## 5. Master Resume Source & Preservation

- **Overleaf Snapshot:** The entire Overleaf project (`66a0fa6d9d8dbb5ba3b706a9`) was downloaded via read-only browser session and safely extracted to `master_resume/overleaf_source/`.
- **Integrity Guarantee:** Zero modifications were made to the remote Overleaf workspace. The candidate's `Main Profile` in ego-browser remains completely untouched.
- **Master Dossier:** `master_resume/MASTER_PROFILE.md` contains every metric, architecture, and project from all 22 versions.

---

## 6. How to Use the CLI

```bash
# Initialize database and environment
python3 cli.py init

# 1. Scrape new postings from OG career boards (parallel)
python3 cli.py find --workers 8

# 2. Run JEV evaluation and tier scoring
python3 cli.py eval

# 3. Dynamically tailor resumes for top-priority jobs
python3 cli.py tailor --limit 5

# 4. Dispatch auto-apply flow via ego-browser
python3 cli.py apply --limit 5

# 5. Run the entire end-to-end pipeline in one command
python3 cli.py pipeline --workers 8 --limit 5

# 6. View real-time status summary
python3 cli.py status
```
