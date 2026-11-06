import re
from pathlib import Path
from typing import Dict, Any, List, Tuple
from engine.config import classify_company_tier, MASTER_PROFILE_PATH, is_location_allowed
from engine.db import update_job_status, get_jobs_by_status

def load_master_profile_text() -> str:
    if MASTER_PROFILE_PATH.exists():
        with open(MASTER_PROFILE_PATH, "r", encoding="utf-8") as f:
            return f.read()
    return ""

# Precision Skill Taxonomy: Grouped with exact word boundaries and relevance weights
# Adarsh's Core Specialties: AI/LLM Systems, Lakehouse Data Engineering, Backend Python & Distributed Systems
WEIGHTED_SKILLS = {
    "genai_llm_agents": {
        "weight": 3,
        "skills": [
            r"\bllms?\b", r"\blarge language models?\b", r"\brag\b", r"\bretrieval augmented generation\b",
            r"\bagents?\b", r"\bagentic\b", r"\bmulti-agent\b", r"\bmcp\b", r"\bmodel context protocol\b",
            r"\bprompt caching\b", r"\btext-to-sql\b", r"\bnova sonic\b", r"\blangchain\b", r"\bllamaindex\b",
            r"\bvllm\b", r"\bvector (?:database|db|store)\b", r"\bpinecone\b", r"\bqdrant\b", r"\bchromadb\b",
            r"\bfaiss\b", r"\bfine-tuning\b", r"\blora\b", r"\bpeft\b", r"\bquantization\b",
            r"\btool calling\b", r"\bfunction calling\b", r"\bconversational ai\b", r"\bprompt engineering\b"
        ]
    },
    "lakehouse_data_engineering": {
        "weight": 3,
        "skills": [
            r"\bapache spark\b", r"\bpyspark\b", r"\bspark\b", r"\baws glue\b", r"\bglue\b",
            r"\bapache kafka\b", r"\bkafka\b", r"\bdebezium\b", r"\bcdc\b", r"\bchange data capture\b",
            r"\bapache hudi\b", r"\bhudi\b", r"\bdelta lake\b", r"\biceberg\b", r"\bparquet\b",
            r"\bamazon athena\b", r"\bathena\b", r"\blakehouse\b", r"\bdata lake\b", r"\betl\b",
            r"\belt\b", r"\bdata pipelines?\b", r"\bstreaming\b", r"\bdata warehousing?\b", r"\bbig data\b"
        ]
    },
    "ml_deep_learning": {
        "weight": 2.5,
        "skills": [
            r"\bpytorch\b", r"\btensorflow\b", r"\btransformers?\b", r"\bhugging\s*face\b",
            r"\bscikit-learn\b", r"\bsklearn\b", r"\bxgboost\b", r"\blightgbm\b",
            r"\bnlp\b", r"\bnatural language processing\b", r"\bcomputer vision\b", r"\bdeep learning\b",
            r"\bembeddings?\b", r"\bsemantic search\b"
        ]
    },
    "backend_distributed_systems": {
        "weight": 2.5,
        "skills": [
            r"\bpython\b", r"\bfastapi\b", r"\bdjango\b", r"\bflask\b", r"\brest(?:ful)? apis?\b",
            r"\bmicroservices\b", r"\bdocker\b", r"\bkubernetes\b", r"\bk8s\b", r"\baws\b",
            r"\bamazon web services\b", r"\bs3\b", r"\bdynamodb\b", r"\baws lambda\b", r"\becs\b",
            r"\bec2\b", r"\bcloudwatch\b", r"\bgcp\b", r"\bgoogle cloud\b", r"\bredis\b",
            r"\bpostgresql\b", r"\bpostgres\b", r"\bmysql\b", r"\bsql\b", r"\bnosql\b",
            r"\blinux\b", r"\bdistributed systems?\b", r"\bgrpc\b", r"\bc\+\+\b",
            r"\b(?:ansi\s+c|c\s+programming|c\s+language)\b", r"\bgolang\b", r"\bgo\b"
        ]
    },
    "cs_core_algorithms": {
        "weight": 2,
        "skills": [
            r"\bdata structures\b", r"\balgorithms\b", r"\bsystem design\b",
            r"\bconcurrency\b", r"\bmultithreading\b", r"\boperating systems\b"
        ]
    }
}

# Display name map for matched skill regex patterns
PATTERN_DISPLAY_NAMES = {
    r"\bllms?\b": "LLM",
    r"\blarge language models?\b": "LLM",
    r"\brag\b": "RAG",
    r"\bretrieval augmented generation\b": "RAG",
    r"\bagents?\b": "Agents",
    r"\bagentic\b": "Agentic AI",
    r"\bmulti-agent\b": "Multi-Agent",
    r"\bmcp\b": "MCP",
    r"\bmodel context protocol\b": "MCP",
    r"\bprompt caching\b": "Prompt Caching",
    r"\btext-to-sql\b": "Text-to-SQL",
    r"\bnova sonic\b": "Nova Sonic",
    r"\blangchain\b": "LangChain",
    r"\bllamaindex\b": "LlamaIndex",
    r"\bvllm\b": "vLLM",
    r"\bvector (?:database|db|store)\b": "Vector DB",
    r"\bpinecone\b": "Pinecone",
    r"\bqdrant\b": "Qdrant",
    r"\bchromadb\b": "ChromaDB",
    r"\bfaiss\b": "FAISS",
    r"\bfine-tuning\b": "Fine-Tuning",
    r"\blora\b": "LoRA",
    r"\bpeft\b": "PEFT",
    r"\bquantization\b": "Quantization",
    r"\btool calling\b": "Tool Calling",
    r"\bfunction calling\b": "Function Calling",
    r"\bconversational ai\b": "Conversational AI",
    r"\bprompt engineering\b": "Prompt Engineering",
    r"\bapache spark\b": "Apache Spark",
    r"\bpyspark\b": "PySpark",
    r"\bspark\b": "Spark",
    r"\baws glue\b": "AWS Glue",
    r"\bglue\b": "AWS Glue",
    r"\bapache kafka\b": "Kafka",
    r"\bkafka\b": "Kafka",
    r"\bdebezium\b": "Debezium",
    r"\bcdc\b": "CDC",
    r"\bchange data capture\b": "CDC",
    r"\bapache hudi\b": "Apache Hudi",
    r"\bhudi\b": "Hudi",
    r"\bdelta lake\b": "Delta Lake",
    r"\biceberg\b": "Apache Iceberg",
    r"\bparquet\b": "Parquet",
    r"\bamazon athena\b": "Amazon Athena",
    r"\bathena\b": "Athena",
    r"\blakehouse\b": "Lakehouse",
    r"\bdata lake\b": "Data Lake",
    r"\betl\b": "ETL",
    r"\belt\b": "ELT",
    r"\bdata pipelines?\b": "Data Pipelines",
    r"\bstreaming\b": "Streaming",
    r"\bdata warehousing?\b": "Data Warehouse",
    r"\bbig data\b": "Big Data",
    r"\bpytorch\b": "PyTorch",
    r"\btensorflow\b": "TensorFlow",
    r"\btransformers?\b": "Transformers",
    r"\bhugging\s*face\b": "HuggingFace",
    r"\bscikit-learn\b": "Scikit-Learn",
    r"\bsklearn\b": "Scikit-Learn",
    r"\bxgboost\b": "XGBoost",
    r"\blightgbm\b": "LightGBM",
    r"\bnlp\b": "NLP",
    r"\bnatural language processing\b": "NLP",
    r"\bcomputer vision\b": "Computer Vision",
    r"\bdeep learning\b": "Deep Learning",
    r"\bembeddings?\b": "Embeddings",
    r"\bsemantic search\b": "Semantic Search",
    r"\bpython\b": "Python",
    r"\bfastapi\b": "FastAPI",
    r"\bdjango\b": "Django",
    r"\bflask\b": "Flask",
    r"\brest(?:ful)? apis?\b": "REST API",
    r"\bmicroservices\b": "Microservices",
    r"\bdocker\b": "Docker",
    r"\bkubernetes\b": "Kubernetes",
    r"\bk8s\b": "Kubernetes",
    r"\baws\b": "AWS",
    r"\bamazon web services\b": "AWS",
    r"\bs3\b": "AWS S3",
    r"\bdynamodb\b": "DynamoDB",
    r"\baws lambda\b": "AWS Lambda",
    r"\becs\b": "AWS ECS",
    r"\bec2\b": "AWS EC2",
    r"\bcloudwatch\b": "CloudWatch",
    r"\bgcp\b": "GCP",
    r"\bgoogle cloud\b": "GCP",
    r"\bredis\b": "Redis",
    r"\bpostgresql\b": "PostgreSQL",
    r"\bpostgres\b": "PostgreSQL",
    r"\bmysql\b": "MySQL",
    r"\bsql\b": "SQL",
    r"\bnosql\b": "NoSQL",
    r"\blinux\b": "Linux",
    r"\bdistributed systems?\b": "Distributed Systems",
    r"\bgrpc\b": "gRPC",
    r"\bc\+\+\b": "C++",
    r"\b(?:ansi\s+c|c\s+programming|c\s+language)\b": "C",
    r"\bgolang\b": "Go",
    r"\bgo\b": "Go",
    r"\bdata structures\b": "DSA",
    r"\balgorithms\b": "Algorithms",
    r"\bsystem design\b": "System Design",
    r"\bconcurrency\b": "Concurrency",
    r"\bmultithreading\b": "Multithreading",
    r"\boperating systems\b": "Operating Systems"
}

SENIOR_TITLE_KEYWORDS = [
    "senior", "sr.", "sr ", "staff", "principal", "lead", "director",
    "manager", "architect", "head of", "head,", "vp", "vice president",
    "tlm", "tech lead", "distinguished", "fellow", " iv", "- iv", "-iv",
    " iii", "- iii", "-iii", "level 2", "level 3", "l5", "l6", "l7"
]

TECH_AFFIRMATIVE_KEYWORDS = [
    "engineer", "engineering", "developer", "software", "swe", "sde", "ai",
    "ml", "machine learning", "data", "deep learning", "architect", "programmer",
    "devops", "sre", "platform", "infrastructure", "backend", "fullstack",
    "full stack", "full-stack", "systems", "cloud", "security", "researcher",
    "scientist", "analyst", "trainer", "coding", "evaluator", "annotation",
    "applied scientist"
]

PURE_NON_TECH_PATTERNS = [
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

EARLY_CAREER_KEYWORDS = [
    "junior", "early career", "new grad", "university grad", "associate",
    "entry level", "entry-level", "graduate", "software engineer 1",
    "software engineer i", "ai engineer 1", "ai engineer i", "swe 1",
    "swe i", "sde 1", "sde i", "l1", "mts 1", "mts i", "intern",
    "internship", "research intern", "applied scientist 1", "applied scientist i",
    "data scientist 1", "data scientist i"
]

def parse_experience_requirements(jd_lower: str) -> Tuple[int, int, str]:
    """
    Robustly extracts minimum and maximum years of experience from job descriptions.
    """
    # 1. Range matching: e.g. 3-5 years, 0 to 2 years, 1–3 years
    range_match = re.search(r"(\d+)\s*(?:[-–—to]+)\s*(\d+)\+?\s*years?", jd_lower)
    if range_match:
        min_y = int(range_match.group(1))
        max_y = int(range_match.group(2))
        return min_y, max_y, f"{min_y}–{max_y} years"

    # 2. Minimum or at least: e.g. minimum 3 years, at least 2 years
    min_match = re.search(r"(?:minimum|at\s+least)\s+(?:of\s+)?(\d+)\+?\s*years?", jd_lower)
    if min_match:
        y = int(min_match.group(1))
        return y, y, f"{y}+ years"

    # 3. Single pattern with arbitrary qualifier: e.g. 3+ years of hands-on engineering experience
    qualifier_match = re.search(r"(\d+)\+?\s*years?(?:\s+of)?(?:\s+[\w\s-]{1,35})?\s+(?:experience|work\s+experience)", jd_lower)
    if qualifier_match:
        y = int(qualifier_match.group(1))
        return y, y, f"{y}+ years"

    # 4. Action phrase: e.g. 3+ years building production systems
    action_match = re.search(r"(\d+)\+?\s*years?\s+(?:in|building|designing|developing|working)", jd_lower)
    if action_match:
        y = int(action_match.group(1))
        return y, y, f"{y}+ years"

    return 0, 1, "0–1 years (Not specified / Open)"

def evaluate_job_match(company: str, title: str, jd: str, location: str = "") -> Dict[str, Any]:
    """
    Calibrated, high-precision Job Evaluation Engine for Adarsh Kumar Jha:
    - IIIT Delhi CS & AI 2026, GATE AIR 252.
    - AI Engineer at TBO.com (~9 months production: Lakehouse CDC Spark/Glue/Kafka/Hudi & Voice AI/Text-to-SQL Agents).
    - Strict Rejection: >2y requirements, Senior/Staff/Principal/Lead, foreign on-site relocation.
    - Dynamic Sensible Scoring: 0 to 98% based on real skill density, domain synergy, and archetype alignment.
    """
    jd_lower = jd.lower()
    title_lower = title.lower()
    company_tier = classify_company_tier(company)

    # 0. Check if title is technical
    is_tech_role = any(re.search(r"\b" + re.escape(k) + r"\b", title_lower) for k in TECH_AFFIRMATIVE_KEYWORDS)

    # Disqualify pure non-tech roles
    if not is_tech_role:
        for pattern in PURE_NON_TECH_PATTERNS:
            if re.search(pattern, title_lower):
                return {
                    "company_tier": company_tier,
                    "match_score": 5,
                    "fit_verdict": "NON_TECH_ROLE_EXCLUDED",
                    "priority_level": "SKIP",
                    "experience_status": "PURE_NON_TECH_ROLE",
                    "primary_domain": "Non-Tech",
                    "matched_skills": [],
                    "recommended_highlights": [],
                    "years_req": 0,
                    "exp_label": "N/A"
                }

    # 1. Light Short-Circuit Filter: Seniority from Title
    # Exclude unless explicitly an early-career exempt role (e.g. Associate, SDE-1)
    is_early_career_title = any(k in title_lower for k in EARLY_CAREER_KEYWORDS)
    is_senior_title = any(re.search(r"\b" + re.escape(k) + r"\b", title_lower) for k in SENIOR_TITLE_KEYWORDS)
    if is_senior_title and not is_early_career_title:
        return {
            "company_tier": company_tier,
            "match_score": 10,
            "fit_verdict": "SENIOR_TITLE_EXCLUDED",
            "priority_level": "SKIP",
            "experience_status": "SENIOR_TITLE_MISMATCH",
            "primary_domain": "Senior Role",
            "matched_skills": [],
            "recommended_highlights": [],
            "years_req": 3,
            "exp_label": "Senior/Lead"
        }

    # 2. Years of Experience Analysis from JD
    min_years, max_years, exp_label = parse_experience_requirements(jd_lower)
    if min_years > 2 and not is_early_career_title:
        return {
            "company_tier": company_tier,
            "match_score": 15,
            "fit_verdict": "HIGH_EXPERIENCE_EXCLUDED",
            "priority_level": "SKIP",
            "experience_status": f"HIGH_EXP_MISMATCH ({exp_label})",
            "primary_domain": "High Experience Required",
            "matched_skills": [],
            "recommended_highlights": [],
            "years_req": min_years,
            "exp_label": exp_label
        }

    # 3. Contract & Remote Role Detection
    is_contract_role = any(k in title_lower or k in jd_lower[:400] for k in [
        "contract", "contractor", "freelance", "hourly", "c2c", "part-time consultant",
        "independent contractor", "fixed-term", "contract-to-hire"
    ])
    is_remote_role = any(k in title_lower or k in jd_lower[:400] for k in [
        "remote", "work from anywhere", "anywhere", "telecommute"
    ])

    # 4. Strict India Location Filter (Only Global Remote Contracts can be outside India)
    location_ok = is_location_allowed(location, is_remote_contract=(is_contract_role and is_remote_role))
    if not location_ok:
        return {
            "company_tier": company_tier,
            "match_score": 10,
            "fit_verdict": "FOREIGN_LOCATION_EXCLUDED",
            "priority_level": "SKIP",
            "experience_status": f"NON_INDIA_LOCATION ({location})",
            "primary_domain": "Foreign On-Site",
            "matched_skills": [],
            "recommended_highlights": [],
            "years_req": min_years,
            "exp_label": exp_label
        }

    # 5. Precise Skill Taxonomy Matching (Exact Word Boundaries)
    domain_scores = {}
    matched_skills_set = set()
    total_weighted_points = 0.0

    for domain, group in WEIGHTED_SKILLS.items():
        weight = group["weight"]
        domain_hits = []
        for pat in group["skills"]:
            if re.search(pat, jd_lower):
                display_name = PATTERN_DISPLAY_NAMES.get(pat, pat.replace(r"\b", ""))
                domain_hits.append(display_name)
                matched_skills_set.add(display_name)
                total_weighted_points += weight
        domain_scores[domain] = domain_hits

    unique_matched_skills = sorted(list(matched_skills_set))

    # Determine Primary Domain by greatest hits
    best_domain = "backend_distributed_systems"
    max_hits = 0
    for d, hits in domain_scores.items():
        if len(hits) > max_hits:
            max_hits = len(hits)
            best_domain = d

    domain_labels = {
        "genai_llm_agents": "AI & Agentic Systems",
        "lakehouse_data_engineering": "Lakehouse & Data Infrastructure",
        "ml_deep_learning": "Machine Learning & Deep Learning",
        "backend_distributed_systems": "Backend & Cloud Microservices",
        "cs_core_algorithms": "Core Systems & Algorithms"
    }
    primary_domain_label = domain_labels.get(best_domain, "Software Engineering")

    # 6. Sensible Dynamic Match Score Calculation (0 to 98)
    # A. Skill Density Score (0 - 45 points)
    # Minimum 1 real tech skill required for any positive score
    if not unique_matched_skills:
        skill_score = 0
    else:
        # Scale weighted points: e.g. 15+ weighted points reaches max 45
        skill_score = min(total_weighted_points * 2.2, 45)

    # B. Title & Archetype Alignment (0 - 25 points)
    title_points = 0
    if any(k in title_lower for k in ["ai engineer", "machine learning", "ml engineer", "llm engineer", "ai specialist"]):
        title_points = 25
    elif any(k in title_lower for k in ["data engineer", "lakehouse", "spark engineer", "data infrastructure"]):
        title_points = 25
    elif any(k in title_lower for k in ["software engineer", "sde", "swe", "backend", "python developer"]):
        title_points = 20
    elif any(k in title_lower for k in ["data scientist", "applied scientist", "research intern"]):
        title_points = 20
    elif is_tech_role:
        title_points = 12

    # C. Experience Calibration (0 - 20 points)
    exp_points = 0
    if is_early_career_title or min_years <= 1:
        exp_points = 20
        exp_status = f"IDEAL_EARLY_CAREER ({exp_label})"
    elif min_years == 2:
        exp_points = 10
        exp_status = f"ACCEPTABLE_2YR ({exp_label})"
    elif min_years > 2:
        exp_points = -25
        exp_status = f"HIGH_EXP_MISMATCH ({exp_label})"
    else:
        exp_points = 15
        exp_status = f"OPEN_EXP ({exp_label})"

    # D. Company Tier & Remote Contract Priority (0 - 10 points)
    tier_points = 0
    if is_contract_role and is_remote_role and company_tier != "TIER_3":
        tier_points = 10
        exp_status = "REPUTED_REMOTE_CONTRACT"
    elif company_tier == "TIER_1":
        tier_points = 8
    elif company_tier == "TIER_2":
        tier_points = 5
    elif company_tier == "TIER_3":
        tier_points = -20

    # Calculate Raw Dynamic Score
    computed_score = int(round(skill_score + title_points + exp_points + tier_points))

    # Sanity Floor & Ceiling:
    # If JD is a stub / title-only (less than 80 chars), handle based on archetype & tier
    is_stub_jd = len(jd_lower.strip()) < 80 or jd_lower.strip() == title_lower.strip()
    if is_stub_jd:
        if is_contract_role and is_remote_role and company_tier != "TIER_3":
            computed_score = 78
            exp_status = "REPUTED_REMOTE_CONTRACT (Title Assessed)"
        elif is_early_career_title:
            if company_tier == "TIER_1":
                computed_score = 80
                exp_status = f"TIER_1_EARLY_CAREER ({exp_label})"
            elif company_tier in ("TIER_2", "STANDARD"):
                computed_score = 72
                exp_status = f"EARLY_CAREER ({exp_label})"
        elif is_tech_role and company_tier in ("TIER_1", "TIER_2"):
            computed_score = 65
            exp_status = f"TECH_ROLE ({exp_label})"
    elif not unique_matched_skills:
        # If full JD is provided and has 0 tech skills, cap score at 15
        computed_score = min(computed_score, 15)

    # If role requires 3+ years and not early career, cap score at 20
    if min_years >= 3 and not is_early_career_title:
        computed_score = min(computed_score, 20)

    final_score = max(min(computed_score, 98), 5)

    # 7. Priority Level & Fit Verdict
    if final_score >= 82 and min_years <= 2:
        priority = "CRITICAL_PRIORITY" if (company_tier == "TIER_1" or is_contract_role) else "HIGH_PRIORITY"
        verdict = "EXCELLENT_MATCH"
    elif final_score >= 68 and min_years <= 2:
        priority = "HIGH_PRIORITY"
        verdict = "STRONG_MATCH"
    elif final_score >= 50 and min_years <= 2:
        priority = "NORMAL"
        verdict = "MODERATE_MATCH"
    else:
        priority = "SKIP"
        verdict = "POOR_FIT_OR_EXCLUDED"

    # Focus Highlights strictly based on actual matched skills
    highlights = []
    if "Apache Spark" in unique_matched_skills or "Kafka" in unique_matched_skills or "Hudi" in unique_matched_skills or "AWS Glue" in unique_matched_skills:
        highlights.append("Lead with TBO Lakehouse CDC pipeline (Spark, Glue, Kafka, Hudi, Athena) & cost optimization")
    if "LLM" in unique_matched_skills or "RAG" in unique_matched_skills or "Agents" in unique_matched_skills or "Prompt Caching" in unique_matched_skills:
        highlights.append("Highlight TBO Nova Sonic voice bot (600ms p95), Text-to-SQL agent with ontology, and prompt caching")
    if "PyTorch" in unique_matched_skills or "Transformers" in unique_matched_skills:
        highlights.append("Emphasize R2C Transformer Q&A (LoRA, 75% compression, 2x inference) and Oracle R-BERT research")
    if "FastAPI" in unique_matched_skills or "Docker" in unique_matched_skills or "Kubernetes" in unique_matched_skills or "Distributed Systems" in unique_matched_skills:
        highlights.append("Emphasize FastAPI microservices, Docker, Kubernetes diagnostics, and Custom Linux OS shell in C")

    return {
        "company_tier": company_tier,
        "match_score": final_score,
        "fit_verdict": verdict,
        "priority_level": priority,
        "experience_status": exp_status,
        "primary_domain": primary_domain_label,
        "matched_skills": unique_matched_skills,
        "recommended_highlights": highlights,
        "years_req": min_years,
        "exp_label": exp_label
    }

def run_evaluation_pipeline(re_evaluate_all: bool = False) -> List[Dict[str, Any]]:
    """Evaluates pending or all jobs in the database against the calibrated experience rules."""
    from engine.db import get_all_jobs
    if re_evaluate_all:
        pending_jobs = get_all_jobs()
    else:
        pending_jobs = get_jobs_by_status("DISCOVERED")
        if not pending_jobs:
            pending_jobs = get_jobs_by_status("EVALUATED")

    print(f"[*] Running calibrated JEV evaluation on {len(pending_jobs)} jobs...")
    evaluated = []

    for job in pending_jobs:
        job_id = job["job_id"]
        raw_jd_path = job["raw_jd_path"]
        jd_text = ""
        if raw_jd_path and Path(raw_jd_path).exists():
            with open(raw_jd_path, "r", encoding="utf-8") as f:
                jd_text = f.read()
        else:
            jd_text = job["title"]

        res = evaluate_job_match(job["company"], job["title"], jd_text, job["location"])

        status_update = "EVALUATED"
        if res["priority_level"] == "SKIP":
            status_update = "SKIPPED"

        skills_str = ", ".join(res["matched_skills"][:6]) if res["matched_skills"] else "None"
        focus_str = f" Focus: {res['recommended_highlights'][0]}" if res["recommended_highlights"] else ""
        notes = f"[{res['experience_status']}] Domain: {res['primary_domain']}. Matched ({len(res['matched_skills'])}): {skills_str}.{focus_str}"

        update_job_status(job_id, status_update, {
            "company_tier": res["company_tier"],
            "match_score": res["match_score"],
            "fit_verdict": res["fit_verdict"],
            "priority_level": res["priority_level"],
            "notes": notes
        })
        evaluated.append({
            "job_id": job_id,
            "company": job["company"],
            "title": job["title"],
            **res
        })

    print(f"[+] Evaluation complete: {len(evaluated)} jobs evaluated with precision matcher.")
    return evaluated
