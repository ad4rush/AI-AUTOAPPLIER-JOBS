#!/usr/bin/env python3
"""
Autonomous Procedure & Q&A Memory Engine.
Provides persistent memorization of:
1. Company application form structures and custom question schemas.
2. Verified candidate answers (both standard deterministic answers and ChatGPT-generated essay answers).
3. Fast 0ms retrieval of previously answered questions for the same company or identical questions across companies.
"""

import os
import re
import sys
import json
import hashlib
from datetime import datetime
from pathlib import Path
from typing import Dict, Any, List, Optional

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from engine.config import (
    DATA_DIR,
    CANDIDATE_NAME,
    CANDIDATE_FIRST_NAME,
    CANDIDATE_LAST_NAME,
    CANDIDATE_EMAIL,
    CANDIDATE_PHONE,
    CANDIDATE_LOCATION,
    CANDIDATE_LINKEDIN,
    CANDIDATE_GITHUB,
    CANDIDATE_CURRENT_COMPANY,
    CANDIDATE_CURRENT_TITLE,
    ANS_WORK_AUTH_INDIA,
    ANS_SPONSORSHIP_INDIA,
    ANS_WORK_AUTH_US,
    ANS_SPONSORSHIP_US,
    ANS_YEARS_OF_EXP,
    ANS_NOTICE_PERIOD,
    ANS_EARLIEST_START_DATE,
    ANS_CURRENT_CTC,
    ANS_EXPECTED_CTC,
    ANS_COLLEGE,
    ANS_DEGREE,
    ANS_MAJOR,
    ANS_GRAD_YEAR,
    ANS_CGPA,
    ANS_GENDER,
    ANS_PITCH_AI_ENGINEER,
    ANS_ALL_INDIA_LOCATIONS,
)
from engine.chatgpt_consultant import ask_chatgpt_for_application_answers
from engine.gemini_batch_client import query_questions_batch

PROCEDURES_DIR = DATA_DIR / "company_apply_procedures"
PROCEDURES_DIR.mkdir(parents=True, exist_ok=True)
QA_CACHE_FILE = PROCEDURES_DIR / "qa_cache.json"


def _slugify(text: str) -> str:
    """Returns normalized alphanumeric slug."""
    return re.sub(r"[^a-z0-9]", "", text.lower())


def _normalize_question_key(question_text: str) -> str:
    """Creates a normalized semantic key from question text."""
    clean = re.sub(r"[^a-zA-Z0-9\s]", " ", question_text.lower()).strip()
    clean = re.sub(r"\s+", " ", clean)
    return clean[:80]


def load_qa_cache() -> Dict[str, Any]:
    """Loads universal Q&A cache."""
    if QA_CACHE_FILE.exists():
        try:
            with open(QA_CACHE_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return {}
    return {}


def save_qa_cache(cache: Dict[str, Any]):
    """Saves universal Q&A cache."""
    try:
        with open(QA_CACHE_FILE, "w", encoding="utf-8") as f:
            json.dump(cache, f, indent=2, ensure_ascii=False)
    except Exception as e:
        print(f"[!] Error saving QA cache: {e}")


def get_standard_answer(question_text: str) -> Optional[str]:
    """
    Returns standard candidate answers for universal questions in 0ms.
    """
    q = question_text.lower()

    if any(k in q for k in ["github"]):
        return CANDIDATE_GITHUB
    if any(k in q for k in ["linkedin"]):
        return CANDIDATE_LINKEDIN
    if any(k in q for k in ["portfolio", "website", "personal site"]):
        return CANDIDATE_GITHUB
    if any(k in q for k in ["authorized to work", "legally authorized", "work authorization", "legal right to work"]):
        return "Yes"
    if any(k in q for k in ["require sponsorship", "visa sponsorship", "need sponsorship"]):
        return "No"
    if any(k in q for k in ["preferred location", "locations in india", "location preference", "work location", "preferred work location", "office location"]):
        return ANS_ALL_INDIA_LOCATIONS
    if any(k in q for k in ["notice period", "availability", "when can you start", "earliest start"]):
        return "Immediately / 15-30 days"
    if any(k in q for k in ["current ctc", "current salary", "current compensation"]):
        return ANS_CURRENT_CTC
    if any(k in q for k in ["expected ctc", "expected salary", "salary expectations"]):
        return ANS_EXPECTED_CTC
    if any(k in q for k in ["years of experience", "total experience"]):
        return ANS_YEARS_OF_EXP
    if any(k in q for k in ["current company", "current employer", "current organization"]):
        return CANDIDATE_CURRENT_COMPANY
    if any(k in q for k in ["current title", "current role", "job title"]):
        return CANDIDATE_CURRENT_TITLE
    if any(k in q for k in ["university", "college", "school"]):
        return ANS_COLLEGE
    if any(k in q for k in ["degree", "highest degree"]):
        return ANS_DEGREE
    if any(k in q for k in ["major", "field of study", "specialization"]):
        return ANS_MAJOR
    if any(k in q for k in ["graduation year", "year of completion"]):
        return ANS_GRAD_YEAR
    if any(k in q for k in ["gpa", "cgpa"]):
        return ANS_CGPA
    if any(k in q for k in ["gender"]):
        return ANS_GENDER
    if any(k in q for k in ["preferred name", "nickname"]):
        return CANDIDATE_FIRST_NAME
    if any(k in q for k in ["pick date", "start date", "earliest start"]):
        import datetime
        return (datetime.date.today() + datetime.timedelta(days=7)).strftime("%Y-%m-%d")
    if any(k in q for k in ["additional information", "anything else"]):
        return ANS_PITCH_AI_ENGINEER

    return None


def resolve_questions_for_company(
    questions: List[Dict[str, Any]],
    company: str,
    job_title: str = "Software Engineer"
) -> Dict[str, str]:
    """
    Resolves answers for a list of form questions:
    1. Checks standard answers in 0ms.
    2. Checks company procedure cache.
    3. Checks universal Q&A cache.
    4. For remaining open-ended essay questions, batches them to ChatGPT Profile 1,
       receives grounded answers, and caches them for future use.

    questions format: [{'id': 'field_1', 'question': 'Why do you want to join?'}, ...]
    Returns: {'field_1': 'Answer text', ...}
    """
    comp_slug = _slugify(company)
    company_proc_file = PROCEDURES_DIR / f"{comp_slug}.json"

    company_proc: Dict[str, Any] = {}
    if company_proc_file.exists():
        try:
            with open(company_proc_file, "r", encoding="utf-8") as f:
                company_proc = json.load(f)
        except Exception:
            pass

    qa_cache = load_qa_cache()
    company_cached_answers = company_proc.get("question_answers", {})

    resolved_answers: Dict[str, str] = {}
    unanswered: List[Dict[str, Any]] = []

    for q_item in questions:
        q_id = q_item.get("id", "")
        q_text = q_item.get("question", "").strip()
        if not q_text:
            continue

        norm_key = _normalize_question_key(q_text)

        # 1. Check standard answers
        std_ans = get_standard_answer(q_text)
        if std_ans is not None:
            resolved_answers[q_id] = std_ans
            continue

        # 2. Check company cached answers
        if norm_key in company_cached_answers:
            resolved_answers[q_id] = company_cached_answers[norm_key]
            print(f"[*] Reused company-cached answer for: '{q_text[:40]}...'")
            continue

        # 3. Check universal Q&A cache
        if norm_key in qa_cache:
            resolved_answers[q_id] = qa_cache[norm_key]
            print(f"[*] Reused universal-cached answer for: '{q_text[:40]}...'")
            continue

        # Mark for dynamic ChatGPT consultation
        unanswered.append({"id": q_id, "question": q_text, "norm_key": norm_key})

    # If all answered, return immediately
    if not unanswered:
        return resolved_answers

    # Consult ChatGPT Profile 1 first (referencing memorized master dossier)
    print(f"[*] Consulting ChatGPT Profile 1 (referencing memorized master dossier) for {len(unanswered)} custom questions at {company}...")
    ai_answers: Dict[str, Any] = {}
    try:
        gpt_query = [{"id": u["id"], "question": u["question"]} for u in unanswered]
        ai_answers = ask_chatgpt_for_application_answers(
            questions=gpt_query,
            jd_text=f"Company: {company}, Role: {job_title}",
            scraped_context=f"Candidate: {CANDIDATE_NAME}, {ANS_COLLEGE}, {CANDIDATE_CURRENT_TITLE} at {CANDIDATE_CURRENT_COMPANY}"
        )
    except Exception as e:
        print(f"[!] Warning: ChatGPT consultation failed ({e}). Falling back to Gemini API pool...")

    # If ChatGPT didn't return all answers, fallback to Gemini API Pool
    missing = [u for u in unanswered if not ai_answers.get(u["id"])]
    if missing:
        print(f"[*] Fallback: Querying Gemini API Pool for {len(missing)} remaining questions at {company}...")
        gemini_query = [{"id": m["id"], "question": m["question"]} for m in missing]
        try:
            gemini_answers = query_questions_batch(
                questions=gemini_query,
                company=company,
                job_title=job_title
            )
            ai_answers.update(gemini_answers)
        except Exception as e:
            print(f"[!] Warning: Gemini batch query failed ({e})")

    # Cache the newly generated answers
    for u in unanswered:
        q_id = u["id"]
        norm_key = u["norm_key"]
        ans = ai_answers.get(q_id, "").strip()
        if ans:
            resolved_answers[q_id] = ans
            company_cached_answers[norm_key] = ans
            # Also cache universally if not company-specific
            if company.lower() not in u["question"].lower():
                qa_cache[norm_key] = ans

    # Save caches to disk
    save_qa_cache(qa_cache)
    company_proc["question_answers"] = company_cached_answers
    company_proc["last_updated"] = datetime.now().isoformat()
    try:
        with open(company_proc_file, "w", encoding="utf-8") as f:
            json.dump(company_proc, f, indent=2, ensure_ascii=False)
    except Exception as e:
        print(f"[!] Error saving company procedure cache: {e}")

    return resolved_answers


def record_company_procedure(
    company: str,
    ats_platform: str,
    url: str,
    fields_found: Optional[List[str]] = None,
    notes: str = ""
):
    """Records the discovered application structure for a company."""
    comp_slug = _slugify(company)
    company_proc_file = PROCEDURES_DIR / f"{comp_slug}.json"

    data = {}
    if company_proc_file.exists():
        try:
            with open(company_proc_file, "r", encoding="utf-8") as f:
                data = json.load(f)
        except Exception:
            pass

    data["company"] = company
    data["ats_platform"] = ats_platform
    data["last_url"] = url
    data["last_updated"] = datetime.now().isoformat()
    if fields_found:
        data["known_fields"] = sorted(list(set(data.get("known_fields", []) + fields_found)))
    if notes:
        data["notes"] = notes

    try:
        with open(company_proc_file, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
    except Exception as e:
        print(f"[!] Error recording company procedure: {e}")


if __name__ == "__main__":
    print("--- Testing Procedure Memory Engine ---")
    q_test = [
        {"id": "q1", "question": "Link to your GitHub profile"},
        {"id": "q2", "question": "Are you legally authorized to work in India?"},
        {"id": "q3", "question": "What is your earliest start date / notice period?"},
    ]
    answers = resolve_questions_for_company(q_test, "ElevenLabs", "Platform Engineer")
    for k, v in answers.items():
        print(f"[{k}] -> {v}")
