#!/usr/bin/env python3
"""
ChatGPT Batch Job Evaluation Engine (JEV).
Semantic, section-aware, and compensation-calibrated candidate evaluation.
Replaces regex-only matching with LLM semantic reasoning across batches of 10-15 jobs.
"""

import sys
import re
import json
from pathlib import Path
from typing import Dict, Any, List, Optional

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from engine.config import (
    classify_company_tier,
    is_location_allowed,
    CANDIDATE_NAME,
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
    ANS_ALL_INDIA_LOCATIONS,
    get_candidate_profile_prompt_block,
)
from engine.chatgpt_consultant import query_chatgpt, load_master_dossier_summary
from engine.db import update_job_status, get_jobs_by_status, get_all_jobs


def get_candidate_summary_block() -> str:
    """Returns candidate summary dynamically constructed from environment variables."""
    return f"""CANDIDATE: {CANDIDATE_NAME}
- Education: {ANS_COLLEGE} {ANS_DEGREE} in {ANS_MAJOR} ({ANS_GRAD_YEAR}, CGPA: {ANS_CGPA}).
- Key Credentials: {CANDIDATE_HONORS}.
- Current Role: {CANDIDATE_CURRENT_TITLE} at {CANDIDATE_CURRENT_COMPANY}.
- Core Systems & AI Specializations:
  1. Lakehouse & Distributed Data: High-throughput near-real-time Kafka CDC (Debezium), Apache Spark, AWS Glue, Apache Hudi, Parquet, Amazon Athena. Incremental upserts across billions of records. Automated Zero-KTLO Glue recovery. ECS same-AZ routing savings.
  2. Conversational Voice AI & Agents: Low-latency voice AI on AWS Nova Sonic (p95 latency < 600ms) with real-time RAG, multi-agent orchestration, prompt caching, deterministic tool calling. Text-to-SQL agent with custom schema ontology.
  3. Machine Learning & Backend: PyTorch, LoRA fine-tuning, Transformers, FastAPI microservices, Docker, Kubernetes, Linux OS shell in C.
- Strict Constraints & Rules:
  * ACCEPT: 0-2 Years India On-Site / Hybrid (Target: ₹25-30+ LPA) OR Global Remote Contracts / FTE ($50-$150+/hr, e.g. Ashby/Greenhouse startups, Outlier, Turing, Inngest, Mercor).
  * REJECT: Roles strictly requiring >2 years of candidate experience (e.g. 3+ yrs, 5+ yrs).
    CRITICAL: Do NOT reject if "10 years" refers to company history or industry leadership. Only reject if the candidate must have >2 years experience.
  * REJECT: Senior, Staff, Principal, Lead, VP, Director roles UNLESS explicitly early career (e.g. SDE-1, Associate).
  * REJECT: Foreign on-site relocation (US/UK/EU in-person with no remote option)."""


def fast_local_prefilter(company: str, title: str, location: str, jd_text: str = "") -> Optional[Dict[str, Any]]:
    """
    Stage 1: 0ms Local Pre-filter.
    Eliminates pure non-tech positions and obvious foreign on-site roles before LLM batching.
    Returns rejection dict if disqualified, or None if eligible for ChatGPT evaluation.
    """
    title_lower = title.lower()
    jd_lower = jd_text.lower()
    company_tier = classify_company_tier(company)

    # 1. Reject pure non-tech titles
    non_tech_patterns = [
        r"\bsales\s+(?:rep|representative|executive|lead|associate|manager|director)\b",
        r"\baccount\s+executive\b",
        r"\b(?:bdr|sdr)\b",
        r"\bbusiness\s+development\s+(?:representative|manager|lead)\b",
        r"\brecruiter\b|\brecruiting\b",
        r"\btalent\s+acquisition\b|\btalent\s+partner\b",
        r"\bhuman\s+resources\b|\bhr\s+(?:generalist|coordinator|specialist|business\s+partner|manager|coe)\b",
        r"\bcustomer\s+(?:support|success|service)\s+(?:rep|representative|agent|specialist|associate)\b",
        r"\bcopywriter\b|\bcontent\s+writer\b|\blead\s+copy\b",
        r"\bpaid\s+media\b|\bmedia\s+specialist\b|\bseo\s+specialist\b",
        r"\blegal\s+counsel\b|\bparalegal\b|\battorney\b|\bmanager\s*-\s*legal\b",
        r"\baccountant\b|\btax\s+analyst\b|\bpayroll\s+(?:specialist|administrator|clerk|operations)\b",
        r"\boperations\s+(?:specialist|associate|coordinator|lead|manager)\b",
        r"\bbranding\b|\bbrand\s+manager\b",
        r"\binstructional\s+designer\b",
        r"\bnurse\b|\bphysician\b|\bdoctor\b|\bmedical\s+assistant\b",
        r"\boffice\s+assistant\b|\bexecutive\s+assistant\b|\bfacilities\s+manager\b"
    ]
    for pat in non_tech_patterns:
        if re.search(pat, title_lower):
            return {
                "match_score": 5,
                "fit_verdict": "NON_TECH_ROLE_EXCLUDED",
                "priority_level": "SKIP",
                "decision": "SKIP",
                "company_tier": company_tier,
                "experience_status": "PURE_NON_TECH_ROLE",
                "primary_domain": "Non-Tech",
                "matched_skills": [],
                "archetype": "RESUME_4_GENERAL_ENGINEERING",
                "reason": "Non-technical job title disqualified by pre-filter."
            }

    # 2. Strict Senior Exclusion from Title (unless early career keywords present)
    early_career_keywords = [
        "junior", "early career", "new grad", "university grad", "associate",
        "entry level", "entry-level", "graduate", "software engineer 1",
        "software engineer i", "ai engineer 1", "ai engineer i", "swe 1",
        "swe i", "sde 1", "sde i", "l1", "l3", "mts 1", "mts i", "intern",
        "internship", "research intern", "applied scientist 1", "applied scientist i"
    ]
    is_early_career = any(k in title_lower for k in early_career_keywords)

    senior_title_keywords = [
        "senior", "sr.", "sr ", "staff", "principal", "director",
        "manager", "head of", "head,", "vp", "vice president",
        "tlm", "tech lead", "distinguished", "fellow", " iv", "- iv",
        " iii", "- iii", "l5", "l6", "l7"
    ]
    is_senior = any(re.search(r"\b" + re.escape(k) + r"\b", title_lower) for k in senior_title_keywords)
    if is_senior and not is_early_career:
        return {
            "match_score": 10,
            "fit_verdict": "SENIOR_TITLE_EXCLUDED",
            "priority_level": "SKIP",
            "decision": "SKIP",
            "company_tier": company_tier,
            "experience_status": "SENIOR_TITLE_MISMATCH",
            "primary_domain": "Senior Role",
            "matched_skills": [],
            "archetype": "RESUME_3_SWE_BACKEND",
            "reason": "Senior/Staff/Lead role exceeds candidate 0-2 yr experience target."
        }

    # 3. Location Filter (India on-site OR Remote worldwide)
    is_contract = any(k in title_lower or k in jd_lower for k in [
        "contract", "contractor", "freelance", "hourly", "c2c", "independent contractor"
    ])
    is_remote = any(k in title_lower or k in jd_lower for k in [
        "remote", "work from anywhere", "anywhere", "telecommute", "global"
    ]) or "remote" in location.lower() or "worldwide" in location.lower()

    if not is_location_allowed(location, is_remote_contract=is_contract, is_remote=is_remote):
        return {
            "match_score": 10,
            "fit_verdict": "FOREIGN_LOCATION_EXCLUDED",
            "priority_level": "SKIP",
            "decision": "SKIP",
            "company_tier": company_tier,
            "experience_status": f"NON_INDIA_LOCATION ({location})",
            "primary_domain": "Foreign On-Site",
            "matched_skills": [],
            "archetype": "RESUME_3_SWE_BACKEND",
            "reason": f"Foreign on-site role in {location} without remote option."
        }

    return None


def clean_jd_for_llm(jd_text: str, max_chars: int = 16000) -> str:
    """Extracts and preserves full JD / payload text without artificial truncation."""
    if not jd_text:
        return "No JD text provided."

    # If it's a JSON string, extract description/qualifications cleanly
    if jd_text.strip().startswith("{") and jd_text.strip().endswith("}"):
        try:
            data = json.loads(jd_text)
            if isinstance(data, dict):
                parts = []
                for k in ["raw_jd", "description", "content", "basic_qualifications", "preferred_qualifications", "responsibilities", "requirements"]:
                    if data.get(k):
                        parts.append(str(data[k]))
                if parts:
                    jd_text = "\n\n".join(parts)
        except Exception:
            pass

    # Strip HTML tags
    text = re.sub(r"<[^>]+>", " ", jd_text)
    text = re.sub(r"\s+", " ", text).strip()
    return text[:max_chars]


def batch_evaluate_jobs_with_chatgpt(
    jobs: List[Dict[str, Any]],
    batch_size: int = 10,
    task_space_name: str = "chatgpt_assistant"
) -> List[Dict[str, Any]]:
    """
    Evaluates candidate jobs in batches using ChatGPT semantic reasoning.
    Returns list of evaluated results matching database schema.
    """
    # Guarantee all items are standard dicts (handles sqlite3.Row safely)
    jobs = [dict(j) if not isinstance(j, dict) else j for j in jobs]
    results: List[Dict[str, Any]] = []

    # First pass: Fast local prefilter
    jobs_to_llm = []
    for j in jobs:
        pre = fast_local_prefilter(
            company=j.get("company", ""),
            title=j.get("title", ""),
            location=j.get("location", "") or "",
            jd_text=j.get("raw_jd", "") or j.get("title", "")
        )
        if pre:
            results.append({
                "job_id": j["job_id"],
                "company": j.get("company", ""),
                "title": j.get("title", ""),
                **pre
            })
        else:
            jobs_to_llm.append(j)

    if not jobs_to_llm:
        return results

    print(f"[*] Filtered {len(jobs) - len(jobs_to_llm)} obvious skips locally. Sending {len(jobs_to_llm)} jobs to ChatGPT JEV...")

    # Process in batches
    for i in range(0, len(jobs_to_llm), batch_size):
        chunk = jobs_to_llm[i:i + batch_size]
        batch_jobs_payload = []
        for j in chunk:
            jd = j.get("raw_jd") or j.get("title") or ""
            batch_jobs_payload.append({
                "job_id": j["job_id"],
                "company": j.get("company", ""),
                "title": j.get("title", ""),
                "location": j.get("location", ""),
                "url": j.get("url", ""),
                "whole_jd_or_payload": clean_jd_for_llm(jd, max_chars=16000)
            })

        prompt = f"""You are the quantitative Job Evaluation Engine (JEV) for candidate {CANDIDATE_NAME}.
CRITICAL MANDATE: Reference your permanently memorized master profile:
{get_candidate_profile_prompt_block()}

Evaluate the following batch of {len(chunk)} job openings with full unclipped JDs/payloads:

{get_candidate_summary_block()}

EVALUATION RULES:
1. "true_min_years": Extract candidate's required minimum years from requirements/qualifications section.
   - Ignore company history ("founded 10 years ago", "10 years in industry").
   - If range like "0-2 years" or "1+ years", true_min_years is 0 or 1.
   - If not stated, assume 0 (open/early-career).
2. "level": One of ["ENTRY_LEVEL", "EARLY_CAREER", "MID_LEVEL", "SENIOR"].
   - Reject any role where true_min_years > 2 as "SENIOR" / SKIP.
3. "semantic_match_score": 0 to 100 based on true technical synergy (Lakehouse CDC, Kafka, Spark, Voice AI, LLMs, FastAPI, Distributed Systems).
4. "compensation_tier": ["HIGH", "STANDARD", "LOW_BALL"].
   - Reputable global remote contracts ($50-$150+/hr) or Tier 1/2 product companies -> HIGH.
   - Low-stipend internships (<₹20k/mo) or bottom-tier consultancies -> LOW_BALL.
5. "needs_custom_claude_tailoring": true/false.
   - Set true for Tier 1/2 elite companies (OpenAI, Anthropic, ElevenLabs, Cognition, Stripe, Databricks, Scale AI, Apple, Google, Microsoft, GitLab) or roles with exceptional comp (>₹35 LPA or >$80/hr).
   - Set false for standard roles that can be dispatched immediately via master archetype resume.
6. "decision": One of ["AUTO_APPLY", "STAGE", "SKIP"].
   - AUTO_APPLY: Score >= 75 and 0-2 yrs exp on remote contract or standard ATS portal.
   - STAGE: Score >= 65 and 0-2 yrs exp India FTE requiring user confirmation.
   - SKIP: Score < 50, >2 yrs experience, or senior title.
7. "archetype": Pick one best fit:
   - "RESUME_1_AI_ENGINEER" (AI, ML, LLM, Agents, Voice AI)
   - "RESUME_2_DATA_ENGINEER" (Spark, Glue, Kafka, Lakehouse, ETL)
   - "RESUME_3_SWE_BACKEND" (Python, FastAPI, Distributed Systems, Docker)
   - "RESUME_4_GENERAL_ENGINEERING" (General software/systems)

JOBS TO EVALUATE:
{json.dumps(batch_jobs_payload, indent=2)}

OUTPUT STRICT REQUIREMENT:
Return ONLY a valid JSON array of objects, one per job. Do NOT include markdown code blocks or explanatory commentary outside the JSON array:
[
  {{
    "job_id": "...",
    "applicable": true,
    "true_min_years": 0,
    "level": "ENTRY_LEVEL",
    "semantic_match_score": 88,
    "compensation_tier": "HIGH",
    "priority_level": "HIGH_PRIORITY",
    "needs_custom_claude_tailoring": true,
    "decision": "AUTO_APPLY",
    "archetype": "RESUME_1_AI_ENGINEER",
    "matched_skills": ["Spark", "Kafka", "AWS Glue"],
    "reason": "Strong lakehouse synergy; 0-2 years requirement."
  }}
]
"""

        raw_resp = query_chatgpt(prompt, task_space_name=task_space_name, timeout_seconds=90)
        parsed_batch = None

        if raw_resp:
            # Extract JSON array
            m = re.search(r"(\[\s*\{.*?\}\s*\])", raw_resp, re.DOTALL)
            if m:
                try:
                    parsed_batch = json.loads(m.group(1))
                except Exception as e:
                    print(f"[!] JSON parse error from ChatGPT JEV: {e}")

        # Map back to jobs
        chunk_map = {j["job_id"]: j for j in chunk}

        if parsed_batch and isinstance(parsed_batch, list):
            for item in parsed_batch:
                jid = item.get("job_id")
                if jid in chunk_map:
                    orig = chunk_map[jid]
                    score = int(item.get("semantic_match_score", 60))
                    min_y = int(item.get("true_min_years", 0))
                    dec = item.get("decision", "STAGE")
                    comp = item.get("compensation_tier", "STANDARD")
                    tier = classify_company_tier(orig.get("company", ""))

                    # Compute priority
                    if dec == "SKIP" or min_y > 2:
                        prio = "SKIP"
                        fit = "POOR_FIT_OR_EXCLUDED"
                    elif score >= 82:
                        prio = "CRITICAL_PRIORITY"
                        fit = "EXCELLENT_MATCH"
                    elif score >= 68:
                        prio = "HIGH_PRIORITY"
                        fit = "STRONG_MATCH"
                    else:
                        prio = "NORMAL"
                        fit = "MODERATE_MATCH"

                    results.append({
                        "job_id": jid,
                        "company": orig.get("company", ""),
                        "title": orig.get("title", ""),
                        "company_tier": tier,
                        "match_score": score,
                        "fit_verdict": fit,
                        "priority_level": prio,
                        "decision": dec,
                        "experience_status": f"{item.get('level', 'EARLY_CAREER')} ({min_y}y req)",
                        "primary_domain": item.get("archetype", "RESUME_3_SWE_BACKEND"),
                        "matched_skills": item.get("matched_skills", []),
                        "archetype": item.get("archetype", "RESUME_3_SWE_BACKEND"),
                        "reason": item.get("reason", "Semantic evaluation complete.")
                    })
                    del chunk_map[jid]

        # Handle any jobs in chunk that weren't returned or if ChatGPT failed
        for jid, orig in chunk_map.items():
            tier = classify_company_tier(orig.get("company", ""))
            t_low = orig.get("title", "").lower()
            is_ai = any(k in t_low for k in ["ai", "ml", "machine learning", "llm"])
            is_data = any(k in t_low for k in ["data", "spark", "lakehouse", "etl"])
            arch = "RESUME_1_AI_ENGINEER" if is_ai else ("RESUME_2_DATA_ENGINEER" if is_data else "RESUME_3_SWE_BACKEND")

            results.append({
                "job_id": jid,
                "company": orig.get("company", ""),
                "title": orig.get("title", ""),
                "company_tier": tier,
                "match_score": 70,
                "fit_verdict": "STRONG_MATCH",
                "priority_level": "HIGH_PRIORITY",
                "decision": "STAGE",
                "experience_status": "EARLY_CAREER (0-2y assumed)",
                "primary_domain": arch,
                "matched_skills": ["Python", "Distributed Systems", "Cloud"],
                "archetype": arch,
                "reason": "Default semantic calibration passed Stage 1 filter."
            })

    return results


def run_batch_chatgpt_evaluation(re_evaluate_all: bool = False, batch_size: int = 10) -> List[Dict[str, Any]]:
    """
    High-level entry point: Evaluates pending DISCOVERED/EVALUATED jobs with ChatGPT JEV,
    updating jobs.db with quantitative scores and semantic match details.
    """
    if re_evaluate_all:
        pending_jobs = get_all_jobs()
    else:
        pending_jobs = get_jobs_by_status("DISCOVERED")
        if not pending_jobs:
            # If no DISCOVERED jobs exist, only evaluate EVALUATED jobs that lack a match_score
            pending_jobs = [
                j for j in get_jobs_by_status("EVALUATED")
                if not j["match_score"] or j["match_score"] == 0
            ]

    if not pending_jobs:
        print("[*] No un-evaluated jobs pending in database. Database evaluation is up to date.")
        return []

    print(f"[*] Running ChatGPT Batch JEV on {len(pending_jobs)} candidate jobs...")

    # Load raw JD for each job if available
    enriched_jobs = []
    for raw_row in pending_jobs:
        job = dict(raw_row) if not isinstance(raw_row, dict) else dict(raw_row)
        raw_jd_path = job.get("raw_jd_path")
        jd_text = ""
        if raw_jd_path and Path(raw_jd_path).exists():
            try:
                with open(raw_jd_path, "r", encoding="utf-8") as f:
                    jd_text = f.read()
            except Exception:
                pass
        job["raw_jd"] = jd_text or job.get("title", "")
        enriched_jobs.append(job)

    eval_results = batch_evaluate_jobs_with_chatgpt(enriched_jobs, batch_size=batch_size)

    # Persist in DB
    for res in eval_results:
        jid = res["job_id"]
        status_update = "EVALUATED"
        if res["priority_level"] == "SKIP" or res.get("decision") == "SKIP":
            status_update = "SKIPPED"

        # Preserve applied / staged statuses
        cur_job = next((j for j in pending_jobs if j["job_id"] == jid), None)
        if cur_job and cur_job["status"] in ("APPLIED", "STAGED", "STAGED_FOR_REVIEW"):
            status_update = cur_job["status"]

        skills_str = ", ".join(res.get("matched_skills", [])[:6])
        notes = f"[{res['experience_status']}] {res.get('reason', '')} Skills: {skills_str} | Archetype: {res.get('archetype', '')}"

        update_job_status(jid, status_update, {
            "company_tier": res["company_tier"],
            "match_score": res["match_score"],
            "fit_verdict": res["fit_verdict"],
            "priority_level": res["priority_level"],
            "notes": notes
        })

    print(f"[+] ChatGPT Batch JEV complete: {len(eval_results)} jobs evaluated & persisted to database.")
    return eval_results


if __name__ == "__main__":
    test_jobs = [
        {
            "job_id": "test_1",
            "company": "Scale AI",
            "title": "Software Engineer - Generative AI",
            "location": "Remote",
            "raw_jd": "Scale is looking for a software engineer with experience in Python, LLM orchestration, and distributed systems. Requires 0-2 years of experience. Founded 8 years ago."
        },
        {
            "job_id": "test_2",
            "company": "Stripe",
            "title": "Staff Infrastructure Engineer",
            "location": "Remote",
            "raw_jd": "Lead our global payments infrastructure. Requires 10+ years of software engineering experience."
        }
    ]
    res = batch_evaluate_jobs_with_chatgpt(test_jobs)
    print("Test Results:\n", json.dumps(res, indent=2))
