import os
from pathlib import Path

# Base Paths
PROJECT_ROOT = Path("/Users/adarsh/job_finder_applier")
MASTER_RESUME_DIR = PROJECT_ROOT / "master_resume"
MASTER_PROFILE_PATH = MASTER_RESUME_DIR / "MASTER_PROFILE.md"
TEMPLATES_DIR = MASTER_RESUME_DIR / "templates"
OVERLEAF_SOURCE_DIR = MASTER_RESUME_DIR / "overleaf_source"

DATA_DIR = PROJECT_ROOT / "data"
RAW_JOBS_DIR = DATA_DIR / "raw_jobs"
APPLIED_JOBS_DIR = PROJECT_ROOT / "applied_jobs"
DB_PATH = DATA_DIR / "jobs.db"
TEXT_SUMMARY_PATH = DATA_DIR / "jobs_found_and_applied.txt"
RESUMES_GENERATED_DIR = PROJECT_ROOT / "resumes_generated"

# Ego-Browser Configuration
EGO_BROWSER_PROFILE_ID = "Default"  # "Daily workload" profile
EGO_BROWSER_MAIN_PROFILE_ID = "Profile 1"  # "Main Profile" (Read-only / User reserved)

# Helper to load .env without hard dependency on external python-dotenv
def _load_env_file():
    env_path = PROJECT_ROOT / ".env"
    if env_path.exists():
        with open(env_path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    key, val = line.split("=", 1)
                    key = key.strip()
                    val = val.strip().strip('"').strip("'")
                    os.environ.setdefault(key, val)

_load_env_file()

# Claude.ai Accounts (Loaded from .env or generic fallbacks)
_env_claude_accounts = os.getenv("CLAUDE_ACCOUNTS")
if _env_claude_accounts:
    CLAUDE_ACCOUNTS = [acc.strip() for acc in _env_claude_accounts.split(",") if acc.strip()]
else:
    CLAUDE_ACCOUNTS = [
        "account1@example.com",
        "account2@example.com",
    ]

# Candidate Core Metadata (Loaded from .env with public generic placeholders)
CANDIDATE_NAME = os.getenv("CANDIDATE_NAME", "Candidate Name")
CANDIDATE_FIRST_NAME = os.getenv("CANDIDATE_FIRST_NAME", "Candidate")
CANDIDATE_LAST_NAME = os.getenv("CANDIDATE_LAST_NAME", "Name")
CANDIDATE_EMAIL = os.getenv("CANDIDATE_EMAIL", "candidate@example.com")
CANDIDATE_PERSONAL_EMAIL = os.getenv("CANDIDATE_PERSONAL_EMAIL", os.getenv("CANDIDATE_EMAIL", "candidate@example.com"))
CANDIDATE_PHONE = os.getenv("CANDIDATE_PHONE", "+1-555-0199")
CANDIDATE_PHONE_PLAIN = os.getenv("CANDIDATE_PHONE_PLAIN", "5550199000")
CANDIDATE_LOCATION = os.getenv("CANDIDATE_LOCATION", "Bengaluru, Karnataka, India")
CANDIDATE_CITY = os.getenv("CANDIDATE_CITY", "Bengaluru / Gurugram, India")
CANDIDATE_ADDRESS = os.getenv("CANDIDATE_ADDRESS", "Tech City, India")
CANDIDATE_FULL_LOCATION = os.getenv("CANDIDATE_FULL_LOCATION", "Bengaluru, Karnataka, India")
CANDIDATE_LINKEDIN = os.getenv("CANDIDATE_LINKEDIN", "https://www.linkedin.com/in/username")
CANDIDATE_GITHUB = os.getenv("CANDIDATE_GITHUB", "https://github.com/username")
CANDIDATE_CURRENT_COMPANY = os.getenv("CANDIDATE_CURRENT_COMPANY", "Tech Enterprise")
CANDIDATE_CURRENT_TITLE = os.getenv("CANDIDATE_CURRENT_TITLE", "AI Engineer (Production Engineering)")

# Strict Production Safety Circuit Breaker:
FORBIDDEN_PLACEHOLDERS = {
    "Candidate Name",
    "candidate@example.com",
    "5550199000",
    "+1-555-0199",
    "Tech City",
    "Tech City, India",
    "CandidateSecretPass!2026"
}

def assert_real_candidate_profile():
    """
    CRITICAL SAFETY CIRCUIT BREAKER:
    Guarantees that placeholder / dummy credentials are NEVER used to generate resumes,
    fill application forms, or submit job applications.
    Halts execution immediately if .env is missing or invalid.
    """
    if (
        CANDIDATE_NAME in FORBIDDEN_PLACEHOLDERS
        or "example.com" in CANDIDATE_EMAIL
        or CANDIDATE_PHONE in FORBIDDEN_PLACEHOLDERS
        or CANDIDATE_PHONE_PLAIN in FORBIDDEN_PLACEHOLDERS
    ):
        raise RuntimeError(
            "\n" + "=" * 80 + "\n"
            "[CRITICAL SAFETY CIRCUIT BREAKER TRIGGERED]\n"
            "Execution ABORTED: System detected generic placeholder credentials.\n"
            "Applications will NEVER be generated, tailored, staged, or submitted with dummy data!\n"
            "Please ensure /Users/adarsh/job_finder_applier/.env exists and contains your real candidate details.\n"
            + "=" * 80 + "\n"
        )

# Target Job Search Roles
TARGET_TITLES = [
    "AI Engineer",
    "Machine Learning Engineer",
    "ML Engineer",
    "LLM Engineer",
    "Data Platform Engineer",
    "Data Engineer",
    "Backend Engineer",
    "Software Engineer - AI",
    "Distributed Systems Engineer",
    "MLOps Engineer",
]

TARGET_LOCATIONS = [
    "Bengaluru, Karnataka, India",
    "Gurugram, Haryana, India",
    "Noida, Uttar Pradesh, India",
    "Delhi, India",
    "Hyderabad, Telangana, India",
    "Pune, Maharashtra, India",
    "Mumbai, Maharashtra, India",
    "Chennai, Tamil Nadu, India",
    "Remote, India",
]

# Strict India location whitelist (Exceptions only for Worldwide Remote Contract roles)
VALID_INDIA_CITIES = {
    "bengaluru", "bangalore", "hyderabad", "delhi", "gurgaon", "gurugram",
    "noida", "ncr", "pune", "mumbai", "chennai", "india"
}

def is_location_allowed(location_str: str, is_remote_contract: bool = False) -> bool:
    """
    Enforces candidate requirement: Location MUST be in India
    (Bangalore, Mumbai, Hyderabad, Delhi/NCR, Pune, Chennai).
    The ONLY exception is global remote contract roles.
    Foreign on-site roles (US, UK, Europe, Australia, etc.) are strictly disqualified.
    """
    loc_lower = (location_str or "").lower()
    
    # 1. Global Remote Contract exception
    if is_remote_contract and ("remote" in loc_lower or "worldwide" in loc_lower or "anywhere" in loc_lower):
        return True
        
    # 2. Strict India location match
    for city in VALID_INDIA_CITIES:
        if city in loc_lower:
            return True
            
    return False

# Company Tier Classification
# Tier 1: Reputed AI/Tech giants & Tier-1 unicorns (Always high priority, trigger custom LaTeX + referral drafts)
TIER_1_COMPANIES = {
    "google", "alphabet", "microsoft", "apple", "nvidia", "meta", "facebook",
    "openai", "anthropic", "databricks", "snowflake", "uber", "stripe",
    "amazon", "aws", "cisco", "salesforce", "zomato", "meesho", "swiggy",
    "flipkart", "cred", "razorpay", "atlassian", "adobe", "oracle", "intuit",
    "linkedin", "palantir", "scale ai", "cohere", "perplexity", "glean",
    "mongodb", "elastic", "confluent", "cloudflare", "datadog", "pinterest"
}

# Tier 2: Strong scale-ups / Well-funded modern tech firms
TIER_2_COMPANIES = {
    "ramp", "brex", "rippling", "deel", "airtable", "notion", "figma",
    "vercel", "supabase", "postman", "browserbase", "modal", "together ai",
    "mistral", "groq", "baseten", "pinecone", "weaviate", "qdrant", "langchain",
    "llamaindex", "anyscale", "runway", "replicate", "character.ai", "instacart"
}

# Companies below TBO.com or known service/low-tech firms (Low priority or skip)
TIER_3_SKIP_COMPANIES = {
    "tcs", "infosys", "wipro", "cognizant", "accenture", "capgemini",
    "tech mahindra", "hcltech", "mindtree", "l&t", "genpact", "hexaware"
}

# Auto-apply Blacklist: Companies that strictly ban/block automated applications.
# Must NOT auto-apply to these; create tailored resume + referral draft only.
AUTO_APPLY_BLACKLIST = {
    "google", "alphabet", "microsoft", "rubrik", "apple", "meta", "nvidia", "goldman sachs"
}

# Default portal password (loaded from .env or safe dummy fallback)
DEFAULT_PORTAL_PASSWORD = os.getenv("DEFAULT_PORTAL_PASSWORD", "CandidateSecretPass!2026")

# Remote Contract Platforms (Highest priority)
REMOTE_CONTRACT_PLATFORMS = {
    "mercor", "cursor", "anysphere", "openai", "langchain", "weaviate",
    "himalayas", "weworkremotely", "remotive", "jobspresso"
}

# Scheduler settings: Runs every 6 hours (4 cycles per day) with +/- 1.5 hours jitter
CYCLE_INTERVAL_HOURS = 6.0
CYCLE_JITTER_HOURS = 1.5  # +/- 1.5 hour random jitter to avoid rate-limiting patterns

def is_auto_apply_allowed(company_name: str) -> bool:
    """Returns False if company is blacklisted from automated bot applications."""
    norm = company_name.strip().lower()
    for bl in AUTO_APPLY_BLACKLIST:
        if bl in norm:
            return False
    return True

def classify_company_tier(company_name: str) -> str:
    """Classifies company into Tier 1 (Elite Priority), Tier 2 (Target), or Tier 3 (Low/Skip)."""
    norm = company_name.strip().lower()
    for t1 in TIER_1_COMPANIES:
        if t1 in norm:
            return "TIER_1"
    for t2 in TIER_2_COMPANIES:
        if t2 in norm:
            return "TIER_2"
    for t3 in TIER_3_SKIP_COMPANIES:
        if t3 in norm:
            return "TIER_3"
    return "STANDARD"

    return "TIER_2"  # Default unclassified companies to Tier 2 for JEV evaluation
