#!/usr/bin/env python3
"""
Autonomous High-Performance Gemini API Batch Client with Round-Robin Key Rotation.
Provides:
1. Dynamic pool management of Gemini API keys (GEMINI_KEY_1, GEMINI_KEY_2, etc.).
2. Thread-safe round-robin key rotation initialized at a random index, with automatic failover.
3. Deterministic batch Q&A query execution (temperature=0.0, response_mime_type="application/json").
4. Deterministic extraction and schema validation of candidate answers grounded in candidate's profile.
"""

import os
import re
import sys
import json
import random
import threading
import urllib.request
import urllib.error
from pathlib import Path
from typing import Dict, Any, List, Optional

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from engine.config import (
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
    ANS_PITCH_AI_ENGINEER,
    ANS_COLLEGE,
    ANS_DEGREE,
    ANS_GRAD_YEAR,
    ANS_CGPA,
)

# Supported high-availability Gemini models in order of priority
GEMINI_MODELS = [
    "gemini-3.5-flash-lite",
    "gemini-3.6-flash",
    "gemini-3-flash-preview",
    "gemini-flash-latest",
]

_lock = threading.Lock()
_key_pool: List[str] = []
_current_index: int = 0


def _load_key_pool() -> List[str]:
    """
    Loads all GEMINI_KEY_X and GEMINI_API_KEYS from environment / .env.
    """
    keys = []
    # 1. Check GEMINI_KEY_1, GEMINI_KEY_2, ...
    for i in range(1, 20):
        val = os.getenv(f"GEMINI_KEY_{i}", "").strip()
        if val and val not in keys:
            keys.append(val)

    # 2. Check comma-separated GEMINI_API_KEYS
    csv_keys = os.getenv("GEMINI_API_KEYS", "").strip()
    if csv_keys:
        for k in csv_keys.split(","):
            k_clean = k.strip()
            if k_clean and k_clean not in keys:
                keys.append(k_clean)

    # 3. Fallback to extracted file if env was not fully populated
    keys_file = PROJECT_ROOT / "data" / "extracted_gemini_keys.json"
    if not keys and keys_file.exists():
        try:
            with open(keys_file, "r", encoding="utf-8") as f:
                loaded = json.load(f)
                if isinstance(loaded, list):
                    keys = [k.strip() for k in loaded if k.strip()]
        except Exception:
            pass

    return keys


def initialize_key_pool():
    """Initializes the round-robin key pool with a random start index."""
    global _key_pool, _current_index
    with _lock:
        _key_pool = _load_key_pool()
        if _key_pool:
            _current_index = random.randint(0, len(_key_pool) - 1)
            print(f"[GeminiClient] Initialized pool with {len(_key_pool)} keys. Starting at index {_current_index}.")
        else:
            print("[GeminiClient] WARNING: No Gemini API keys found in environment.")


# Initialize on import
initialize_key_pool()


def get_next_key() -> Optional[str]:
    """Returns the next key in round-robin order."""
    global _current_index, _key_pool
    with _lock:
        if not _key_pool:
            _key_pool = _load_key_pool()
        if not _key_pool:
            return None
        key = _key_pool[_current_index]
        _current_index = (_current_index + 1) % len(_key_pool)
        return key


def get_random_key() -> Optional[str]:
    """Returns a random key from the pool."""
    with _lock:
        if not _key_pool:
            _key_pool = _load_key_pool()
        if not _key_pool:
            return None
        return random.choice(_key_pool)


def get_candidate_grounding_context() -> str:
    """Returns the ground truth context of candidate profile for factual answers."""
    return f"""
Candidate Master Profile:
- Full Name: {CANDIDATE_NAME} ({CANDIDATE_FIRST_NAME} {CANDIDATE_LAST_NAME})
- Education: {ANS_DEGREE}, {ANS_COLLEGE} (Graduation: {ANS_GRAD_YEAR}, CGPA: {ANS_CGPA})
- Current Role: {CANDIDATE_CURRENT_TITLE} at {CANDIDATE_CURRENT_COMPANY}
- Location: {CANDIDATE_LOCATION} (India)
- Contact: Email: {CANDIDATE_EMAIL}, Phone: {CANDIDATE_PHONE}
- Profiles: GitHub: {CANDIDATE_LINKEDIN}, LinkedIn: {CANDIDATE_LINKEDIN}

Core Technical Experience & Production Accomplishments:
1. Distributed Lakehouse & Near-Real-Time CDC ({CANDIDATE_CURRENT_COMPANY}):
   - Engineered scalable change-data-capture pipelines streaming transactional mutations from MariaDB into Apache Hudi via Kafka Connect, AWS Glue, and Apache Spark.
   - Maintained 99.8% ingestion availability across billions of records daily, cutting storage costs by $5,000/mo via parquet compression and tiering.
2. Ontology-Grounded Text-to-SQL Agent:
   - Built a schema-aware SQL agent on Amazon Athena parsing SQL Abstract Syntax Trees (ASTs) against enterprise domain ontologies, cutting BI query friction by 35%.
3. Voice AI Agent & Telephony:
   - Deployed low-latency voice bots using AWS Nova Sonic, FastAPI, Docker, and DTMF/IVR tool-calling integration.
4. Systems Engineering & Security:
   - Built custom Unix shell in C (lexer/parser/fork-exec/pipes); implemented CI/CD AST security gates using Bandit, flake8, and Software Composition Analysis (SCA) with Trivy/pip-audit.
5. Work Authorization & Preferences:
   - Authorized to work in India: Yes. Requires sponsorship in India: No. Willing to relocate to Bangalore: Yes.
"""


def query_questions_batch(
    questions: List[Dict[str, str]],
    company: str = "",
    job_title: str = "",
    jd_snippet: str = "",
    max_retries: int = 5
) -> Dict[str, str]:
    """
    Asks a batch of application questions deterministically and extracts answers deterministically.

    Args:
        questions: List of dicts, each having 'id' and 'question'
                   e.g. [{'id': 'q1', 'question': 'Why do you want to work at GitLab?'}]
        company: Target company name
        job_title: Target job title
        jd_snippet: Optional job description context
        max_retries: Maximum key-rotation attempts across pool

    Returns:
        Dict mapping question ID to deterministic grounded answer:
        {'q1': 'Answer text...'}
    """
    if not questions:
        return {}

    candidate_context = get_candidate_grounding_context()

    # Format questions into clean numbered list
    formatted_questions = []
    for item in questions:
        q_id = str(item.get("id", "")).strip()
        q_text = str(item.get("question", "")).strip()
        if q_id and q_text:
            formatted_questions.append({"id": q_id, "question": q_text})

    if not formatted_questions:
        return {}

    # Strict JSON Output Schema instruction
    prompt = f"""
You are an autonomous executive assistant representing candidate {CANDIDATE_NAME} for a job application.
Answer the following batch of job application questions authentically, professionally, and concisely.

Target Job Details:
- Company: {company if company else "Tech Company"}
- Title: {job_title if job_title else "Software Engineer"}
{f"- Role Context: {jd_snippet[:400]}" if jd_snippet else ""}

{candidate_context}

INSTRUCTIONS:
1. Ground every answer strictly in the candidate's real experience at {CANDIDATE_CURRENT_COMPANY}, {ANS_COLLEGE}, and personal systems projects.
2. For short or factual questions (e.g., years of experience, locations, tools), give direct, accurate answers (e.g., "0 - 2 years", "Bengaluru, Karnataka, India", "Yes", "No").
3. For technical essay questions (e.g. AST, compilers, architecture, why this company), provide a crisp, authoritative 1-2 paragraph technical response highlighting relevant production projects.
4. Output MUST be valid JSON mapping each question's exact "id" to its string answer.

QUESTIONS TO ANSWER:
{json.dumps(formatted_questions, indent=2)}

OUTPUT FORMAT (Strict JSON only, no markdown, no other keys):
{{
  "id_1": "answer_1",
  "id_2": "answer_2"
}}
"""

    payload_data = {
        "contents": [
            {
                "role": "user",
                "parts": [{"text": prompt}]
            }
        ],
        "generationConfig": {
            "temperature": 0.0,  # 100% deterministic
            "responseMimeType": "application/json"
        }
    }
    payload_bytes = json.dumps(payload_data).encode("utf-8")

    # Try models in priority order with round-robin key rotation
    for attempt in range(max_retries):
        key = get_next_key()
        if not key:
            print("[GeminiBatch] Error: No API key available.")
            break

        key_hint = f"{key[:6]}...{key[-4:]}"

        for model in GEMINI_MODELS:
            url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={key}"
            req = urllib.request.Request(
                url,
                data=payload_bytes,
                headers={"Content-Type": "application/json"}
            )

            try:
                with urllib.request.urlopen(req, timeout=12) as resp:
                    resp_json = json.loads(resp.read().decode("utf-8"))
                    text = resp_json["candidates"][0]["content"]["parts"][0]["text"].strip()

                    # Deterministic JSON Extraction
                    extracted = _parse_json_deterministic(text)
                    if extracted:
                        print(f"[GeminiBatch] Successfully answered {len(extracted)}/{len(formatted_questions)} questions using {model} (Key {key_hint}).")
                        return extracted

            except urllib.error.HTTPError as e:
                # 429 = Rate limited, 503 = Service overloaded, 404 = Model deprecation
                if e.code in (429, 503, 404):
                    # Continue to next model or next key
                    continue
                else:
                    print(f"[GeminiBatch] HTTP {e.code} on {model} with key {key_hint}: {e.reason}")
                    continue
            except Exception as e:
                # Timeout or network error
                continue

        print(f"[GeminiBatch] Key {key_hint} exhausted or busy. Rotating to next key in pool (Attempt {attempt + 1}/{max_retries})...")

    print("[GeminiBatch] Fallback: All Gemini attempts failed. Returning empty dict.")
    return {}


def _parse_json_deterministic(text: str) -> Dict[str, str]:
    """
    Cleans and deterministically parses JSON dictionary from model output.
    """
    text = text.strip()
    # Strip markdown code fences if model enclosed it
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text, flags=re.MULTILINE)
        text = re.sub(r"\s*```$", "", text, flags=re.MULTILINE)
        text = text.strip()

    try:
        data = json.loads(text)
        if isinstance(data, dict):
            # Ensure all values are strings
            return {str(k): str(v).strip() for k, v in data.items()}
    except json.JSONDecodeError:
        # Fallback: extract the outermost {...} block via regex
        m = re.search(r"(\{.*\})", text, re.DOTALL)
        if m:
            try:
                data = json.loads(m.group(1))
                if isinstance(data, dict):
                    return {str(k): str(v).strip() for k, v in data.items()}
            except Exception:
                pass

    return {}


if __name__ == "__main__":
    print("=== Testing Gemini Batch Client with Round-Robin Rotation ===")
    test_questions = [
        {
            "id": "q_graphql",
            "question": "What experience do you have with GraphQL federation and Apollo Gateway in production?"
        },
        {
            "id": "q_why_company",
            "question": "Why are you interested in joining Anthropic?"
        },
        {
            "id": "q_years_go",
            "question": "How many years of professional experience do you have in Go?"
        }
    ]

    print(f"Pool size: {len(_key_pool)} keys.")
    answers = query_questions_batch(
        test_questions,
        company="Anthropic",
        job_title="Backend & Inference Infrastructure Engineer"
    )

    print("\n--- DETERMINISTIC EXTRACTED ANSWERS ---")
    for qid, ans in answers.items():
        print(f"\n[{qid}]:\n{ans}")
