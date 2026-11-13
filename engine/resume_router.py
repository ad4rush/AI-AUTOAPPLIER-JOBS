#!/usr/bin/env python3
"""
Autonomous Resume Router.
Determines the optimal resume (tailored vs master archetype) for any job opening:
1. Elite FTE Roles (Tier 1/2: OpenAI, Anthropic, ElevenLabs, Cognition, Stripe, Microsoft, etc.):
   - Generates or retrieves Claude Sonnet 5.5 tailored 1-page PDF.
2. General Engineering Roles (High-volume speed):
   - Deterministically selects one of the 4 verified 1-page master resumes in 0ms:
     * RESUME_1_AI_ENGINEER.pdf (AI, ML, LLM, RAG, Computer Vision, Voice Agents)
     * RESUME_2_DATA_ENGINEER.pdf (Data Eng, Lakehouse, Kafka CDC, Spark, AWS Glue, Hudi)
     * RESUME_3_SWE_BACKEND.pdf (Backend, Systems, API, Microservices, Cloud, Distributed)
     * RESUME_4_GENERAL_ENGINEERING.pdf (Full Stack, Frontend, General SWE, Early Career)
"""

import os
import re
import sys
from pathlib import Path
from typing import Dict, Any, Optional

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

MASTER_RESUMES_DIR = PROJECT_ROOT / "master_resumes"
DATA_DIR = PROJECT_ROOT / "data"
TAILORED_DIR = DATA_DIR / "tailored_resumes"
TAILORED_DIR.mkdir(parents=True, exist_ok=True)

MASTER_RESUMES = {
    "AI_ENGINEER": MASTER_RESUMES_DIR / "RESUME_1_AI_ENGINEER.pdf",
    "DATA_ENGINEER": MASTER_RESUMES_DIR / "RESUME_2_DATA_ENGINEER.pdf",
    "SWE_BACKEND": MASTER_RESUMES_DIR / "RESUME_3_SWE_BACKEND.pdf",
    "GENERAL_ENGINEERING": MASTER_RESUMES_DIR / "RESUME_4_GENERAL_ENGINEERING.pdf",
}

ELITE_COMPANIES = {
    "openai", "anthropic", "elevenlabs", "cognition", "stripe", "microsoft",
    "google", "deepmind", "gitlab", "databricks", "scaleai", "scale ai", "brex",
    "vercel", "figma", "postman", "palantir", "atlassian", "spotify", "perplexity",
    "mistral", "cohere", "cursor", "anysphere", "modal", "replicate", "inngest",
    "linear", "ramp", "rippling", "notion"
}


def classify_master_archetype(title: str, jd_text: str = "") -> str:
    """
    Classifies the role into one of the 4 master resume archetypes in 0ms.
    """
    text = f"{title} {jd_text}".lower()

    # 1. AI / ML
    ai_keywords = [
        "ai engineer", "machine learning", "ml engineer", "llm", "deep learning",
        "nlp", "computer vision", "generative ai", "genai", "prompt", "rag",
        "agent", "agents", "nova sonic", "langchain", "llamaindex", "pytorch"
    ]
    if any(k in text for k in ai_keywords):
        return "AI_ENGINEER"

    # 2. Data Engineering
    data_keywords = [
        "data engineer", "etl", "lakehouse", "spark", "kafka", "glue",
        "hudi", "data warehouse", "data pipeline", "olap", "athena", "snowflake",
        "databricks", "big data", "hadoop", "flink", "dbt"
    ]
    if any(k in text for k in data_keywords):
        return "DATA_ENGINEER"

    # 3. Backend / Systems
    backend_keywords = [
        "backend", "back end", "systems engineer", "distributed systems",
        "infrastructure", "api engineer", "platform engineer", "cloud engineer",
        "golang", "python developer", "software engineer - backend", "core engineer"
    ]
    if any(k in text for k in backend_keywords):
        return "SWE_BACKEND"

    # 4. Fallback: General Engineering
    return "GENERAL_ENGINEERING"


def is_elite_company(company: str) -> bool:
    """Checks if the company is an elite Tier 1/2 organization."""
    comp_slug = re.sub(r"[^a-z0-9]", "", company.lower())
    for elite in ELITE_COMPANIES:
        if re.sub(r"[^a-z0-9]", "", elite) in comp_slug:
            return True
    return False


def get_master_resume_path(archetype: str) -> str:
    """Returns absolute path to verified master resume PDF."""
    path = MASTER_RESUMES.get(archetype, MASTER_RESUMES["GENERAL_ENGINEERING"])
    if path.exists():
        return str(path.resolve())
    # Fallback to any existing master PDF
    for fallback in MASTER_RESUMES.values():
        if fallback.exists():
            return str(fallback.resolve())
    return ""


def select_resume_for_job(
    company: str,
    title: str,
    jd_text: str = "",
    force_master: bool = False,
    force_tailor: bool = False
) -> Dict[str, Any]:
    """
    Selects or generates the optimal single-page PDF resume.
    Returns:
    {
        "resume_path": "/absolute/path/to/resume.pdf",
        "archetype": "AI_ENGINEER",
        "is_tailored": bool,
        "notes": str
    }
    """
    archetype = classify_master_archetype(title, jd_text)
    elite = is_elite_company(company)

    # If it's a general job or master is forced
    if (not elite and not force_tailor) or force_master:
        resume_path = get_master_resume_path(archetype)
        return {
            "resume_path": resume_path,
            "archetype": archetype,
            "is_tailored": False,
            "notes": f"Master Archetype: {archetype} (0ms dispatch)"
        }

    # For Elite FTE roles: Check if already tailored in TAILORED_DIR or RESUMES_GENERATED_DIR
    clean_company = re.sub(r"[^a-zA-Z0-9]", "", company)[:15].lower()
    clean_title = re.sub(r"[^a-zA-Z0-9]", "", title)[:15].lower()

    # Search in TAILORED_DIR
    cached = list(TAILORED_DIR.glob(f"*{clean_company}*.pdf"))
    if not cached:
        # Search in RESUMES_GENERATED_DIR
        gen_dir = PROJECT_ROOT / "resumes_generated"
        if gen_dir.exists():
            cached = list(gen_dir.glob(f"*{clean_company}*/*.pdf"))
            if not cached:
                cached = list(gen_dir.glob(f"*/*{clean_company}*.pdf"))

    if cached:
        return {
            "resume_path": str(cached[0].resolve()),
            "archetype": archetype,
            "is_tailored": True,
            "notes": f"Reused cached tailored resume: {cached[0].name}"
        }

    # Attempt dynamic Claude Sonnet 5.5 tailoring
    print(f"[*] Elite company detected ({company}). Attempting Claude Sonnet 5.5 tailoring...")
    try:
        from engine.claude_tailor import generate_tailored_resume_via_claude
        dummy_job_id = f"tailor_{clean_company.lower()}_{clean_title.lower()}"
        success, msg, tex_path, pdf_path = generate_tailored_resume_via_claude(
            job_id=dummy_job_id,
            company=company,
            title=title,
            jd=jd_text or title
        )
        if success and pdf_path and Path(pdf_path).exists():
            return {
                "resume_path": str(Path(pdf_path).resolve()),
                "archetype": archetype,
                "is_tailored": True,
                "notes": f"Dynamically tailored via Claude 3.5: {Path(pdf_path).name}"
            }
        else:
            print(f"[!] Claude tailoring yielded no PDF ({msg}). Falling back to master {archetype}...")
    except Exception as e:
        print(f"[!] Claude tailoring exception: {e}. Falling back to master {archetype}...")

    # Safe fallback to verified master archetype PDF
    resume_path = get_master_resume_path(archetype)
    return {
        "resume_path": resume_path,
        "archetype": archetype,
        "is_tailored": False,
        "notes": f"Master Archetype fallback: {archetype}"
    }


if __name__ == "__main__":
    test_cases = [
        ("ElevenLabs", "Platform Engineer", "Distributed systems, low latency voice pipelines"),
        ("Cognition", "Applied AI Engineer", "LLM reasoning, coding agents, prompt optimization"),
        ("Razorpay", "Senior Data Engineer", "Spark, Kafka, Lakehouse CDC pipelines"),
        ("Swiggy", "Software Development Engineer 1", "Java, Go, REST APIs, Microservices"),
        ("Zomato", "Frontend Engineer", "React, TypeScript, Next.js"),
    ]
    print("--- Testing Resume Router ---")
    for comp, tit, jd in test_cases:
        res = select_resume_for_job(comp, tit, jd, force_master=True)
        print(f"[{comp}] '{tit}' -> {Path(res['resume_path']).name} ({res['notes']})")
