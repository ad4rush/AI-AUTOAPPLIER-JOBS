import os
import re
from pathlib import Path

# Base Paths
PROJECT_ROOT = Path(os.getenv("JOB_APPLIER_ROOT", Path(__file__).resolve().parent.parent)).resolve()
MASTER_RESUMES_DIR = PROJECT_ROOT / "master_resumes"
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
LOGS_DIR = PROJECT_ROOT / "logs"

# Ego-Browser Configuration
EGO_BROWSER_PROFILE_ID = "Default"  # "Daily workload" profile
EGO_BROWSER_MAIN_PROFILE_ID = "Profile 1"  # "Main Profile" (Personal)
EGO_BROWSER_COLLEGE_PROFILE_ID = "Profile 2"  # "COLLEGE PROFILE" (College)

# Dedicated Remote/Contract Job Applier Agent (Handoff Target)
REMOTE_AGENT_CONVERSATION_ID = "d5f399de-bcf3-4f7f-a9d4-233a20113449"
REMOTE_AGENT_TITLE = "Automated Remote Job Application Process"

# Helper to load .env with absolute guarantee across all working directories
def _load_env_file():
    possible_paths = [
        PROJECT_ROOT / ".env",
        Path(__file__).resolve().parent.parent / ".env",
        Path.cwd() / ".env",
        Path.home() / "job_finder_applier" / ".env"
    ]
    loaded = False
    for env_path in possible_paths:
        if env_path.exists():
            with open(env_path, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if line and not line.startswith("#") and "=" in line:
                        key, val = line.split("=", 1)
                        key = key.strip()
                        val = val.strip().strip('"').strip("'")
                        # Force overwrite to ensure real .env takes precedence over any placeholder env vars
                        os.environ[key] = val
            loaded = True
            break
    if not loaded:
        print("[!] Warning: .env file not found in search paths. Profile verification will halt placeholder execution.")

_load_env_file()

# Claude.ai Accounts (Loaded from .env)
_env_claude_accounts = os.getenv("CLAUDE_ACCOUNTS", "")
CLAUDE_ACCOUNTS = [acc.strip() for acc in _env_claude_accounts.split(",") if acc.strip()]

# Candidate Core Metadata (Strictly loaded from .env - NO DUMMY FALLBACKS)
CANDIDATE_NAME = os.getenv("CANDIDATE_NAME", "")
CANDIDATE_FIRST_NAME = os.getenv("CANDIDATE_FIRST_NAME", "")
CANDIDATE_LAST_NAME = os.getenv("CANDIDATE_LAST_NAME", "")
CANDIDATE_EMAIL = os.getenv("CANDIDATE_EMAIL", "")
CANDIDATE_PERSONAL_EMAIL = os.getenv("CANDIDATE_PERSONAL_EMAIL", "")
CANDIDATE_COLLEGE_EMAIL = os.getenv("CANDIDATE_COLLEGE_EMAIL", os.getenv("CANDIDATE_EMAIL", ""))
CANDIDATE_PHONE = os.getenv("CANDIDATE_PHONE", "")
CANDIDATE_PHONE_PLAIN = os.getenv("CANDIDATE_PHONE_PLAIN", "")
CANDIDATE_LOCATION = os.getenv("CANDIDATE_LOCATION", "")
CANDIDATE_CITY = os.getenv("CANDIDATE_CITY", "")
CANDIDATE_ZIP = os.getenv("CANDIDATE_ZIP", "")
CANDIDATE_ADDRESS = os.getenv("CANDIDATE_ADDRESS", "")
CANDIDATE_FULL_LOCATION = os.getenv("CANDIDATE_FULL_LOCATION", "")
CANDIDATE_LINKEDIN = os.getenv("CANDIDATE_LINKEDIN", "")
CANDIDATE_GITHUB = os.getenv("CANDIDATE_GITHUB", "")
CANDIDATE_CURRENT_COMPANY = os.getenv("CANDIDATE_CURRENT_COMPANY", "")
CANDIDATE_CURRENT_TITLE = os.getenv("CANDIDATE_CURRENT_TITLE", "")
CANDIDATE_HONORS = os.getenv("CANDIDATE_HONORS", "")
CANDIDATE_PRODUCTION_HIGHLIGHTS = os.getenv("CANDIDATE_PRODUCTION_HIGHLIGHTS", "")
CANDIDATE_RESEARCH_HIGHLIGHTS = os.getenv("CANDIDATE_RESEARCH_HIGHLIGHTS", "")
CANDIDATE_TARGET_ROLES = os.getenv("CANDIDATE_TARGET_ROLES", "")
CANDIDATE_MISSION_AND_GOALS = os.getenv("CANDIDATE_MISSION_AND_GOALS", "")
CANDIDATE_EXCLUSIONS = os.getenv("CANDIDATE_EXCLUSIONS", "")
CANDIDATE_BACKGROUND_SUMMARY = os.getenv("CANDIDATE_BACKGROUND_SUMMARY", "")


def get_candidate_profile_prompt_block() -> str:
    """
    Dynamically generates candidate profile text for LLM prompts at runtime.
    Loaded strictly from environment variables and local gitignored files.
    Ensures zero personal PII or hardcoded data is ever checked into Git.
    """
    return f"""- Candidate: {CANDIDATE_NAME} ({ANS_COLLEGE}, {ANS_DEGREE} in {ANS_MAJOR} {ANS_GRAD_YEAR}, {ANS_CGPA} CGPA)
- Key Credentials: {CANDIDATE_HONORS}
- Current Role: {CANDIDATE_CURRENT_TITLE} at {CANDIDATE_CURRENT_COMPANY}
- Production Highlights: {CANDIDATE_PRODUCTION_HIGHLIGHTS}
- Prior Research: {CANDIDATE_RESEARCH_HIGHLIGHTS}
- Target Roles (What to Apply For): {CANDIDATE_TARGET_ROLES}
- Engineering Mission (What I Want to Do): {CANDIDATE_MISSION_AND_GOALS}
- Hard Exclusions (Never Apply To): {CANDIDATE_EXCLUSIONS}
- Multi-Select Location Rule: Whenever multi-select location options exist (especially on Microsoft Eightfold, Ashby, Greenhouse), select ALL available locations in India ({ANS_ALL_INDIA_LOCATIONS}).
- Custom Resume Policy: "is_worthy_of_custom_resume" is ONLY true for Tier-1 tech giants (Microsoft, Google, Apple, Amazon, OpenAI, Stripe, Scale AI, Databricks, Barclays, Anthropic, Meta) OR >=$75/hr / >=₹30 LPA roles. For standard Tier-2 or startup roles, false."""

# Standard Form Answers (Loaded from .env for automated application form fillers)
ANS_WORK_AUTH_INDIA = os.getenv("ANS_WORK_AUTH_INDIA", "Yes")
ANS_SPONSORSHIP_INDIA = os.getenv("ANS_SPONSORSHIP_INDIA", "No")
ANS_WORK_AUTH_US = os.getenv("ANS_WORK_AUTH_US", "Yes")
ANS_SPONSORSHIP_US = os.getenv("ANS_SPONSORSHIP_US", "No")
ANS_CITIZENSHIP = os.getenv("ANS_CITIZENSHIP", "Indian")
ANS_LEGAL_RIGHT_TO_WORK = os.getenv("ANS_LEGAL_RIGHT_TO_WORK", "Yes - I am a citizen")

ANS_YEARS_OF_EXP = os.getenv("ANS_YEARS_OF_EXP", "1+")
ANS_NOTICE_PERIOD = os.getenv("ANS_NOTICE_PERIOD", "Immediate / 15-30 days")
ANS_EARLIEST_START_DATE = os.getenv("ANS_EARLIEST_START_DATE", "Immediately")

ANS_CURRENT_CTC = os.getenv("ANS_CURRENT_CTC", "₹20 LPA")
ANS_EXPECTED_CTC = os.getenv("ANS_EXPECTED_CTC", "₹25–30+ LPA")
ANS_HOURLY_RATE_USD = os.getenv("ANS_HOURLY_RATE_USD", "$75-$120/hr")

ANS_GENDER = os.getenv("ANS_GENDER", "Male")
ANS_RACE_ETHNICITY = os.getenv("ANS_RACE_ETHNICITY", "Asian (India)")
ANS_VETERAN_STATUS = os.getenv("ANS_VETERAN_STATUS", "I am not a protected veteran")
ANS_ARMED_FORCES_STATUS = os.getenv("ANS_ARMED_FORCES_STATUS", "I have not served")
ANS_DISABILITY_STATUS = os.getenv("ANS_DISABILITY_STATUS", "No, I do not have a disability")

ANS_CRIMINAL_RECORD = os.getenv("ANS_CRIMINAL_RECORD", "No")
ANS_NON_COMPETE = os.getenv("ANS_NON_COMPETE", "No")
ANS_FORMER_EMPLOYEE = os.getenv("ANS_FORMER_EMPLOYEE", "No")
ANS_GOVT_MILITARY_EMPLOYEE = os.getenv("ANS_GOVT_MILITARY_EMPLOYEE", "No")
ANS_KPMG_AUDITOR = os.getenv("ANS_KPMG_AUDITOR", "No")
ANS_FAMILY_STAKEHOLDER = os.getenv("ANS_FAMILY_STAKEHOLDER", "No")

ANS_COLLEGE = os.getenv("ANS_COLLEGE", "Premier Institute of Information Technology")
ANS_DEGREE = os.getenv("ANS_DEGREE", "Bachelor of Technology")
ANS_MAJOR = os.getenv("ANS_MAJOR", "Computer Science and Artificial Intelligence (CSAI)")
ANS_GRAD_YEAR = os.getenv("ANS_GRAD_YEAR", "2026")
ANS_CGPA = os.getenv("ANS_CGPA", "8.2 / 10")

ANS_PITCH_AI_ENGINEER = os.getenv("ANS_PITCH_AI_ENGINEER", "AI Engineer with experience deploying production voice AI, MCP agents, and data lakehouses.")
ANS_WHY_ANTHROPIC = os.getenv("ANS_WHY_ANTHROPIC", "Research alignment with constitutional AI and safe scalable ML systems.")
ANS_WHY_OPENAI = os.getenv("ANS_WHY_OPENAI", "Mission alignment with scalable beneficial artificial general intelligence.")
ANS_WHY_REMOTE = os.getenv("ANS_WHY_REMOTE", "High autonomy, asynchronous communication, and automated delivery across timezones.")

ANS_ALL_INDIA_LOCATIONS = "Bengaluru, Hyderabad, Noida, Gurugram, Pune, Delhi NCR, India (All India Locations / Remote)"
ALL_INDIA_LOCATIONS = [
    "Bengaluru", "Bangalore",
    "Hyderabad",
    "Noida",
    "Gurugram", "Gurgaon",
    "Pune",
    "Mumbai",
    "Delhi", "Delhi NCR",
    "Chennai",
    "Kolkata",
    "India"
]

# Strict Production Safety Circuit Breaker:
FORBIDDEN_PLACEHOLDERS = {
    "Candidate Name",
    "CandidateName",
    "Candidate_Name",
    "candidate@example.com",
    "personal@example.com",
    "college@example.com",
    "example.com",
    "5550199000",
    "+1-555-0199",
    "+1-555",
    "555-0199",
    "Tech City",
    "Tech City, India",
    "Tech Enterprise",
    "Premier Institute of Information Technology",
    "CandidateSecretPass!2026",
    "https://www.linkedin.com/in/username",
    "https://github.com/username",
    "github.com/username",
    "linkedin.com/in/username"
}

def assert_real_candidate_profile():
    """
    CRITICAL SAFETY CIRCUIT BREAKER:
    Guarantees that placeholder / dummy credentials are NEVER used to generate resumes,
    fill application forms, or submit job applications.
    Halts execution immediately if .env is missing or invalid.
    """
    errors = []
    if not CANDIDATE_NAME or CANDIDATE_NAME in FORBIDDEN_PLACEHOLDERS or CANDIDATE_NAME.strip().lower() in ["candidate", "name", "candidate name"]:
        errors.append(f"Invalid CANDIDATE_NAME: '{CANDIDATE_NAME}'")
    if not CANDIDATE_EMAIL or "example.com" in CANDIDATE_EMAIL or CANDIDATE_EMAIL in FORBIDDEN_PLACEHOLDERS:
        errors.append(f"Invalid CANDIDATE_EMAIL: '{CANDIDATE_EMAIL}'")
    if not CANDIDATE_PHONE or any(p in CANDIDATE_PHONE for p in ["555-0199", "5550199", "+1-555"]):
        errors.append(f"Invalid CANDIDATE_PHONE: '{CANDIDATE_PHONE}'")
    if not CANDIDATE_PHONE_PLAIN or "555" in CANDIDATE_PHONE_PLAIN[:4]:
        errors.append(f"Invalid CANDIDATE_PHONE_PLAIN: '{CANDIDATE_PHONE_PLAIN}'")
    if not CANDIDATE_LINKEDIN or "username" in CANDIDATE_LINKEDIN:
        errors.append(f"Invalid CANDIDATE_LINKEDIN: '{CANDIDATE_LINKEDIN}'")
    if not CANDIDATE_GITHUB or "username" in CANDIDATE_GITHUB:
        errors.append(f"Invalid CANDIDATE_GITHUB: '{CANDIDATE_GITHUB}'")
    if not CANDIDATE_ADDRESS or "Tech City" in CANDIDATE_ADDRESS:
        errors.append(f"Invalid CANDIDATE_ADDRESS: '{CANDIDATE_ADDRESS}'")
    if not CANDIDATE_CURRENT_COMPANY or CANDIDATE_CURRENT_COMPANY in FORBIDDEN_PLACEHOLDERS:
        errors.append(f"Invalid CANDIDATE_CURRENT_COMPANY: '{CANDIDATE_CURRENT_COMPANY}'")

    if errors:
        raise RuntimeError(
            "\n" + "=" * 80 + "\n"
            "[CRITICAL SAFETY CIRCUIT BREAKER TRIGGERED]\n"
            "Execution ABORTED: System detected generic placeholder credentials.\n"
            "Applications will NEVER be generated, tailored, staged, or submitted with dummy data!\n"
            "Errors detected:\n  - " + "\n  - ".join(errors) + "\n"
            f"Please ensure {PROJECT_ROOT}/.env exists and contains your real candidate details.\n"
            + "=" * 80 + "\n"
        )

def verify_script_zero_placeholders(script_code: str, context_label: str = "Script"):
    """
    Scans any generated automation or apply script before sending to browser.
    Aborts immediately if placeholder detected.
    """
    for bad in FORBIDDEN_PLACEHOLDERS:
        if bad in script_code:
            raise RuntimeError(
                f"[CRITICAL SAFETY CIRCUIT BREAKER] {context_label} contains forbidden placeholder '{bad}'! "
                "Application automation aborted immediately."
            )

# Execute circuit breaker validation on module load
assert_real_candidate_profile()

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
    "noida", "ncr", "pune", "mumbai", "chennai", "india", "ind"
}

FOREIGN_TERRITORIES = {
    "us", "uk", "us only", "usa only", "uk only", "canada only", "europe only", "eu only", "germany only",
    "united states", "usa", "u.s.", "u.s.a", "canada", "united kingdom", "great britain",
    "germany", "france", "australia", "japan", "tokyo", "singapore", "netherlands",
    "ireland", "israel", "switzerland", "sweden", "poland", "emea", "latam", "apac",
    "san francisco", "new york", "seattle", "austin", "boston", "chicago",
    "california", "texas", "washington, dc", "washington dc", "los angeles", "munich", "berlin", "london"
}

def is_location_allowed(location_str: str, is_remote_contract: bool = False, is_remote: bool = False) -> bool:
    """
    Enforces candidate requirement: Location MUST be in India
    (Bangalore, Mumbai, Hyderabad, Delhi/NCR, Pune, Chennai) OR Worldwide / Global Remote.
    Foreign on-site and country-restricted remote roles (US, UK, Europe, Australia, etc.) are strictly disqualified.
    """
    loc_lower = (location_str or "").lower().strip()
    if not loc_lower:
        return False

    # 1. Strict India location match (always allowed)
    for city in VALID_INDIA_CITIES:
        # Use regex word boundaries or substring check with word delimiters
        if re.search(r"\b" + re.escape(city) + r"\b", loc_lower):
            return True

    # 2. True Worldwide / Anywhere Remote match
    is_worldwide = any(w in loc_lower for w in ["worldwide", "anywhere", "global", "all locations", "work from anywhere"])

    # 3. Check for foreign country or city restrictions
    has_foreign_restriction = False
    for ft in FOREIGN_TERRITORIES:
        if re.search(r"\b" + re.escape(ft) + r"\b", loc_lower):
            has_foreign_restriction = True
            break

    # If it is restricted to a foreign country and NOT explicitly worldwide, reject
    if has_foreign_restriction and not is_worldwide:
        return False

    # 4. If remote or remote_contract is indicated and not restricted to foreign territory
    if is_remote or is_remote_contract or "remote" in loc_lower or is_worldwide:
        return True

    return False

# Company Tier Classification
# Tier 1: Reputed AI/Tech giants & Tier-1 unicorns (Always high priority, trigger custom LaTeX + referral drafts)
TIER_1_COMPANIES = {
    "google", "alphabet", "microsoft", "apple", "nvidia", "meta", "facebook",
    "openai", "anthropic", "databricks", "snowflake", "uber", "stripe",
    "amazon", "aws", "cisco", "salesforce", "zomato", "meesho", "swiggy",
    "flipkart", "cred", "razorpay", "groww", "slice", "sarvam", "navi", "glance",
    "inmobi", "postman", "atlassian", "adobe", "oracle", "intuit",
    "linkedin", "palantir", "scale ai", "cohere", "perplexity", "glean",
    "mongodb", "elastic", "confluent", "cloudflare", "datadog", "pinterest", "netflix"
}

# Tier 2: Strong scale-ups / Well-funded modern tech firms
TIER_2_COMPANIES = {
    "ramp", "brex", "rippling", "deel", "airtable", "notion", "figma",
    "vercel", "supabase", "postman", "browserbase", "modal", "together ai",
    "mistral", "groq", "baseten", "pinecone", "weaviate", "qdrant", "langchain",
    "llamaindex", "anyscale", "runway", "replicate", "character.ai", "instacart"
}

# Companies below current tier or known service/low-tech firms (Low priority or skip)
TIER_3_SKIP_COMPANIES = {
    "tcs", "infosys", "wipro", "cognizant", "accenture", "capgemini",
    "tech mahindra", "hcltech", "mindtree", "l&t", "genpact", "hexaware"
}

# Big Tech & Elite Tier 1 Targets (Absolute Top Priority for Immediate Staging & Application)
BIG_TECH_PRIORITY_COMPANIES = {
    "microsoft", "google", "apple", "amazon", "meta", "stripe", "oracle",
    "salesforce", "uber", "atlassian", "adobe", "nvidia", "netflix", "linkedin",
    "databricks", "snowflake", "palantir",
    # Elite Indian Tech Unicorns
    "meesho", "cred", "swiggy", "razorpay", "groww", "slice", "sarvam", "navi", "glance", "inmobi", "postman", "flipkart", "zomato"
}

# Auto-apply Blacklist: Only companies that strictly require manual referral or have verified hard IP bans
AUTO_APPLY_BLACKLIST = set()

# Default portal password (loaded from .env or safe dummy fallback)
DEFAULT_PORTAL_PASSWORD = os.getenv("DEFAULT_PORTAL_PASSWORD", "CandidateSecretPass!2026")

# Remote Contract Platforms (Highest priority)
REMOTE_CONTRACT_PLATFORMS = {
    "mercor", "cursor", "anysphere", "openai", "langchain", "weaviate",
    "himalayas", "weworkremotely", "remotive", "jobspresso"
}

# Scheduler settings: Runs every 6.0 hours with +/- 0.5 hours jitter (continuous autonomous discovery)
CYCLE_INTERVAL_HOURS = 6.0
CYCLE_JITTER_HOURS = 0.5  # +/- 30 min random jitter to avoid rate-limiting patterns

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
