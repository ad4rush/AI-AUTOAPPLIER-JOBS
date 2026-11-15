#!/usr/bin/env python3
"""
Autonomous Resume Router.
Determines the optimal resume (tailored vs master archetype) for any job opening:
1. Custom Tailored Resumes:
   - Reuses or compiles dedicated 1-page LaTeX resumes for company/job from resumes_generated/ or Claude/ChatGPT.
2. Domain-Specialized Master Archetypes:
   - AI_ENGINEER: RESUME_1_AI_ENGINEER.pdf (AI, ML, LLM, RAG, Computer Vision, Voice Agents, Speech)
   - DATA_ENGINEER: RESUME_2_DATA_ENGINEER.pdf (Data Eng, Lakehouse, Kafka CDC, Spark, AWS Glue, Hudi, ETL, BI)
   - SWE_BACKEND: RESUME_3_SWE_BACKEND.pdf (Backend, Systems, Distributed Systems, Go, Python, APIs, Cloud)
   - GENERAL_ENGINEERING: RESUME_4_GENERAL_ENGINEERING.pdf (Non-technical / General SWE fallback only)
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
RESUMES_GENERATED_DIR = PROJECT_ROOT / "resumes_generated"
RESUMES_GENERATED_DIR.mkdir(parents=True, exist_ok=True)

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
    "linear", "ramp", "rippling", "notion", "supabase", "cloudflare", "apple"
}


def classify_master_archetype(title: str, jd_text: str = "") -> str:
    """
    Classifies the role into one of the specialized master resume archetypes in 0ms.
    Guarantees that technical roles map to AI, Data, or Backend (never generic).
    """
    clean_title = (title or "").lower()
    clean_jd = (jd_text or "").lower()
    text = f"{clean_title} {clean_jd}"

    # 1. AI / ML / LLMs / Agents / Computer Vision / NLP / Speech
    ai_keywords = [
        "ai", "artificial intelligence", "machine learning", "ml", "llm", "vlm",
        "deep learning", "nlp", "computer vision", "generative ai", "genai",
        "prompt", "rag", "agent", "agents", "nova sonic", "langchain", "llamaindex",
        "pytorch", "tensorflow", "applied scientist", "data scientist", "research engineer",
        "speech", "audio", "nlp engineer", "model evaluation", "fine-tuning", "lora"
    ]
    # Check title first with word boundaries or substring
    for k in ai_keywords:
        pattern = r"\b" + re.escape(k) + r"\b"
        if re.search(pattern, clean_title):
            return "AI_ENGINEER"
    # Check JD if title is generic
    if any(k in text for k in ["generative ai", "rag", "llm", "agentic", "nova sonic", "pytorch", "huggingface"]):
        return "AI_ENGINEER"

    # 2. Data Engineering / Lakehouse / Streaming / ETL
    data_keywords = [
        "data engineer", "data engineering", "etl", "lakehouse", "spark", "kafka",
        "glue", "hudi", "data warehouse", "data pipeline", "olap", "athena",
        "snowflake", "databricks", "big data", "hadoop", "flink", "dbt",
        "bi engineer", "business intelligence", "data platform", "database engineer",
        "analytics engineer"
    ]
    for k in data_keywords:
        pattern = r"\b" + re.escape(k) + r"\b"
        if re.search(pattern, clean_title) or k in clean_title:
            return "DATA_ENGINEER"
    if any(k in text for k in ["lakehouse", "apache spark", "kafka cdc", "debezium", "apache hudi", "aws glue"]):
        return "DATA_ENGINEER"

    # 3. Backend / Systems / Microservices / Distributed Systems / Python / Go / SDE
    backend_keywords = [
        "backend", "back end", "systems engineer", "distributed systems",
        "infrastructure", "api engineer", "platform engineer", "cloud engineer",
        "golang", "python developer", "python engineer", "software engineer",
        "sde", "developer", "core engineer", "microservices", "full stack",
        "engineer", "fullstack", "software developer", "site reliability", "devops"
    ]
    for k in backend_keywords:
        pattern = r"\b" + re.escape(k) + r"\b"
        if re.search(pattern, clean_title) or k in clean_title:
            return "SWE_BACKEND"

    # 4. Technical default: SWE_BACKEND (Adarsh's core engineering strength)
    return "SWE_BACKEND"


def is_elite_company(company: str) -> bool:
    """Checks if the company is an elite Tier 1/2 organization."""
    comp_slug = re.sub(r"[^a-z0-9]", "", (company or "").lower())
    for elite in ELITE_COMPANIES:
        if re.sub(r"[^a-z0-9]", "", elite) in comp_slug:
            return True
    return False


def get_master_resume_path(archetype: str) -> str:
    """Returns absolute path to verified master resume PDF."""
    path = MASTER_RESUMES.get(archetype, MASTER_RESUMES["SWE_BACKEND"])
    if path.exists():
        return str(path.resolve())
    for fallback in MASTER_RESUMES.values():
        if fallback.exists():
            return str(fallback.resolve())
    return ""


def is_resume_cross_contaminated(resume_file: str, company: str) -> bool:
    """Returns True if resume path explicitly references a different elite/known company name."""
    clean_co = re.sub(r"[^a-zA-Z0-9]", "", company or "").lower()
    if not clean_co or clean_co in ("targetcompany", "techcompany", "remote", "linkedinjob"):
        return False
    path_lower = str(resume_file).lower()
    for other in ELITE_COMPANIES:
        if other != clean_co and len(other) > 3:
            if f"_{other}_" in path_lower or f"/{other}_" in path_lower or f"resume_{other}" in path_lower:
                return True
    return False


def select_resume_for_job(
    company: str,
    title: str,
    jd_text: str = "",
    job_id: str = "",
    force_master: bool = False,
    force_tailor: bool = False
) -> Dict[str, Any]:
    """
    Selects or generates the optimal single-page PDF resume.
    1. Checks if a dedicated tailored PDF already exists in jobs.db or resumes_generated/.
    2. If elite or force_tailor: compiles a dedicated single-page tailored PDF.
    3. Otherwise, deterministically returns the exact specialized master archetype:
       - AI_ENGINEER -> RESUME_1_AI_ENGINEER.pdf
       - DATA_ENGINEER -> RESUME_2_DATA_ENGINEER.pdf
       - SWE_BACKEND -> RESUME_3_SWE_BACKEND.pdf
    """
    archetype = classify_master_archetype(title, jd_text)
    clean_company = re.sub(r"[^a-zA-Z0-9]", "", company or "")[:15].lower()
    clean_job_id = re.sub(r"[^a-zA-Z0-9]", "", job_id or "")[:15].lower()

    # Step 1: Check jobs.db for tailored_resume_dir
    if job_id:
        try:
            from engine.db import get_db_connection
            conn = get_db_connection()
            c = conn.cursor()
            c.execute("SELECT tailored_resume_dir, raw_jd_path, title FROM jobs WHERE job_id = ? OR url LIKE ?", (job_id, f"%{job_id}%"))
            row = c.fetchone()
            conn.close()
            if row and row["tailored_resume_dir"]:
                t_dir = Path(row["tailored_resume_dir"])
                cand_pdf = None
                if t_dir.is_file() and t_dir.suffix.lower() == ".pdf" and t_dir.exists():
                    cand_pdf = t_dir
                elif t_dir.is_dir() and t_dir.exists():
                    pdfs = list(t_dir.glob("*.pdf"))
                    if pdfs:
                        cand_pdf = pdfs[0]
                if cand_pdf and not is_resume_cross_contaminated(str(cand_pdf), clean_company):
                    return {
                        "resume_path": str(cand_pdf.resolve()),
                        "archetype": archetype,
                        "is_tailored": True,
                        "notes": f"Database matched tailored resume: {cand_pdf.name}"
                    }
        except Exception:
            pass

    # Step 2: Check cached tailored resumes in resumes_generated/ or data/tailored_resumes/
    if clean_company and clean_company not in ("targetcompany", "linkedinjob", "techcompany", "remote"):
        # Search resumes_generated
        matches = list(RESUMES_GENERATED_DIR.glob(f"*{clean_company}*/*.pdf"))
        if not matches:
            matches = list(RESUMES_GENERATED_DIR.glob(f"*{clean_company}*.pdf"))
        if not matches:
            matches = list(TAILORED_DIR.glob(f"*{clean_company}*.pdf"))
        if matches:
            return {
                "resume_path": str(matches[0].resolve()),
                "archetype": archetype,
                "is_tailored": True,
                "notes": f"Reused cached tailored resume: {matches[0].name}"
            }

    # Step 3: If elite or force_tailor, attempt Claude Sonnet 3.5 or dedicated archetype compilation
    elite = is_elite_company(company)
    if (elite or force_tailor) and not force_master:
        print(f"[*] High-priority company detected ({company}). Generating dedicated tailored resume...")
        try:
            from engine.claude_tailor import generate_tailored_resume_via_claude, select_specialization_resume, inject_candidate_profile
            from engine.resume_ats_sanitizer import compile_and_guarantee_single_page

            target_id = job_id or f"tailor_{clean_company}_{int(os.getpid())}"
            t_ok, t_msg, _, t_pdf = generate_tailored_resume_via_claude(
                job_id=target_id,
                company=company,
                title=title,
                jd=jd_text or title
            )
            if t_ok and t_pdf and Path(t_pdf).exists():
                return {
                    "resume_path": str(Path(t_pdf).resolve()),
                    "archetype": archetype,
                    "is_tailored": True,
                    "notes": f"Dynamically tailored via Claude: {Path(t_pdf).name}"
                }
        except Exception as e:
            print(f"[!] Claude tailoring fallback ({e}). Using specialized master archetype...")

    # Step 4: Deterministic Specialized Master Archetype
    resume_path = get_master_resume_path(archetype)
    return {
        "resume_path": resume_path,
        "archetype": archetype,
        "is_tailored": False,
        "notes": f"Master Archetype: {archetype} ({Path(resume_path).name})"
    }


def resolve_resume_and_metadata(
    company: Optional[str] = None,
    title: Optional[str] = None,
    jd_text: Optional[str] = None,
    job_id: Optional[str] = None,
    resume_path: Optional[str] = None,
    url: Optional[str] = None,
    force_master: bool = False,
    force_tailor: bool = False
) -> Dict[str, Any]:
    """
    Unified metadata and resume resolver:
    1. If resume_path exists on disk, verifies and uses it.
    2. Recovers missing company, title, jd_text, or tailored_resume_dir from jobs.db using job_id or url.
    3. Calls select_resume_for_job(...) with complete context.
    4. Returns dict with: resume_path, company, title, jd_text, archetype, is_tailored, notes.
    """
    eff_comp = (company or "").strip()
    eff_title = (title or "").strip()
    eff_jd = (jd_text or "").strip()
    clean_url = (url or "").strip()

    # Step A: Query jobs.db if any key metadata is missing
    if (not eff_comp or not eff_title or not eff_jd or not resume_path) and (job_id or clean_url):
        try:
            from engine.db import get_db_connection
            conn = get_db_connection()
            c = conn.cursor()
            query_key = job_id or clean_url
            c.execute(
                "SELECT job_id, company, title, raw_jd_path, tailored_resume_dir, url FROM jobs WHERE job_id = ? OR url = ? OR url LIKE ? LIMIT 1",
                (query_key, clean_url, f"%{clean_url}%" if clean_url else query_key)
            )
            row = c.fetchone()
            conn.close()
            if row:
                if not eff_comp and row["company"]:
                    eff_comp = row["company"]
                if not eff_title and row["title"]:
                    eff_title = row["title"]
                if not job_id and row["job_id"]:
                    job_id = row["job_id"]
                if not resume_path and row["tailored_resume_dir"]:
                    t_cand = Path(row["tailored_resume_dir"])
                    cand_path = ""
                    if t_cand.is_file() and t_cand.suffix.lower() == ".pdf" and t_cand.exists():
                        cand_path = str(t_cand.resolve())
                    elif t_cand.is_dir() and t_cand.exists():
                        pdfs = list(t_cand.glob("*.pdf"))
                        if pdfs:
                            cand_path = str(pdfs[0].resolve())
                    if cand_path and not is_resume_cross_contaminated(cand_path, eff_comp):
                        resume_path = cand_path
                if not eff_jd and row["raw_jd_path"] and Path(row["raw_jd_path"]).exists():
                    try:
                        with open(row["raw_jd_path"], "r", encoding="utf-8") as f:
                            eff_jd = f.read()
                    except Exception:
                        pass
        except Exception:
            pass

    # Step B: If resume_path was provided or found in DB and exists
    if resume_path and Path(resume_path).exists() and not is_resume_cross_contaminated(resume_path, eff_comp):
        eff_title = eff_title or "Software Engineer"
        arch = classify_master_archetype(eff_title, eff_jd)
        return {
            "resume_path": str(Path(resume_path).resolve()),
            "company": eff_comp or "Target Company",
            "title": eff_title,
            "jd_text": eff_jd,
            "archetype": arch,
            "is_tailored": True,
            "notes": f"Verified resume file: {Path(resume_path).name}"
        }

    # Step C: Fallback to intelligent archetype/tailored resume selection
    routed = select_resume_for_job(
        company=eff_comp or "Target Company",
        title=eff_title or "Software Engineer",
        jd_text=eff_jd,
        job_id=job_id or "",
        force_master=force_master,
        force_tailor=force_tailor
    )
    routed["company"] = eff_comp or "Target Company"
    routed["title"] = eff_title or "Software Engineer"
    routed["jd_text"] = eff_jd
    return routed



if __name__ == "__main__":
    test_cases = [
        ("Opkey", "AI Engineer – LLM / VLM", "LLM fine-tuning, RAG, voice agents"),
        ("Schneider Electric", "Data Scientist – Generative AI & ML", "Generative AI models"),
        ("Deloitte", "Python Developer", "Python, FastAPI, microservices, Docker"),
        ("BlueOptima", "Machine Learning Data Engineer", "ETL, Spark, Kafka, ML pipelines"),
        ("Supabase", "AI Platform Engineer", "Postgres, pgvector, Edge Functions, LLM execution"),
        ("Generic", "Software Engineer", "Core systems development"),
    ]
    print("--- Testing Enhanced Resume Router ---")
    for comp, tit, jd in test_cases:
        res = select_resume_for_job(comp, tit, jd, force_master=True)
        print(f"[{comp}] '{tit}' -> Archetype: {res['archetype']} | File: {Path(res['resume_path']).name}")
