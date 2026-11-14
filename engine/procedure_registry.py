"""
Procedure Registry & Memory Engine for Autonomous Job Applications
Maintains, memorizes, and retrieves verified application procedures for each company.
Enforces zero-guesswork dispatch: knows ATS platform, auth mechanism, selectors,
resume archetypes, and form answers.
"""

import os
import re
import sys
import json
import subprocess
from pathlib import Path
from datetime import datetime
from typing import Dict, Any, List, Optional, Tuple
from engine.procedure_memory import record_company_procedure

from engine.config import (
    DATA_DIR,
    PROJECT_ROOT,
    DEFAULT_PORTAL_PASSWORD,
    CANDIDATE_NAME,
    CANDIDATE_FIRST_NAME,
    CANDIDATE_LAST_NAME,
    CANDIDATE_EMAIL,
    CANDIDATE_PERSONAL_EMAIL,
    CANDIDATE_COLLEGE_EMAIL,
    CANDIDATE_PHONE,
    CANDIDATE_LOCATION,
    CANDIDATE_CITY,
    CANDIDATE_ADDRESS,
    CANDIDATE_LINKEDIN,
    CANDIDATE_GITHUB,
    CANDIDATE_CURRENT_COMPANY,
    CANDIDATE_CURRENT_TITLE,
    EGO_BROWSER_MAIN_PROFILE_ID,
    EGO_BROWSER_COLLEGE_PROFILE_ID,
    ANS_WORK_AUTH_INDIA,
    ANS_SPONSORSHIP_INDIA,
    ANS_WORK_AUTH_US,
    ANS_SPONSORSHIP_US,
    ANS_CITIZENSHIP,
    ANS_LEGAL_RIGHT_TO_WORK,
    ANS_YEARS_OF_EXP,
    ANS_NOTICE_PERIOD,
    ANS_EARLIEST_START_DATE,
    ANS_CURRENT_CTC,
    ANS_EXPECTED_CTC,
    ANS_HOURLY_RATE_USD,
    ANS_GENDER,
    ANS_RACE_ETHNICITY,
    ANS_VETERAN_STATUS,
    ANS_ARMED_FORCES_STATUS,
    ANS_DISABILITY_STATUS,
    ANS_COLLEGE,
    ANS_DEGREE,
    ANS_MAJOR,
    ANS_GRAD_YEAR,
    ANS_CGPA,
    ANS_PITCH_AI_ENGINEER,
    ANS_WHY_ANTHROPIC,
    ANS_WHY_OPENAI,
    ANS_WHY_REMOTE
)

PROCEDURES_DIR = DATA_DIR / "company_apply_procedures"
PROCEDURES_DIR.mkdir(parents=True, exist_ok=True)


def _slugify(text: str) -> str:
    """Returns normalized alphanumeric slug (e.g., 'Scale AI' -> 'scaleai', 'OpenAI' -> 'openai')."""
    return re.sub(r"[^a-z0-9]", "", text.lower())


# Canonical procedure definitions for core target companies and ATS platforms
DEFAULT_COMPANY_PROCEDURES: Dict[str, Dict[str, Any]] = {
    "microsoft": {
        "company": "Microsoft",
        "ats_platform": "Eightfold.ai",
        "supported_urls": [
            "https://apply.careers.microsoft.com/careers/job/*",
            "https://apply.careers.microsoft.com/careers/apply?pid=*"
        ],
        "target_geography": "Strictly India (Hyderabad, Bengaluru, Noida, Gurugram)",
        "submission_policy": "STAGE_AND_VALIDATE",
        "browser_profile": EGO_BROWSER_MAIN_PROFILE_ID,
        "authentication": {
            "method": "Google OAuth",
            "account": "CANDIDATE_PERSONAL_EMAIL (.env)",
            "procedure": [
                "1. Navigate to target job posting",
                "2. Click 'Apply now' button",
                "3. Select 'Sign in using Google' (candidateAuthGoogleLoginButton)",
                "4. Authorize via Profile 1 Google account",
                "5. Redirects into multi-section Eightfold application form"
            ]
        },
        "resume_archetype": "RESUME_3_SWE_BACKEND (or RESUME_1_AI_ENGINEER for Research/AI)",
        "field_mappings": {
            "work_auth_india": "Yes",
            "visa_sponsorship_india": "No",
            "gender": "Male",
            "military_govt": "No",
            "non_compete": "No",
            "former_microsoft": "No",
            "job_specific_questions": "Yes to full-stack, cloud, scalability & architecture",
            "acknowledgments": "All required disclaimers checked (True)"
        },
        "dispatch_engine": "microsoft_apply",
        "cli_apply_command": "python3 cli.py apply-microsoft --url <url>"
    },
    "barclays": {
        "company": "Barclays",
        "ats_platform": "Workday (barclays.wd3.myworkdayjobs.com)",
        "supported_urls": [
            "https://search.jobs.barclays/job/*",
            "https://barclays.wd3.myworkdayjobs.com/External_Career_Site_Barclays/job/*"
        ],
        "target_geography": "India (Gurugram, Pune, Bengaluru)",
        "submission_policy": "STAGE_AND_VALIDATE",
        "browser_profile": EGO_BROWSER_MAIN_PROFILE_ID,
        "authentication": {
            "method": "Workday Account Registration & Activation",
            "account": "CANDIDATE_COLLEGE_EMAIL (.env)",
            "procedure": [
                "1. Navigate to Workday apply URL",
                "2. Register account using CANDIDATE_COLLEGE_EMAIL and DEFAULT_PORTAL_PASSWORD",
                "3. Activate account via Workday link sent to candidate email",
                "4. Execute 7-step wizard: Resume Upload -> My Information -> My Experience -> 10 Application Questions -> Voluntary Disclosures -> Review -> Submit"
            ]
        },
        "resume_archetype": "RESUME_1_AI_ENGINEER (Data Scientist / ML)",
        "field_mappings": {
            "source": "LinkedIn",
            "legal_right_to_work": "Yes - I am a citizen",
            "kpmg_auditor": "No",
            "preventing_employment": "No",
            "criminal_convictions": "No",
            "screening_consent": "Yes",
            "ethnicity": "Asian (India)"
        },
        "dispatch_engine": "barclays_apply",
        "cli_apply_command": "python3 cli.py apply-barclays --url <url>"
    },
    "stripe": {
        "company": "Stripe",
        "ats_platform": "Greenhouse Embed",
        "supported_urls": [
            "https://stripe.com/jobs/search?gh_jid=*",
            "https://stripe.com/careers/apply/*",
            "https://job-boards.greenhouse.io/embed/job_app?for=stripe&token=*",
            "https://boards.greenhouse.io/stripe/jobs/*"
        ],
        "target_geography": "India / Worldwide Remote",
        "submission_policy": "STAGE_AND_VALIDATE",
        "browser_profile": EGO_BROWSER_MAIN_PROFILE_ID,
        "authentication": {
            "method": "None (Public Embedded Greenhouse Form)",
            "account": "N/A",
            "procedure": [
                "1. Load Stripe career page or Greenhouse embed",
                "2. Auto-fill demographic, university, graduation year and links",
                "3. Attach 1-page XeTeX resume",
                "4. Answer work authorization (Yes) & competing offers (No)",
                "5. Validate submit button state"
            ]
        },
        "resume_archetype": "RESUME_3_SWE_BACKEND (or RESUME_1_AI_ENGINEER)",
        "field_mappings": {
            "college": ANS_COLLEGE,
            "degree": "Bachelor's Degree (B.Tech CS & AI)",
            "work_auth_india": "Yes, I am currently eligible",
            "visa_sponsorship_india": "No, I do not require",
            "offer_deadline": "No active competing deadlines. Immediate onboarding."
        },
        "dispatch_engine": "stripe_apply",
        "cli_apply_command": "python3 cli.py apply-stripe --url <url>"
    },
    "openai": {
        "company": "OpenAI",
        "ats_platform": "Ashby HQ",
        "supported_urls": [
            "https://jobs.ashbyhq.com/openai/*"
        ],
        "target_geography": "Worldwide Remote / India",
        "submission_policy": "STAGE_AND_VALIDATE",
        "browser_profile": EGO_BROWSER_MAIN_PROFILE_ID,
        "authentication": {
            "method": "None (Public Ashby Application)",
            "account": "N/A",
            "procedure": [
                "1. Navigate to Ashby job URL",
                "2. Click 'Apply for this Job' button",
                "3. Fill candidate contact info using UUID attribute selectors",
                "4. Attach 1-page XeTeX resume PDF",
                "5. Answer work authorization & location details",
                "6. Validate submit button"
            ]
        },
        "resume_archetype": "RESUME_1_AI_ENGINEER (Production LLMs, Fine-tuning, RAG)",
        "field_mappings": {
            "work_authorization": "Yes",
            "visa_sponsorship": "No",
            "availability": "Immediately / 15-30 days"
        },
        "dispatch_engine": "ashby_apply",
        "cli_apply_command": "python3 cli.py apply-ashby --url <url>"
    },
    "anthropic": {
        "company": "Anthropic",
        "ats_platform": "Greenhouse Standard",
        "supported_urls": [
            "https://job-boards.greenhouse.io/anthropic/*",
            "https://boards.greenhouse.io/anthropic/*"
        ],
        "target_geography": "Global Remote / India FTE",
        "submission_policy": "STAGE_AND_VALIDATE",
        "browser_profile": EGO_BROWSER_MAIN_PROFILE_ID,
        "authentication": {
            "method": "None (Public Greenhouse Board)",
            "account": "N/A",
            "procedure": [
                "1. Navigate to Greenhouse job board URL",
                "2. Populate demographic & contact inputs",
                "3. Attach tailored XeTeX resume",
                "4. Execute ChatGPT dynamic consultant for role-specific prompts",
                "5. Validate form readiness"
            ]
        },
        "resume_archetype": "RESUME_1_AI_ENGINEER (RL, Evaluation, Safety, Scaled Systems)",
        "field_mappings": {
            "work_authorization": "Yes",
            "visa_sponsorship": "No",
            "current_company": CANDIDATE_CURRENT_COMPANY,
            "current_title": CANDIDATE_CURRENT_TITLE
        },
        "dispatch_engine": "greenhouse_apply",
        "cli_apply_command": "python3 cli.py apply-greenhouse --url <url> --company anthropic"
    },
    "scaleai": {
        "company": "Scale AI",
        "ats_platform": "Greenhouse Standard",
        "supported_urls": [
            "https://job-boards.greenhouse.io/scaleai/*",
            "https://boards.greenhouse.io/scaleai/*"
        ],
        "target_geography": "Worldwide Remote / India",
        "submission_policy": "STAGE_AND_VALIDATE",
        "browser_profile": EGO_BROWSER_MAIN_PROFILE_ID,
        "authentication": {
            "method": "None (Greenhouse Board)",
            "account": "N/A",
            "procedure": [
                "1. Load Scale AI job application",
                "2. Fill applicant details and upload resume",
                "3. Stage for user review"
            ]
        },
        "resume_archetype": "RESUME_1_AI_ENGINEER",
        "field_mappings": {
            "work_authorization": "Yes",
            "visa_sponsorship": "No"
        },
        "dispatch_engine": "greenhouse_apply",
        "cli_apply_command": "python3 cli.py apply-greenhouse --url <url> --company scaleai"
    },
    "databricks": {
        "company": "Databricks",
        "ats_platform": "Greenhouse Embed",
        "supported_urls": [
            "https://databricks.com/company/careers/open-positions/job?gh_jid=*",
            "https://boards.greenhouse.io/databricks/*"
        ],
        "target_geography": "India (Bengaluru) / Remote",
        "submission_policy": "STAGE_AND_VALIDATE",
        "browser_profile": EGO_BROWSER_MAIN_PROFILE_ID,
        "authentication": {
            "method": "None (Embed Greenhouse Form)",
            "account": "N/A",
            "procedure": [
                "1. Load Databricks career job page",
                "2. Wait for Greenhouse iframe / embed form",
                "3. Populate fields and attach resume",
                "4. Validate submit readiness"
            ]
        },
        "resume_archetype": "RESUME_2_DATA_ENGINEER (Spark, ETL, Data Lake, Distributed Systems)",
        "field_mappings": {
            "work_authorization": "Yes",
            "visa_sponsorship": "No"
        },
        "dispatch_engine": "greenhouse_apply",
        "cli_apply_command": "python3 cli.py apply-greenhouse --url <url> --company databricks"
    },
    "brex": {
        "company": "Brex",
        "ats_platform": "Greenhouse Standard & Embed",
        "supported_urls": [
            "https://www.brex.com/careers/*?gh_jid=*",
            "https://job-boards.greenhouse.io/brex/*"
        ],
        "target_geography": "India / Worldwide Remote",
        "submission_policy": "STAGE_AND_VALIDATE",
        "browser_profile": EGO_BROWSER_MAIN_PROFILE_ID,
        "authentication": {"method": "None (Greenhouse)", "account": "N/A"},
        "resume_archetype": "RESUME_3_SWE_BACKEND",
        "dispatch_engine": "greenhouse_apply",
        "cli_apply_command": "python3 cli.py apply-greenhouse --url <url> --company brex"
    },
    "vercel": {
        "company": "Vercel",
        "ats_platform": "Greenhouse Standard",
        "supported_urls": [
            "https://job-boards.greenhouse.io/vercel/*",
            "https://boards.greenhouse.io/vercel/*"
        ],
        "target_geography": "Worldwide Remote / India",
        "submission_policy": "STAGE_AND_VALIDATE",
        "browser_profile": EGO_BROWSER_MAIN_PROFILE_ID,
        "authentication": {"method": "None (Greenhouse)", "account": "N/A"},
        "resume_archetype": "RESUME_3_SWE_BACKEND (Next.js, Edge Runtime, TypeScript)",
        "dispatch_engine": "greenhouse_apply",
        "cli_apply_command": "python3 cli.py apply-greenhouse --url <url> --company vercel"
    },
    "cursor": {
        "company": "Cursor (Anysphere)",
        "ats_platform": "Ashby HQ",
        "supported_urls": [
            "https://jobs.ashbyhq.com/anysphere/*",
            "https://jobs.ashbyhq.com/cursor/*"
        ],
        "target_geography": "Worldwide Remote",
        "submission_policy": "STAGE_AND_VALIDATE",
        "browser_profile": EGO_BROWSER_MAIN_PROFILE_ID,
        "authentication": {"method": "None (Ashby)", "account": "N/A"},
        "resume_archetype": "RESUME_1_AI_ENGINEER (Developer Tools & LLMs)",
        "dispatch_engine": "ashby_apply",
        "cli_apply_command": "python3 cli.py apply-ashby --url <url>"
    },
    "linear": {
        "company": "Linear",
        "ats_platform": "Ashby HQ",
        "supported_urls": [
            "https://jobs.ashbyhq.com/linear/*"
        ],
        "target_geography": "Worldwide Remote",
        "submission_policy": "STAGE_AND_VALIDATE",
        "browser_profile": EGO_BROWSER_MAIN_PROFILE_ID,
        "authentication": {"method": "None (Ashby)", "account": "N/A"},
        "resume_archetype": "RESUME_3_SWE_BACKEND",
        "dispatch_engine": "ashby_apply",
        "cli_apply_command": "python3 cli.py apply-ashby --url <url>"
    },
    "mercor": {
        "company": "Mercor",
        "ats_platform": "Mercor Talent Network & Ashby",
        "supported_urls": [
            "https://work.mercor.com/jobs/*",
            "https://jobs.ashbyhq.com/mercor/*"
        ],
        "target_geography": "Worldwide Remote / Independent Contractor ($70-$200/hr)",
        "submission_policy": "AUTO_SUBMIT",
        "browser_profile": EGO_BROWSER_MAIN_PROFILE_ID,
        "authentication": {
            "method": "Direct / Verified Profile",
            "account": "Profile 1 Candidate Session"
        },
        "resume_archetype": "RESUME_1_AI_ENGINEER",
        "dispatch_engine": "remote_apply",
        "cli_apply_command": "python3 cli.py apply-remote --url <url>"
    },
    "alignerr": {
        "company": "Alignerr",
        "ats_platform": "Labelbox / Alignerr Custom",
        "supported_urls": [
            "https://app.alignerr.com/application/*",
            "https://app.alignerr.com/home"
        ],
        "target_geography": "Worldwide Remote ($90-$120/hr)",
        "submission_policy": "AUTO_SUBMIT",
        "browser_profile": EGO_BROWSER_MAIN_PROFILE_ID,
        "authentication": {"method": "Candidate Portal Login", "account": "Profile 1"},
        "resume_archetype": "RESUME_1_AI_ENGINEER",
        "dispatch_engine": "remote_apply",
        "cli_apply_command": "python3 cli.py apply-remote --url <url>"
    },
    "palantir": {
        "company": "Palantir",
        "ats_platform": "Lever",
        "supported_urls": [
            "https://jobs.lever.co/palantir/*"
        ],
        "target_geography": "India / Worldwide Remote",
        "submission_policy": "STAGE_AND_VALIDATE",
        "browser_profile": EGO_BROWSER_MAIN_PROFILE_ID,
        "authentication": {"method": "None (Lever)", "account": "N/A"},
        "resume_archetype": "RESUME_1_AI_ENGINEER (Forward Deployed SWE / AI)",
        "dispatch_engine": "lever_apply",
        "cli_apply_command": "python3 cli.py apply-lever --url <url>"
    },
    "cisco": {
        "company": "Cisco",
        "ats_platform": "Phenom People / Naukri Direct",
        "supported_urls": [
            "https://jobs.cisco.com/*",
            "https://www.naukri.com/job-listings-*-cisco-*"
        ],
        "target_geography": "India (Bengaluru)",
        "submission_policy": "STAGE_AND_VALIDATE",
        "browser_profile": EGO_BROWSER_MAIN_PROFILE_ID,
        "authentication": {
            "method": "Naukri 1-Click / Phenom Candidate Profile",
            "account": "Profile 1"
        },
        "resume_archetype": "RESUME_3_SWE_BACKEND (Cloud, Distributed Systems, Python/Java)",
        "dispatch_engine": "greenhouse_apply",
        "cli_apply_command": "python3 cli.py apply --company cisco --url <url>"
    },
    "elevenlabs": {
        "company": "ElevenLabs",
        "ats_platform": "Ashby HQ",
        "supported_urls": [
            "https://jobs.ashbyhq.com/ElevenLabs/*",
            "https://jobs.ashbyhq.com/elevenlabs/*"
        ],
        "target_geography": "Global Remote / Worldwide",
        "submission_policy": "STAGE_AND_VALIDATE",
        "browser_profile": EGO_BROWSER_MAIN_PROFILE_ID,
        "authentication": {"method": "None (Public Ashby Application)", "account": "N/A"},
        "resume_archetype": "RESUME_1_AI_ENGINEER (Voice AI, Nova Sonic, Low Latency Audio)",
        "dispatch_engine": "ashby_apply",
        "cli_apply_command": "python3 cli.py apply-ashby --url <url>"
    },
    "outlier": {
        "company": "Outlier",
        "ats_platform": "Outlier AI Expert Network",
        "supported_urls": [
            "https://app.outlier.ai/en/expert/opportunities/*",
            "https://app.outlier.ai/*"
        ],
        "target_geography": "Worldwide Remote / India Contractor",
        "submission_policy": "AUTO_SUBMIT",
        "browser_profile": EGO_BROWSER_MAIN_PROFILE_ID,
        "authentication": {"method": "Direct / Verified Profile", "account": "Profile 1"},
        "resume_archetype": "RESUME_1_AI_ENGINEER (Codeforces Specialist, Competitive Python)",
        "dispatch_engine": "remote_apply",
        "cli_apply_command": "python3 cli.py apply-remote --url <url>"
    },
    "dataannotation": {
        "company": "DataAnnotation",
        "ats_platform": "DataAnnotation Tech Portal",
        "supported_urls": [
            "https://www.dataannotation.tech/job-board/*",
            "https://www.dataannotation.tech/*"
        ],
        "target_geography": "Worldwide Remote ($40-$150+/hr)",
        "submission_policy": "AUTO_SUBMIT",
        "browser_profile": EGO_BROWSER_MAIN_PROFILE_ID,
        "authentication": {"method": "Direct / Verified Profile", "account": "Profile 1"},
        "resume_archetype": "RESUME_1_AI_ENGINEER",
        "dispatch_engine": "remote_apply",
        "cli_apply_command": "python3 cli.py apply-remote --url <url>"
    },
    "toptal": {
        "company": "Toptal",
        "ats_platform": "Toptal Remote Talent Network",
        "supported_urls": [
            "https://www.toptal.com/*",
            "https://remoteok.com/remote-jobs/*toptal*"
        ],
        "target_geography": "Worldwide Remote ($80-$150/hr)",
        "submission_policy": "AUTO_SUBMIT",
        "browser_profile": EGO_BROWSER_MAIN_PROFILE_ID,
        "authentication": {"method": "Direct / Verified Profile", "account": "Profile 1"},
        "resume_archetype": "RESUME_1_AI_ENGINEER (vLLM, SGLang, TensorRT-LLM Inference)",
        "dispatch_engine": "remote_apply",
        "cli_apply_command": "python3 cli.py apply-remote --url <url>"
    },
    "masabi": {
        "company": "Masabi",
        "ats_platform": "Jobicy Remote Contract Portal",
        "supported_urls": [
            "https://jobicy.com/jobs/*masabi*",
            "https://masabi.workable.com/*"
        ],
        "target_geography": "Worldwide Remote / Independent Contractor",
        "submission_policy": "AUTO_SUBMIT",
        "browser_profile": EGO_BROWSER_MAIN_PROFILE_ID,
        "authentication": {"method": "Direct / Public Application", "account": "N/A"},
        "resume_archetype": "RESUME_2_DATA_ENGINEER (Spark, Kafka, Data Platforms)",
        "dispatch_engine": "remote_apply",
        "cli_apply_command": "python3 cli.py apply-remote --url <url>"
    }
}


def init_default_procedures():
    """Initializes or updates default company apply procedures on disk."""
    for slug, proc in DEFAULT_COMPANY_PROCEDURES.items():
        proc_file = PROCEDURES_DIR / f"{slug}.json"
        if not proc_file.exists():
            with open(proc_file, "w", encoding="utf-8") as f:
                json.dump(proc, f, indent=2)
        else:
            # Merge existing with defaults to preserve history while updating schema
            try:
                with open(proc_file, "r", encoding="utf-8") as f:
                    curr = json.load(f)
                # Keep existing history if present
                for k, v in proc.items():
                    if k not in curr:
                        curr[k] = v
                with open(proc_file, "w", encoding="utf-8") as f:
                    json.dump(curr, f, indent=2)
            except Exception:
                pass


# Initialize defaults at import time
init_default_procedures()


def get_procedure(company: str = "", url: str = "") -> Optional[Dict[str, Any]]:
    """
    Intelligently retrieves the memorized apply procedure for a given company or URL.
    Performs fuzzy slug matching, company-specific URL matching, and ATS-level fallbacks.
    """
    comp_slug = _slugify(company) if company else ""
    clean_url = (url or "").lower()

    # 1. Exact or slug match in company_apply_procedures directory
    if comp_slug:
        file_path = PROCEDURES_DIR / f"{comp_slug}.json"
        if file_path.exists():
            try:
                with open(file_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    if "company" not in data:
                        data["company"] = comp_slug.capitalize()
                    return data
            except Exception:
                pass

    # 2. First pass: Check company-specific files (excluding generic ats files)
    generic_ats_slugs = {"ashby", "greenhouse", "lever", "workday", "remote"}
    for p in PROCEDURES_DIR.glob("*.json"):
        if p.name.endswith("_history.json") or p.stem in generic_ats_slugs:
            continue
        try:
            with open(p, "r", encoding="utf-8") as f:
                data = json.load(f)
            if "company" not in data:
                data["company"] = p.stem.capitalize()

            # Check company name match
            if comp_slug and _slugify(data.get("company", "")) == comp_slug:
                return data

            # Check supported URLs pattern match
            if clean_url:
                for pat in data.get("supported_urls", []):
                    regex_pat = pat.replace("*", ".*").lower()
                    if re.search(regex_pat, clean_url):
                        return data
        except Exception:
            continue

    # 3. Second pass: Check if URL matches company-specific keywords
    if clean_url:
        for known_company in DEFAULT_COMPANY_PROCEDURES.keys():
            if known_company in clean_url:
                proc = get_procedure(known_company)
                if proc:
                    return proc

    # 4. Third pass: Detect ATS platform from URL and provide ATS-level procedure fallback
    if clean_url:
        if "careers.microsoft.com" in clean_url or "eightfold.ai" in clean_url:
            return get_procedure("microsoft")
        elif "barclays" in clean_url or "myworkdayjobs.com" in clean_url:
            return get_procedure("barclays")
        elif "stripe.com" in clean_url:
            return get_procedure("stripe")
        elif "ashbyhq.com" in clean_url:
            return {
                "company": company or "Ashby Supported Company",
                "ats_platform": "Ashby HQ",
                "supported_urls": ["https://jobs.ashbyhq.com/*"],
                "target_geography": "Worldwide Remote / India",
                "submission_policy": "STAGE_AND_VALIDATE",
                "browser_profile": EGO_BROWSER_MAIN_PROFILE_ID,
                "resume_archetype": "RESUME_1_AI_ENGINEER",
                "dispatch_engine": "ashby_apply",
                "cli_apply_command": f"python3 cli.py apply-ashby --url '{url}'"
            }
        elif "greenhouse.io" in clean_url or "gh_jid=" in clean_url:
            return {
                "company": company or "Greenhouse Supported Company",
                "ats_platform": "Greenhouse Standard",
                "supported_urls": ["https://job-boards.greenhouse.io/*", "https://boards.greenhouse.io/*"],
                "target_geography": "Worldwide Remote / India",
                "submission_policy": "STAGE_AND_VALIDATE",
                "browser_profile": EGO_BROWSER_MAIN_PROFILE_ID,
                "resume_archetype": "RESUME_1_AI_ENGINEER",
                "dispatch_engine": "greenhouse_apply",
                "cli_apply_command": f"python3 cli.py apply-greenhouse --url '{url}'"
            }
        elif "lever.co" in clean_url:
            return {
                "company": company or "Lever Supported Company",
                "ats_platform": "Lever",
                "supported_urls": ["https://jobs.lever.co/*"],
                "target_geography": "Worldwide Remote / India",
                "submission_policy": "STAGE_AND_VALIDATE",
                "browser_profile": EGO_BROWSER_MAIN_PROFILE_ID,
                "resume_archetype": "RESUME_1_AI_ENGINEER",
                "dispatch_engine": "lever_apply",
                "cli_apply_command": f"python3 cli.py apply-lever --url '{url}'"
            }
        elif "mercor.com" in clean_url or "weworkremotely.com" in clean_url or "remoteok.com" in clean_url:
            return {
                "company": company or "Remote Contract",
                "ats_platform": "Remote Contract Portal",
                "supported_urls": ["https://work.mercor.com/*", "https://weworkremotely.com/*"],
                "target_geography": "Worldwide Remote ($70-$200/hr)",
                "submission_policy": "AUTO_SUBMIT",
                "browser_profile": EGO_BROWSER_MAIN_PROFILE_ID,
                "resume_archetype": "RESUME_1_AI_ENGINEER",
                "dispatch_engine": "remote_apply",
                "cli_apply_command": f"python3 cli.py apply-remote --url '{url}'"
            }

    return None


def save_procedure(company: str, procedure_data: Dict[str, Any]) -> Path:
    """Saves or updates a company procedure in data/company_apply_procedures/."""
    slug = _slugify(company)
    file_path = PROCEDURES_DIR / f"{slug}.json"
    procedure_data["last_updated"] = datetime.now().isoformat()
    with open(file_path, "w", encoding="utf-8") as f:
        json.dump(procedure_data, f, indent=2)
    return file_path


def record_apply_event(
    company: str,
    job_url: str,
    status: str,
    submit: bool,
    resume: str = "",
    notes: str = "",
    job_id: str = "",
    title: str = ""
):
    """
    Memorizes application execution event in both the company's procedure file
    and company-specific history log.
    """
    slug = _slugify(company) if company else "unknown"
    event = {
        "timestamp": datetime.now().isoformat(),
        "job_id": job_id,
        "company": company,
        "title": title,
        "url": job_url,
        "status": status,
        "submit_mode": submit,
        "resume_path": resume,
        "notes": notes
    }

    # 1. Update company procedure history array
    proc_file = PROCEDURES_DIR / f"{slug}.json"
    if proc_file.exists():
        try:
            with open(proc_file, "r", encoding="utf-8") as f:
                proc = json.load(f)
            history = proc.get("history", [])
            history.append(event)
            proc["history"] = history
            proc["last_applied_at"] = event["timestamp"]
            proc["total_staged_or_applied"] = len(history)
            with open(proc_file, "w", encoding="utf-8") as f:
                json.dump(proc, f, indent=2)
        except Exception:
            pass

    # 2. Update dedicated <slug>_history.json
    hist_file = PROCEDURES_DIR / f"{slug}_history.json"
    history_list = []
    if hist_file.exists():
        try:
            with open(hist_file, "r", encoding="utf-8") as f:
                history_list = json.load(f)
        except Exception:
            history_list = []
    history_list.append(event)
    try:
        with open(hist_file, "w", encoding="utf-8") as f:
            json.dump(history_list, f, indent=2)
    except Exception:
        pass


def list_all_procedures() -> List[Dict[str, Any]]:
    """Returns a structured summary list of all memorized company apply procedures."""
    results = []
    for p in sorted(PROCEDURES_DIR.glob("*.json")):
        if p.name.endswith("_history.json"):
            continue
        try:
            with open(p, "r", encoding="utf-8") as f:
                data = json.load(f)
            slug = p.stem
            history = data.get("history", [])
            hist_file = PROCEDURES_DIR / f"{slug}_history.json"
            total_apps = len(history)
            if hist_file.exists() and total_apps == 0:
                try:
                    with open(hist_file, "r", encoding="utf-8") as hf:
                        total_apps = len(json.load(hf))
                except Exception:
                    pass

            results.append({
                "slug": slug,
                "company": data.get("company", slug.capitalize()),
                "ats_platform": data.get("ats_platform", "Unknown"),
                "auth_method": data.get("authentication", {}).get("method", "Direct / Public Embed"),
                "submission_policy": data.get("submission_policy", "STAGE_AND_VALIDATE"),
                "resume_archetype": data.get("resume_archetype", "Archetype 1 (AI/ML)"),
                "dispatch_engine": data.get("dispatch_engine", "auto"),
                "total_applications": total_apps,
                "file_path": str(p)
            })
        except Exception:
            continue
    return results


def dispatch_application(
    company: str,
    url: str,
    resume_path: Optional[str] = None,
    submit: bool = False,
    task_space: Optional[str] = None
) -> Dict[str, Any]:
    """
    The unified execution router. Looks up the memorized apply procedure for the
    company/URL, executes the appropriate engine, records the result in memory,
    and returns the execution status.
    """
    from engine.resume_router import select_resume_for_job

    if not resume_path or not Path(resume_path).exists():
        routed = select_resume_for_job(company=company, title="Software Engineer", jd_text="")
        resume_path = routed.get("resume_path", "")
        print(f"[*] Auto-routed resume for {company}: {Path(resume_path).name} ({routed.get('notes')})")

    proc = get_procedure(company=company, url=url)
    engine = proc.get("dispatch_engine") if proc else None
    if engine:
        engine = engine.replace("engine/", "").replace(".py", "")

    # Fallback engine detection from URL
    url_lower = url.lower()
    if not engine:
        if "careers.microsoft.com" in url_lower or "eightfold.ai" in url_lower or "microsoft" in (company or "").lower():
            engine = "microsoft_apply"
        elif "stripe.com" in url_lower:
            engine = "stripe_apply"
        elif "barclays" in url_lower or "myworkdayjobs.com" in url_lower:
            engine = "barclays_apply"
        elif "ashbyhq.com" in url_lower:
            engine = "ashby_apply"
        elif "greenhouse.io" in url_lower or "gh_jid=" in url_lower:
            engine = "greenhouse_apply"
        elif "lever.co" in url_lower:
            engine = "lever_apply"
        elif "rippling.com" in url_lower:
            engine = "rippling_apply"
        elif "breezy.hr" in url_lower:
            engine = "breezy_apply"
        elif "careers-page.com" in url_lower or "manatal.com" in url_lower:
            engine = "manatal_apply"
        elif "micro1.ai" in url_lower:
            engine = "micro1_apply"
        elif "applytojob.com" in url_lower or "jazzhr" in url_lower:
            engine = "jazzhr_apply"
        elif "amazon.jobs" in url_lower or "amazon" in (company or "").lower():
            engine = "amazon_apply"
        elif "mercor.com" in url_lower or "outlier.ai" in url_lower:
            engine = "remote_apply"
        elif "askable.com" in url_lower or "askable" in (company or "").lower():
            engine = "askable_apply"
        else:
            engine = "intelligent_solver"

    print(f"[*] Memorized Procedure Match: Company='{company}' -> ATS Engine='{engine}'")

    res = {"success": False, "error": f"Unknown engine: {engine}"}

    if engine == "microsoft_apply":
        from engine.microsoft_apply import apply_to_microsoft_job
        res = apply_to_microsoft_job(url, resume_path=resume_path, submit=submit)
    elif engine == "stripe_apply":
        from engine.stripe_apply import apply_to_stripe_job
        res = apply_to_stripe_job(url, resume_path=resume_path, submit=submit)
    elif engine == "barclays_apply":
        from engine.barclays_apply import apply_to_barclays_workday
        res = apply_to_barclays_workday(url, resume_path=resume_path, submit=submit)
    elif engine == "ashby_apply":
        from engine.ashby_apply import apply_to_ashby_job
        tspace = task_space or "ashby_auto_apply"
        res = apply_to_ashby_job(url, resume_path=resume_path, submit=submit, task_space_name=tspace)
        if not res.get("success"):
            print(f"[*] Standard Ashby apply had issues, invoking Intelligent Form Solver fallback...")
            from engine.intelligent_form_solver import execute_intelligent_application
            res = execute_intelligent_application(url=url, company=company, title="Software Engineer", resume_path=resume_path, submit=submit, task_space_name=tspace)
    elif engine == "greenhouse_apply":
        from engine.greenhouse_apply import apply_to_greenhouse_job
        tspace = task_space or "greenhouse_auto_apply"
        res = apply_to_greenhouse_job(url, resume_path=resume_path, company_name=company, submit=submit, task_space_name=tspace)
        if not res.get("success"):
            print(f"[*] Standard Greenhouse apply had issues, invoking Intelligent Form Solver fallback...")
            from engine.intelligent_form_solver import execute_intelligent_application
            res = execute_intelligent_application(url=url, company=company, title="Software Engineer", resume_path=resume_path, submit=submit, task_space_name=tspace)
    elif engine == "lever_apply":
        from engine.lever_apply import apply_to_lever_job
        tspace = task_space or "lever_auto_apply"
        res = apply_to_lever_job(url, resume_path=resume_path, submit=submit, task_space_name=tspace)
        if not res.get("success"):
            print(f"[*] Standard Lever apply had issues, invoking Intelligent Form Solver fallback...")
            from engine.intelligent_form_solver import execute_intelligent_application
            res = execute_intelligent_application(url=url, company=company, title="Software Engineer", resume_path=resume_path, submit=submit, task_space_name=tspace)
    elif engine == "amazon_apply":
        from engine.amazon_apply import apply_to_amazon_job
        tspace = task_space or "amazon_auto_apply"
        res = apply_to_amazon_job(url, resume_path=resume_path, submit=submit, task_space_name=tspace)
    elif engine == "remote_apply":
        from engine.remote_apply import apply_to_remote_contract_job
        res = apply_to_remote_contract_job(url, resume_path=resume_path, submit=submit)
    elif engine == "rippling_apply":
        from engine.rippling_apply import apply_rippling
        tspace = task_space or "rippling_auto_apply"
        res = apply_rippling(url, resume_path=resume_path, submit=submit, task_space_name=tspace)
    elif engine == "breezy_apply":
        from engine.breezy_apply import apply_to_breezy_job
        tspace = task_space or "breezy_auto_apply"
        res = apply_to_breezy_job(url, resume_path=resume_path, company_name=company, submit=submit, task_space_name=tspace)
    elif engine == "manatal_apply":
        from engine.manatal_apply import apply_to_manatal_job
        tspace = task_space or "manatal_auto_apply"
        res = apply_to_manatal_job(url, resume_path=resume_path, submit=submit, task_space_name=tspace)
    elif engine == "micro1_apply":
        from engine.micro1_apply import apply_to_micro1_job
        tspace = task_space or "micro1_auto_apply"
        res = apply_to_micro1_job(url, resume_path=resume_path, submit=submit, task_space_name=tspace)
    elif engine == "jazzhr_apply":
        from engine.jazzhr_apply import apply_to_jazzhr_job
        tspace = task_space or "jazzhr_auto_apply"
        res = apply_to_jazzhr_job(url, resume_path=resume_path, company_name=company, submit=submit, task_space_name=tspace)
    elif engine == "askable_apply":
        from engine.askable_apply import apply_to_askable_job
        tspace = task_space or "apply_askable"
        res = apply_to_askable_job(url, resume_path=resume_path, submit=submit, task_space_name=tspace)
    elif engine.startswith("generated_"):
        safe_co = engine.replace("generated_", "")
        script_file = DATA_DIR / "generated_scripts" / f"{safe_co}_apply.py"
        if script_file.exists():
            cmd = [sys.executable, str(script_file), "--url", url]
            if resume_path:
                cmd.extend(["--resume", str(resume_path)])
            if submit:
                cmd.append("--submit")
            try:
                p = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
                out = (p.stdout or "") + "\n" + (p.stderr or "")
                for line in out.splitlines():
                    line_s = line.strip()
                    if line_s.startswith("{") and line_s.endswith("}"):
                        try:
                            res = json.loads(line_s)
                            break
                        except Exception:
                            pass
                if not res.get("success"):
                    print(f"[*] Generated script for {company} had issues, invoking Intelligent Form Solver...")
                    from engine.intelligent_form_solver import execute_intelligent_application
                    tspace = task_space or f"apply_{safe_co}"
                    res = execute_intelligent_application(url=url, company=company, title="Software Engineer", resume_path=resume_path, submit=submit, task_space_name=tspace)
            except Exception as e:
                print(f"[!] Generated script run error: {e}, falling back to Intelligent Form Solver...")
                from engine.intelligent_form_solver import execute_intelligent_application
                tspace = task_space or f"apply_{safe_co}"
                res = execute_intelligent_application(url=url, company=company, title="Software Engineer", resume_path=resume_path, submit=submit, task_space_name=tspace)
        else:
            from engine.intelligent_form_solver import execute_intelligent_application
            tspace = task_space or f"apply_{safe_co}"
            res = execute_intelligent_application(url=url, company=company, title="Software Engineer", resume_path=resume_path, submit=submit, task_space_name=tspace)
    elif engine in ("intelligent_solver", "portal_generator", "ego_browser_task_space") or not res.get("success"):
        from engine.intelligent_form_solver import execute_intelligent_application
        tspace = task_space or f"apply_{re.sub(r'[^a-zA-Z0-9]', '', (company or 'job').lower())[:12]}"
        res = execute_intelligent_application(url=url, company=company, title="Software Engineer", resume_path=resume_path, submit=submit, task_space_name=tspace)

    # Record event in procedure memory
    status_str = "APPLIED" if (res.get("success") and submit) else ("STAGED_FOR_REVIEW" if res.get("success") else "FAILED")
    record_apply_event(
        company=company,
        job_url=url,
        status=status_str,
        submit=submit,
        resume=resume_path or "",
        notes=res.get("notes", "") if isinstance(res, dict) else ""
    )

    return res
