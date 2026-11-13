import os
import re
import json
import time
import hashlib
import subprocess
import urllib.request
import urllib.parse
from datetime import datetime
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import List, Dict, Any, Optional

from engine.config import (
    RAW_JOBS_DIR,
    TARGET_TITLES,
    TARGET_LOCATIONS,
    classify_company_tier,
    EGO_BROWSER_PROFILE_ID,
    EGO_BROWSER_MAIN_PROFILE_ID
)
from engine.db import (
    generate_canonical_hash,
    is_job_seen,
    insert_job
)

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
}

def http_get_json(url: str, timeout: int = 12) -> Optional[Any]:
    req = urllib.request.Request(url, headers=HEADERS)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            if resp.status == 200:
                body = resp.read().decode("utf-8", errors="ignore")
                return json.loads(body)
    except Exception:
        return None
    return None

# Curated deterministic registry of target tech companies using Greenhouse, Lever, and Ashby
TARGET_COMPANIES = {
    "greenhouse": [
        "databricks", "stripe", "scaleai", "figma", "notion", "glean",
        "pinecone", "cohere", "anthropic", "browserbase", "modal", "vercel",
        "postman", "brex", "ramp", "rippling", "airtable", "supabase", "inmobi",
        "uber", "datadog", "instacart", "gusto", "cloudflare", "sentry", "docker",
        "wandb", "snowflake", "temporal", "chainlink", "labelbox", "cleanlab", "snorkelai",
        "affirm", "airbnb", "dropbox", "robinhood", "roblox", "snap", "discord",
        "lyft", "pinterest", "hashicorp", "gitlab", "elastic", "mongodb", "twilio",
        "segment", "pagerduty", "confluent", "cockroachlabs", "automattic", "github",
        "reddit", "plaid", "dbtlabs", "huggingface", "deepgram", "writer",
        "coreweave", "anyscale", "cerebras", "lambda", "qdrant", "chroma",
        "neon", "clickhouse", "redpanda", "fly", "railway", "render",
        "grafana", "decagon", "retool", "checkr", "launchdarkly", "zapier",
        "appliedintuition", "shieldai", "palantir", "anduril", "aurora",
        # Top Indian Tech Unicorns & Scaleups on Greenhouse
        "razorpaysoftwareprivatelimited", "groww", "slice", "glance"
    ],
    "lever": [
        "atlassian", "together", "baseten", "perplexity", "replicate", "meesho", "cred",
        "palantir", "benchling", "sourcegraph", "appliedintuition", "quora", "nuro", "aurora",
        "thoughtspot", "webflow", "zapier", "mux", "fullstory", "ironclad", "coursera",
        "plaid", "carta", "blend", "duolingo", "udemy", "grammarly", "monzo"
    ],
    "ashby": [
        "openai", "langchain", "mercor", "cursor", "anysphere", "weaviate",
        "suno", "runwayml", "replit", "linear", "resend",
        "elevenlabs", "mistral", "groq", "posthog", "tldraw", "characterai",
        "synthesia", "harvey", "dust", "tavus", "braintrust", "pika",
        "superhuman", "raycast", "warp", "clerk", "dub", "cal", "mintlify",
        "inngest", "speakeasy", "trigger", "knock", "loops", "convex", "upstash",
        "turso", "codeium", "cognition", "bland", "v0", "lovable",
        "unstructured", "lancedb", "poe", "monad", "berachain", "perplexity",
        # Top Indian Tech Unicorns on Ashby
        "sarvam", "navi"
    ]
}

def clean_html(raw_html: str) -> str:
    """Removes HTML tags and normalizes whitespace."""
    if not raw_html:
        return ""
    clean = re.sub(r"<[^>]+>", " ", raw_html)
    clean = re.sub(r"&nbsp;", " ", clean)
    clean = re.sub(r"&amp;", "&", clean)
    clean = re.sub(r"&lt;", "<", clean)
    clean = re.sub(r"&gt;", ">", clean)
    clean = re.sub(r"\s+", " ", clean).strip()
    return clean

# Fast Phase-1 Title Filtering: Eliminates 50%+ senior/staff/principal/non-tech roles before downloading full JDs
DISQUALIFIED_SENIORITY_PATTERNS = [
    r"\bsenior\b", r"\bsr\.?\b", r"\bstaff\b", r"\bprincipal\b", r"\blead\b",
    r"\bdirector\b", r"\bhead\s+of\b", r"\bhead,\b", r"\bvp\b", r"\bvice\s+president\b",
    r"\bmanager\b", r"\barchitect\b", r"\bdistinguished\b", r"\bfellow\b",
    r"\bfounding\b", r"\btlm\b", r"\btech\s+lead\b",
    r"\b(?:ii|iii|iv|v)\b", r"\b[2-5]\b", r"-(?:ii|iii|iv|v)\b", r"-[2-5]\b",
    r"\b5\+\s*years?\b", r"\b7\+\s*years?\b", r"\b8\+\s*years?\b", r"\b10\+\s*years?\b"
]

DISQUALIFIED_NON_TECH_PATTERNS = [
    r"\bsales\b", r"\bmarketing\b", r"\brecruiter\b", r"\brecruiting\b",
    r"\btalent\s+acquisition\b", r"\bhuman\s+resources\b", r"\bhr\b",
    r"\baccount\s+executive\b", r"\bcustomer\s+(?:support|success|service)\b",
    r"\blegal\b", r"\bcounsel\b", r"\bcompliance\b", r"\btax\b", r"\bpayroll\b",
    r"\bfacilities\b", r"\boffice\s+assistant\b", r"\bcopywriter\b", r"\bcontent\s+writer\b",
    r"\bmedia\b", r"\bpaid\s+media\b", r"\bseo\b",
    r"\bmedical\b", r"\bnurse\b", r"\bphysician\b", r"\bdoctor\b",
    r"\bmechanical\b", r"\bcivil\b", r"\bstructural\b", r"\bchemical\b",
    r"\bbusiness\s+development\b", r"\bbdr\b", r"\bsdr\b", r"\bprocurement\b",
    r"\bsupply\s+chain\b", r"\boperations\s+manager\b"
]

EARLY_CAREER_EXEMPTIONS = [
    r"\bsoftware\s+engineer\s*(?:-|–)?\s*(?:1|i)\b",
    r"\bswe\s*(?:1|i)\b",
    r"\bsde\s*(?:1|i)\b",
    r"\bmember\s+of\s+technical\s+staff\b",
    r"\bmts\b",
    r"\bforward\s+deployed\s+engineer\b",
    r"\bai\s+engineer\s*(?:-|–)?\s*(?:1|i)\b",
    r"\bdata\s+engineer\s*(?:-|–)?\s*(?:1|i)\b",
    r"\bapplied\s+scientist\s*(?:-|–)?\s*(?:1|i)\b",
    r"\bresearch\s+scientist\s*(?:-|–)?\s*(?:1|i)\b",
    r"\bdata\s+scientist\s*(?:-|–)?\s*(?:1|i)?\b",
    r"\bassociate\b",
    r"\bjunior\b",
    r"\bentry\s*level\b",
    r"\bentry-level\b",
    r"\bnew\s*grad\b",
    r"\buniversity\s*grad\b",
    r"\bintern\b",
    r"\binternship\b",
    r"\bl1\b",
    r"\bmts\s*(?:1|i)\b"
]

def is_title_relevant(title: str) -> bool:
    """
    Phase 1 Fast Title Filter:
    1. Rejects non-tech titles (sales, HR, legal, tax, medical).
    2. Rejects senior, staff, principal, lead, director, manager, and level II-V titles.
    3. Retains entry-level, early-career, intern, and target engineering titles.
    """
    title_lower = title.lower()

    # If title explicitly matches early-career exemption (e.g. SDE-1, Software Engineer I), keep it!
    is_early_career = any(re.search(pat, title_lower) for pat in EARLY_CAREER_EXEMPTIONS)
    if is_early_career:
        return True

    # 1. Non-tech filter
    for pat in DISQUALIFIED_NON_TECH_PATTERNS:
        if re.search(pat, title_lower):
            return False

    # 2. Seniority filter (Senior, Staff, Principal, Lead, Manager, Architect, II, III, IV, etc.)
    for pat in DISQUALIFIED_SENIORITY_PATTERNS:
        if re.search(pat, title_lower):
            return False

    # 3. Positive engineering archetype keywords
    positive_keywords = [
        "ai", "artificial intelligence", "ml", "machine learning",
        "data", "lakehouse", "spark", "llm", "backend", "software engineer",
        "systems", "platform", "infrastructure", "etl", "python", "developer", "swe", "sde",
        "scientist", "researcher", "intern", "apprentice"
    ]
    return any(pos in title_lower for pos in positive_keywords)

def save_raw_job(company: str, job_id: str, data: Dict[str, Any]) -> str:
    """Saves raw job json to data/raw_jobs/YYYY-MM-DD/<company>_<job_id>.json."""
    today = datetime.now().strftime("%Y-%m-%d")
    out_dir = RAW_JOBS_DIR / today
    out_dir.mkdir(parents=True, exist_ok=True)
    clean_company = re.sub(r"[^a-zA-Z0-9_-]", "_", company.lower())
    clean_id = re.sub(r"[^a-zA-Z0-9_-]", "_", str(job_id))
    file_path = out_dir / f"{clean_company}_{clean_id}.json"
    with open(file_path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
    return str(file_path)

def scrape_greenhouse_company(company: str) -> List[Dict[str, Any]]:
    """Scrapes Greenhouse jobs using their official board API."""
    url = f"https://boards-api.greenhouse.io/v1/boards/{company}/jobs?content=true"
    discovered = []
    try:
        data = http_get_json(url, timeout=12)
        if not data or not isinstance(data, dict):
            return []
        jobs = data.get("jobs", [])
        for j in jobs:
            title = j.get("title", "")
            if not is_title_relevant(title):
                continue

            job_id = str(j.get("id"))
            job_url = j.get("absolute_url")
            location = j.get("location", {}).get("name", "Remote / Unspecified")
            raw_content = j.get("content", "")
            clean_jd = clean_html(raw_content)

            canonical_hash = generate_canonical_hash(company, title, job_url)
            if is_job_seen(canonical_hash):
                continue

            record = {
                "job_id": f"gh_{company}_{job_id}",
                "canonical_hash": canonical_hash,
                "company": company.title(),
                "title": title,
                "location": location,
                "url": job_url,
                "source": "greenhouse",
                "company_tier": classify_company_tier(company),
                "raw_jd": clean_jd,
                "metadata": {
                    "updated_at": j.get("updated_at"),
                    "departments": [d.get("name") for d in j.get("departments", [])]
                }
            }
            raw_path = save_raw_job(company, job_id, record)
            record["raw_jd_path"] = raw_path
            discovered.append(record)
    except Exception as e:
        print(f"[Scraper:Greenhouse] Error for {company}: {e}")
    return discovered

def scrape_lever_company(company: str) -> List[Dict[str, Any]]:
    """Scrapes Lever jobs using their public postings API."""
    url = f"https://api.lever.co/v0/postings/{company}?mode=json"
    discovered = []
    try:
        jobs = http_get_json(url, timeout=12)
        if not jobs or not isinstance(jobs, list):
            return []

        for j in jobs:
            title = j.get("text", "")
            if not is_title_relevant(title):
                continue

            job_id = str(j.get("id"))
            job_url = j.get("hostedUrl", "")
            cats = j.get("categories", {})
            location = cats.get("location", "Remote / Unspecified")
            commitment = cats.get("commitment", "Full-time")
            raw_desc = j.get("descriptionPlain", "") or clean_html(j.get("description", ""))

            is_contract = any(k in title.lower() or k in commitment.lower() for k in ["contract", "contractor", "freelance", "hourly", "part-time", "consultant"])

            canonical_hash = generate_canonical_hash(company, title, job_url)
            if is_job_seen(canonical_hash):
                continue

            record = {
                "job_id": f"lev_{company}_{job_id}",
                "canonical_hash": canonical_hash,
                "company": company.title(),
                "title": title + (" [Contract]" if is_contract else ""),
                "location": location,
                "url": job_url,
                "source": "lever",
                "company_tier": classify_company_tier(company),
                "raw_jd": raw_desc,
                "metadata": {
                    "team": cats.get("team"),
                    "commitment": commitment,
                    "isContract": is_contract
                }
            }
            raw_path = save_raw_job(company, job_id, record)
            record["raw_jd_path"] = raw_path
            discovered.append(record)
    except Exception as e:
        print(f"[Scraper:Lever] Error for {company}: {e}")
    return discovered

def scrape_ashby_company(company: str) -> List[Dict[str, Any]]:
    """Scrapes Ashby jobs using their public posting API."""
    url = f"https://api.ashbyhq.com/posting-api/job-board/{company}"
    discovered = []
    try:
        data = http_get_json(url, timeout=12)
        if not data or not isinstance(data, dict):
            return []
        jobs = data.get("jobs", [])
        for j in jobs:
            title = j.get("title", "")
            if not is_title_relevant(title):
                continue

            job_id = str(j.get("id"))
            job_url = j.get("jobUrl") or f"https://jobs.ashbyhq.com/{company}/{job_id}"
            location = j.get("location", "Remote / Unspecified")
            is_remote = j.get("isRemote", False)
            emp_type = j.get("employmentType", "FullTime")
            raw_desc = j.get("descriptionPlain", "") or clean_html(j.get("descriptionHtml", ""))

            # Flag contract / remote contract positions
            is_contract = any(k in title.lower() or k in emp_type.lower() or k in raw_desc.lower()[:300] for k in ["contract", "contractor", "freelance", "hourly", "part-time", "consultant"])

            canonical_hash = generate_canonical_hash(company, title, job_url)
            if is_job_seen(canonical_hash):
                continue

            record = {
                "job_id": f"ash_{company}_{job_id[:8]}",
                "canonical_hash": canonical_hash,
                "company": company.title(),
                "title": title + (" [Contract]" if is_contract else "") + (" [Remote]" if is_remote else ""),
                "location": location + (" (Remote)" if is_remote else ""),
                "url": job_url,
                "source": "ashby",
                "company_tier": classify_company_tier(company),
                "raw_jd": raw_desc,
                "metadata": {
                    "department": j.get("department"),
                    "employmentType": emp_type,
                    "isRemote": is_remote,
                    "isContract": is_contract
                }
            }
            raw_path = save_raw_job(company, job_id, record)
            record["raw_jd_path"] = raw_path
            discovered.append(record)
    except Exception as e:
        print(f"[Scraper:Ashby] Error for {company}: {e}")
    return discovered


def scrape_google_careers() -> List[Dict[str, Any]]:
    """Scrapes Google Careers for Software & AI Engineering roles in India and Remote."""
    discovered = []
    tmp_path = Path("/tmp/google_jobs.json")
    if tmp_path.exists():
        tmp_path.unlink(missing_ok=True)

    script = """
const fs = await import("node:fs/promises");
const task = await taskSpace("job_scraper_google_" + Date.now(), { profileId: "Profile 1" });
const p1 = task.page("p1");
const url = "https://www.google.com/about/careers/applications/jobs/results/?q=Software%20Engineer&location=India&target_level=EARLY&target_level=INTERN_AND_APPRENTICE&sort_by=date";
await p1.goto(url, { waitUntil: "domcontentloaded" });
await p1.waitForTimeout(5000);
const jobs = await p1.evaluate(() => {
  const links = Array.from(document.querySelectorAll("a[href*='jobs/results/']"));
  return links.map(a => {
    if (a.href.includes("accounts.google.com")) return null;
    const aria = a.getAttribute("aria-label") || "";
    let title = aria.replace(/^Learn more about\\s+/i, "").trim();
    const card = a.closest("div.sMn82b") || a.parentElement?.parentElement;
    if (!title && card) {
      const h3 = card.querySelector("h3");
      title = h3 ? h3.innerText.trim() : "";
    }
    return {
      title: title,
      url: a.href,
      text: card ? card.innerText.replace(/\\s+/g, ' ').slice(0, 300) : ""
    };
  }).filter(j => j && j.title && j.title.length > 5 && !j.title.toLowerCase().includes("search"));
});
await task.finish({ keep: [] });
await fs.writeFile("/tmp/google_jobs.json", JSON.stringify(jobs));
"""
    try:
        proc = subprocess.run(["ego-browser", "nodejs"], input=script, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=40)
        if tmp_path.exists():
            with open(tmp_path, "r") as f:
                jobs = json.load(f)
            tmp_path.unlink(missing_ok=True)
            for j in jobs:
                title = j.get("title", "")
                if not is_title_relevant(title):
                    continue
                job_url = j.get("url", "")
                m = re.search(r"/jobs/results/(\d+)", job_url)
                job_id = m.group(1) if m else hashlib.md5(job_url.encode()).hexdigest()[:8]
                canonical_hash = generate_canonical_hash("Google", title, job_url)
                if is_job_seen(canonical_hash):
                    continue
                record = {
                    "job_id": f"goog_{job_id[:12]}",
                    "canonical_hash": canonical_hash,
                    "company": "Google",
                    "title": title,
                    "location": "Bengaluru / Hyderabad, India",
                    "url": job_url,
                    "source": "google_careers",
                    "company_tier": "TIER_1",
                    "raw_jd": j.get("text", title),
                    "metadata": {}
                }
                raw_path = save_raw_job("google", job_id, record)
                record["raw_jd_path"] = raw_path
                discovered.append(record)
    except Exception as e:
        print(f"[Scraper:Google] Error: {e}")
    return discovered

def fetch_microsoft_full_jd(url: str) -> Optional[str]:
    """Fetches full job description and requirements from Microsoft Careers details page via JSON-LD or meta tags."""
    if not url:
        return None
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)"})
    try:
        with urllib.request.urlopen(req, timeout=8) as resp:
            html = resp.read().decode("utf-8", errors="ignore")
            # 1. Try JSON-LD schema
            matches = re.findall(r'<script[^>]+type=[\"\']application/ld\+json[\"\'][^>]*>(.*?)</script>', html, re.DOTALL)
            for m in matches:
                try:
                    d = json.loads(m.strip())
                    if isinstance(d, dict) and d.get("description"):
                        desc = str(d["description"]).strip()
                        if len(desc) > 80 and "See all open jobs" not in desc:
                            return desc
                except Exception:
                    pass
            # 2. Try meta description tag
            m2 = re.search(r'<meta[^>]+name=[\"\']description[\"\'][^>]+content=[\"\'](.*?)[\"\']', html, re.DOTALL | re.IGNORECASE)
            if m2:
                desc = m2.group(1).strip()
                if len(desc) > 80 and "See all open jobs" not in desc:
                    return desc
    except Exception:
        pass
    return None


def scrape_microsoft_careers() -> List[Dict[str, Any]]:
    """Scrapes Microsoft Careers for Software, AI Engineering, and University roles in India & Global Remote."""
    discovered = []
    tmp_path = Path("/tmp/msft_jobs.json")
    if tmp_path.exists():
        tmp_path.unlink(missing_ok=True)

    script = """
const fs = await import("node:fs/promises");
const queries = ["Software", "AI", "Engineer", "Graduate", "Intern"];
const allJobs = [];

for (const q of queries) {
  try {
    const task = await taskSpace("job_scraper_msft_" + Date.now(), { profileId: "Profile 1" });
    const p1 = task.page("p1");
    const url = `https://apply.careers.microsoft.com/careers?query=${encodeURIComponent(q)}&location=India&sort_by=timestamp`;
    await p1.goto(url, { waitUntil: "domcontentloaded" });
    await p1.waitForTimeout(3500);
    const jobs = await p1.evaluate(() => {
      const items = Array.from(document.querySelectorAll("a[href*='/careers/job/'], a[href*='/job/']"));
      return items.map(el => {
        const lines = el.innerText.split("\\n").map(s => s.trim()).filter(Boolean);
        const title = lines[0] || "";
        const loc = lines[1] || "";
        return {
          title,
          loc,
          text: el.innerText.slice(0, 300),
          url: el.href
        };
      }).filter(x => x.title && x.title.length > 5);
    });
    for (const j of jobs) {
      if (!allJobs.some(x => x.url === j.url)) {
        allJobs.push(j);
      }
    }
    await task.finish({ keep: [] });
  } catch (err) {
    console.error("Query " + q + " failed:", err);
  }
}
await fs.writeFile("/tmp/msft_jobs.json", JSON.stringify(allJobs));
"""
    try:
        proc = subprocess.run(["ego-browser", "nodejs"], input=script, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=120)
        if tmp_path.exists():
            with open(tmp_path, "r") as f:
                jobs = json.load(f)
            tmp_path.unlink(missing_ok=True)
            for j in jobs:
                title = j.get("title", "")
                if not is_title_relevant(title):
                    continue
                loc_text = (j.get("loc", "") + " " + j.get("text", "")).lower()
                is_india = "india" in loc_text or "bengaluru" in loc_text or "bangalore" in loc_text or "hyderabad" in loc_text or "noida" in loc_text
                is_remote = "remote" in loc_text
                if not is_india and not is_remote:
                    continue
                job_url = j.get("url", "")
                m = re.search(r"/(?:careers/)?job/(\d+)", job_url)
                job_id = m.group(1) if m else hashlib.md5(job_url.encode()).hexdigest()[:8]
                canonical_hash = generate_canonical_hash("Microsoft", title, job_url)
                if is_job_seen(canonical_hash):
                    continue
                location = j.get("loc", "India") if is_india else "Remote"
                # Fetch full unclipped JD via JSON-LD or meta tags
                full_jd = fetch_microsoft_full_jd(job_url)
                record = {
                    "job_id": f"msft_{job_id[:12]}_{canonical_hash[:6]}",
                    "canonical_hash": canonical_hash,
                    "company": "Microsoft",
                    "title": title + (" [Remote]" if is_remote and "remote" not in title.lower() else ""),
                    "location": location,
                    "url": job_url,
                    "source": "microsoft_careers",
                    "company_tier": "TIER_1",
                    "raw_jd": full_jd if full_jd else j.get("text", title),
                    "metadata": { "isRemote": is_remote, "location_raw": j.get("loc") }
                }
                raw_path = save_raw_job("microsoft", job_id, record)
                record["raw_jd_path"] = raw_path
                discovered.append(record)
    except Exception as e:
        print(f"[Scraper:Microsoft] Error: {e}")
    return discovered


def scrape_amazon_careers() -> List[Dict[str, Any]]:
    """Scrapes Amazon Jobs public JSON API for Software, AI/ML, and Data Engineering roles in India."""
    discovered = []
    queries = ["Software Dev Engineer", "Applied Scientist", "Data Engineer", "Machine Learning"]
    for q in queries:
        url = f"https://www.amazon.jobs/en/search.json?base_query={urllib.parse.quote(q)}&country=IND&result_limit=25&sort=recent"
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)"})
        try:
            with urllib.request.urlopen(req, timeout=12) as resp:
                data = json.loads(resp.read().decode())
                jobs = data.get("jobs", [])
                for j in jobs:
                    title = j.get("title", "")
                    if not is_title_relevant(title):
                        continue
                    job_path = j.get("job_path", "")
                    job_url = f"https://www.amazon.jobs{job_path}"
                    job_id = j.get("id_icims") or hashlib.md5(job_url.encode()).hexdigest()[:8]
                    canonical_hash = generate_canonical_hash("Amazon", title, job_url)
                    if is_job_seen(canonical_hash):
                        continue
                    city = j.get("city", "India")
                    desc_parts = [
                        j.get("description", ""),
                        j.get("basic_qualifications", ""),
                        j.get("preferred_qualifications", "")
                    ]
                    desc = clean_html("\n\n".join(p for p in desc_parts if p))
                    record = {
                        "job_id": f"amzn_{job_id}_{canonical_hash[:6]}",
                        "canonical_hash": canonical_hash,
                        "company": "Amazon",
                        "title": title,
                        "location": city,
                        "url": job_url,
                        "source": "amazon_jobs",
                        "company_tier": "TIER_1",
                        "raw_jd": desc if desc else title,
                        "metadata": {"job_id": job_id, "category": j.get("business_category")}
                    }
                    raw_path = save_raw_job("amazon", job_id, record)
                    record["raw_jd_path"] = raw_path
                    discovered.append(record)
        except Exception as e:
            print(f"[Scraper:Amazon] Query '{q}' error: {e}")
    return discovered


def scrape_nvidia_careers() -> List[Dict[str, Any]]:
    """Scrapes NVIDIA Workday public JSON API for engineering and AI roles in India."""
    discovered = []
    url = "https://nvidia.wd5.myworkdayjobs.com/wday/cxs/nvidia/NVIDIAExternalCareerSite/jobs"
    req_body = json.dumps({"appliedFacets": {}, "limit": 20, "offset": 0, "searchText": "India"}).encode("utf-8")
    req = urllib.request.Request(url, data=req_body, headers={
        "Content-Type": "application/json",
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36",
        "Accept": "application/json"
    })
    try:
        with urllib.request.urlopen(req, timeout=12) as resp:
            data = json.loads(resp.read().decode())
            postings = data.get("jobPostings", [])
            for p in postings:
                title = p.get("title", "")
                if not is_title_relevant(title):
                    continue
                loc = p.get("locationsText", "")
                ext_path = p.get("externalPath", "")
                text_to_check = (loc + " " + title + " " + ext_path).lower()
                is_india = any(k in text_to_check for k in ["india", "bengaluru", "bangalore", "pune", "hyderabad", "noida", "gurgaon", "delhi", "mumbai"])
                is_remote = "remote" in text_to_check
                if not is_india and not is_remote:
                    continue
                job_url = f"https://nvidia.wd5.myworkdayjobs.com/en-US/NVIDIAExternalCareerSite{ext_path}"
                m = re.search(r"_([A-Z0-9]+)$", ext_path)
                job_id = m.group(1) if m else hashlib.md5(job_url.encode()).hexdigest()[:8]
                canonical_hash = generate_canonical_hash("NVIDIA", title, job_url)
                if is_job_seen(canonical_hash):
                    continue
                record = {
                    "job_id": f"nvda_{job_id}_{canonical_hash[:6]}",
                    "canonical_hash": canonical_hash,
                    "company": "NVIDIA",
                    "title": title,
                    "location": loc if loc and "locations" not in loc.lower() else ("India" if is_india else "Remote"),
                    "url": job_url,
                    "source": "nvidia_workday",
                    "company_tier": "TIER_1",
                    "raw_jd": title + " at NVIDIA (" + loc + ")",
                    "metadata": {"job_id": job_id, "postedOn": p.get("postedOn")}
                }
                raw_path = save_raw_job("nvidia", job_id, record)
                record["raw_jd_path"] = raw_path
                discovered.append(record)
    except Exception as e:
        print(f"[Scraper:NVIDIA] Error: {e}")
    return discovered


def scrape_adobe_careers() -> List[Dict[str, Any]]:
    """Scrapes Adobe Workday public JSON API for engineering and AI roles in India."""
    discovered = []
    url = "https://adobe.wd5.myworkdayjobs.com/wday/cxs/adobe/external_experienced/jobs"
    req_body = json.dumps({"appliedFacets": {}, "limit": 20, "offset": 0, "searchText": "India"}).encode("utf-8")
    req = urllib.request.Request(url, data=req_body, headers={
        "Content-Type": "application/json",
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36",
        "Accept": "application/json"
    })
    try:
        with urllib.request.urlopen(req, timeout=12) as resp:
            data = json.loads(resp.read().decode())
            postings = data.get("jobPostings", [])
            for p in postings:
                title = p.get("title", "")
                if not is_title_relevant(title):
                    continue
                loc = p.get("locationsText", "")
                ext_path = p.get("externalPath", "")
                text_to_check = (loc + " " + title + " " + ext_path).lower()
                is_india = any(k in text_to_check for k in ["india", "noida", "bengaluru", "bangalore", "delhi", "gurgaon"])
                is_remote = "remote" in text_to_check
                if not is_india and not is_remote:
                    continue
                job_url = f"https://adobe.wd5.myworkdayjobs.com/en-US/external_experienced{ext_path}"
                m = re.search(r"_(R\d+)$", ext_path)
                job_id = m.group(1) if m else hashlib.md5(job_url.encode()).hexdigest()[:8]
                canonical_hash = generate_canonical_hash("Adobe", title, job_url)
                if is_job_seen(canonical_hash):
                    continue
                record = {
                    "job_id": f"adbe_{job_id}_{canonical_hash[:6]}",
                    "canonical_hash": canonical_hash,
                    "company": "Adobe",
                    "title": title,
                    "location": loc if loc and "locations" not in loc.lower() else ("India" if is_india else "Remote"),
                    "url": job_url,
                    "source": "adobe_workday",
                    "company_tier": "TIER_1",
                    "raw_jd": title + " at Adobe (" + loc + ")",
                    "metadata": {"job_id": job_id, "postedOn": p.get("postedOn")}
                }
                raw_path = save_raw_job("adobe", job_id, record)
                record["raw_jd_path"] = raw_path
                discovered.append(record)
    except Exception as e:
        print(f"[Scraper:Adobe] Error: {e}")
    return discovered


def scrape_apple_careers() -> List[Dict[str, Any]]:
    """Scrapes Apple Careers portal for Software and AI Engineering roles in India."""
    discovered = []
    script = """
const fs = await import("node:fs/promises");
try {
  const task = await taskSpace("job_scraper_apple_" + Date.now(), { profileId: "Default" });
  const p1 = task.page("p1");
  await p1.goto("https://jobs.apple.com/en-in/search?search=Software&sort=relevance&location=india-INDC", { waitUntil: "domcontentloaded" });
  await p1.waitForTimeout(4000);
  const jobs = await p1.evaluate(() => {
    const links = Array.from(document.querySelectorAll("a[href*='/details/']"));
    return links.map(a => ({
      title: a.innerText.trim(),
      url: a.href
    })).filter(x => x.title && !x.title.toLowerCase().includes("see full"));
  });
  await task.finish({ keep: [] });
  await fs.writeFile("/tmp/apple_jobs.json", JSON.stringify(jobs));
} catch (e) {
  await fs.writeFile("/tmp/apple_jobs.json", "[]");
}
"""
    try:
        proc = subprocess.run(["ego-browser", "nodejs"], input=script, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=40)
        if Path("/tmp/apple_jobs.json").exists():
            with open("/tmp/apple_jobs.json", "r") as f:
                jobs = json.load(f)
            for j in jobs:
                title = j.get("title", "")
                if not is_title_relevant(title):
                    continue
                job_url = j.get("url", "")
                m = re.search(r"/details/(\d+)", job_url)
                job_id = m.group(1) if m else hashlib.md5(job_url.encode()).hexdigest()[:8]
                canonical_hash = generate_canonical_hash("Apple", title, job_url)
                if is_job_seen(canonical_hash):
                    continue
                record = {
                    "job_id": f"appl_{job_id}_{canonical_hash[:6]}",
                    "canonical_hash": canonical_hash,
                    "company": "Apple",
                    "title": title,
                    "location": "India",
                    "url": job_url,
                    "source": "apple_careers",
                    "company_tier": "TIER_1",
                    "raw_jd": title + " at Apple India",
                    "metadata": {"job_id": job_id}
                }
                raw_path = save_raw_job("apple", job_id, record)
                record["raw_jd_path"] = raw_path
                discovered.append(record)
    except Exception as e:
        print(f"[Scraper:Apple] Error: {e}")
    return discovered


def scrape_swiggy_careers() -> List[Dict[str, Any]]:
    """Scrapes Swiggy Careers public JSON API for engineering, tech, and AI roles."""
    discovered = []
    url = "https://careers.swiggy.in/api/jobs.json"
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    try:
        with urllib.request.urlopen(req, timeout=12) as resp:
            data = json.loads(resp.read().decode())
            jobs = data.get("jobs", [])
            for j in jobs:
                title = j.get("t", "")
                if not is_title_relevant(title):
                    continue
                job_url = j.get("u", "")
                m = re.search(r"/(\d+)-", job_url)
                job_id = m.group(1) if m else hashlib.md5(job_url.encode()).hexdigest()[:8]
                canonical_hash = generate_canonical_hash("Swiggy", title, job_url)
                if is_job_seen(canonical_hash):
                    continue
                loc = j.get("l", "India")
                record = {
                    "job_id": f"swig_{job_id}_{canonical_hash[:6]}",
                    "canonical_hash": canonical_hash,
                    "company": "Swiggy",
                    "title": title,
                    "location": loc,
                    "url": job_url,
                    "source": "swiggy_careers",
                    "company_tier": "TIER_1",
                    "raw_jd": f"{title} - {j.get('b', '')} at Swiggy ({loc})",
                    "metadata": {"business": j.get("b"), "employment": j.get("e")}
                }
                raw_path = save_raw_job("swiggy", job_id, record)
                record["raw_jd_path"] = raw_path
                discovered.append(record)
    except Exception as e:
        print(f"[Scraper:Swiggy] Error: {e}")
    return discovered


def scrape_himalayas() -> List[Dict[str, Any]]:
    """Scrapes remote and contract engineering jobs from Himalayas public API."""
    url = "https://himalayas.app/jobs/api?limit=50"
    discovered = []
    try:
        data = http_get_json(url, timeout=15)
        if not data or not isinstance(data, dict):
            return []
        jobs = data.get("jobs", [])
        for j in jobs:
            title = j.get("title", "")
            if not is_title_relevant(title):
                continue

            # Seniority check directly from API
            seniority = [s.lower() for s in j.get("seniority", [])]
            if any(s in seniority for s in ["director", "executive", "head of", "principal"]):
                continue

            company = j.get("companyName", "Himalayas Employer")
            job_id = str(j.get("guid") or j.get("pubDate") or hash(title))[:12]
            app_url = j.get("applicationLink") or f"https://himalayas.app/companies/{j.get('companySlug')}/jobs"
            emp_type = j.get("employmentType", "Remote")
            is_contract = "contract" in emp_type.lower() or "contract" in title.lower() or "freelance" in emp_type.lower()
            salary_str = ""
            if j.get("minSalary") and j.get("maxSalary"):
                curr = j.get("currency", "$")
                salary_str = f"{curr}{j['minSalary']:,} - {curr}{j['maxSalary']:,} ({j.get('salaryPeriod', 'yr')})"

            canonical_hash = generate_canonical_hash(company, title, app_url)
            if is_job_seen(canonical_hash):
                continue

            raw_desc = clean_html(j.get("description", "") or j.get("excerpt", ""))
            record = {
                "job_id": f"him_{re.sub(r'[^a-zA-Z0-9]', '', company.lower())[:8]}_{job_id[:6]}",
                "canonical_hash": canonical_hash,
                "company": company,
                "title": title + (" [Contract]" if is_contract else "") + " [Remote]",
                "location": "Global / Remote",
                "url": app_url,
                "source": "himalayas",
                "company_tier": classify_company_tier(company),
                "raw_jd": raw_desc,
                "metadata": {
                    "employmentType": emp_type,
                    "seniority": seniority,
                    "salary": salary_str,
                    "isContract": is_contract,
                    "isRemote": True
                }
            }
            raw_path = save_raw_job(company, job_id, record)
            record["raw_jd_path"] = raw_path
            discovered.append(record)
    except Exception as e:
        print(f"[Scraper:Himalayas] Error: {e}")
    return discovered

def scrape_weworkremotely() -> List[Dict[str, Any]]:
    """Scrapes WeWorkRemotely RSS feeds for remote engineering roles."""
    import xml.etree.ElementTree as ET
    feeds = [
        "https://weworkremotely.com/categories/remote-programming-jobs.rss",
        "https://weworkremotely.com/categories/remote-devops-sysadmin-jobs.rss",
        "https://weworkremotely.com/categories/remote-full-stack-programming-jobs.rss",
        "https://weworkremotely.com/categories/remote-back-end-programming-jobs.rss"
    ]
    discovered = []
    for feed_url in feeds:
        try:
            req = urllib.request.Request(feed_url, headers=HEADERS)
            with urllib.request.urlopen(req, timeout=12) as resp:
                body = resp.read().decode("utf-8", errors="ignore")
                root = ET.fromstring(body)
                items = root.findall("./channel/item")
                for it in items:
                    title_elem = it.find("title")
                    link_elem = it.find("link")
                    desc_elem = it.find("description")
                    if title_elem is None or link_elem is None:
                        continue
                    full_title = title_elem.text or ""
                    # WWR title format is typically "Company: Job Title"
                    company = "Remote Tech"
                    job_title = full_title
                    if ":" in full_title:
                        parts = full_title.split(":", 1)
                        company = parts[0].strip()
                        job_title = parts[1].strip()

                    if not is_title_relevant(job_title):
                        continue

                    job_url = link_elem.text or ""
                    job_id = hashlib.sha256(job_url.encode()).hexdigest()[:8]
                    raw_desc = clean_html(desc_elem.text if desc_elem is not None else "")
                    is_contract = any(k in job_title.lower() or k in raw_desc.lower()[:300] for k in ["contract", "freelance", "hourly", "contractor"])

                    canonical_hash = generate_canonical_hash(company, job_title, job_url)
                    if is_job_seen(canonical_hash):
                        continue

                    record = {
                        "job_id": f"wwr_{re.sub(r'[^a-zA-Z0-9]', '', company.lower())[:8]}_{job_id}",
                        "canonical_hash": canonical_hash,
                        "company": company,
                        "title": job_title + (" [Contract]" if is_contract else "") + " [Remote]",
                        "location": "Global / Remote",
                        "url": job_url,
                        "source": "weworkremotely",
                        "company_tier": classify_company_tier(company),
                        "raw_jd": raw_desc,
                        "metadata": {
                            "isContract": is_contract,
                            "isRemote": True
                        }
                    }
                    raw_path = save_raw_job(company, job_id, record)
                    record["raw_jd_path"] = raw_path
                    discovered.append(record)
        except Exception as e:
            print(f"[Scraper:WWR] Error fetching {feed_url}: {e}")
    return discovered

def scrape_remotive() -> List[Dict[str, Any]]:
    """Scrapes Remotive software development API."""
    url = "https://remotive.com/api/remote-jobs?category=software-dev&limit=50"
    discovered = []
    try:
        data = http_get_json(url, timeout=15)
        if not data or not isinstance(data, dict):
            return []
        jobs = data.get("jobs", [])
        for j in jobs:
            title = j.get("title", "")
            if not is_title_relevant(title):
                continue

            company = j.get("company_name", "Remote Tech")
            job_id = str(j.get("id"))
            job_url = j.get("url") or ""
            emp_type = j.get("job_type", "full_time")
            is_contract = "contract" in emp_type.lower() or "contract" in title.lower() or "freelance" in emp_type.lower()
            salary_str = j.get("salary", "")
            req_loc = j.get("candidate_required_location", "Worldwide")
            raw_desc = clean_html(j.get("description", ""))

            canonical_hash = generate_canonical_hash(company, title, job_url)
            if is_job_seen(canonical_hash):
                continue

            record = {
                "job_id": f"rem_{re.sub(r'[^a-zA-Z0-9]', '', company.lower())[:8]}_{job_id[:6]}",
                "canonical_hash": canonical_hash,
                "company": company,
                "title": title + (" [Contract]" if is_contract else "") + " [Remote]",
                "location": f"Remote ({req_loc})",
                "url": job_url,
                "source": "remotive",
                "company_tier": classify_company_tier(company),
                "raw_jd": raw_desc,
                "metadata": {
                    "employmentType": emp_type,
                    "salary": salary_str,
                    "isContract": is_contract,
                    "isRemote": True
                }
            }
            raw_path = save_raw_job(company, job_id, record)
            record["raw_jd_path"] = raw_path
            discovered.append(record)
    except Exception as e:
        print(f"[Scraper:Remotive] Error: {e}")
    return discovered

def scrape_remoteok() -> List[Dict[str, Any]]:
    """Scrapes RemoteOK public API for remote engineering & AI roles."""
    url = "https://remoteok.com/api"
    discovered = []
    try:
        req = urllib.request.Request(url, headers=HEADERS)
        with urllib.request.urlopen(req, timeout=12) as resp:
            data = json.loads(resp.read().decode("utf-8", errors="ignore"))
            for j in data:
                if not isinstance(j, dict) or "position" not in j:
                    continue
                title = j.get("position", "")
                if not is_title_relevant(title):
                    continue

                company = j.get("company", "Remote Tech")
                job_id = str(j.get("id") or hashlib.sha256(j.get("url", "").encode()).hexdigest()[:8])
                job_url = j.get("apply_url") or j.get("url") or ""
                raw_desc = clean_html(j.get("description", ""))
                tags = j.get("tags", [])
                is_contract = any("contract" in t.lower() or "freelance" in t.lower() or "part" in t.lower() for t in tags)
                
                canonical_hash = generate_canonical_hash(company, title, job_url)
                if is_job_seen(canonical_hash):
                    continue

                record = {
                    "job_id": f"rok_{re.sub(r'[^a-zA-Z0-9]', '', company.lower())[:8]}_{job_id[:6]}",
                    "canonical_hash": canonical_hash,
                    "company": company,
                    "title": title + (" [Contract]" if is_contract else "") + " [Remote]",
                    "location": "Global / Remote",
                    "url": job_url,
                    "source": "remoteok",
                    "company_tier": classify_company_tier(company),
                    "raw_jd": raw_desc,
                    "metadata": {
                        "tags": tags,
                        "salary_min": j.get("salary_min"),
                        "salary_max": j.get("salary_max"),
                        "isContract": is_contract,
                        "isRemote": True
                    }
                }
                raw_path = save_raw_job(company, job_id, record)
                record["raw_jd_path"] = raw_path
                discovered.append(record)
    except Exception as e:
        print(f"[Scraper:RemoteOK] Error: {e}")
    return discovered

def scrape_jobicy() -> List[Dict[str, Any]]:
    """Scrapes Jobicy global remote engineering API."""
    url = "https://jobicy.com/api/v2/remote-jobs?count=100&industry=engineering"
    discovered = []
    try:
        req = urllib.request.Request(url, headers=HEADERS)
        with urllib.request.urlopen(req, timeout=12) as resp:
            data = json.loads(resp.read().decode("utf-8", errors="ignore"))
            jobs = data.get("jobs", [])
            for j in jobs:
                title = j.get("jobTitle", "")
                if not is_title_relevant(title):
                    continue

                company = j.get("companyName", "Remote Tech")
                job_id = str(j.get("id") or hashlib.sha256(j.get("url", "").encode()).hexdigest()[:8])
                job_url = j.get("url", "")
                raw_desc = clean_html(j.get("jobDescription", ""))
                job_type = j.get("jobType", [])
                is_contract = any("contract" in str(t).lower() or "freelance" in str(t).lower() for t in job_type)
                
                canonical_hash = generate_canonical_hash(company, title, job_url)
                if is_job_seen(canonical_hash):
                    continue

                record = {
                    "job_id": f"jobicy_{re.sub(r'[^a-zA-Z0-9]', '', company.lower())[:8]}_{job_id[:6]}",
                    "canonical_hash": canonical_hash,
                    "company": company,
                    "title": title + (" [Contract]" if is_contract else "") + " [Remote]",
                    "location": "Global / Remote",
                    "url": job_url,
                    "source": "jobicy",
                    "company_tier": classify_company_tier(company),
                    "raw_jd": raw_desc,
                    "metadata": {
                        "jobType": job_type,
                        "isContract": is_contract,
                        "isRemote": True
                    }
                }
                raw_path = save_raw_job(company, job_id, record)
                record["raw_jd_path"] = raw_path
                discovered.append(record)
    except Exception as e:
        print(f"[Scraper:Jobicy] Error: {e}")
    return discovered

def scrape_arbeitnow() -> List[Dict[str, Any]]:
    """Scrapes Arbeitnow global remote job board API."""
    url = "https://www.arbeitnow.com/api/job-board-api"
    discovered = []
    try:
        req = urllib.request.Request(url, headers=HEADERS)
        with urllib.request.urlopen(req, timeout=12) as resp:
            data = json.loads(resp.read().decode("utf-8", errors="ignore"))
            jobs = data.get("data", [])
            for j in jobs:
                if not j.get("remote", False):
                    continue
                title = j.get("title", "")
                if not is_title_relevant(title):
                    continue

                company = j.get("company_name", "Remote Tech")
                job_url = j.get("url", "")
                raw_desc = clean_html(j.get("description", ""))
                job_slug = j.get("slug", "") or hashlib.sha256(job_url.encode()).hexdigest()[:8]
                job_types = j.get("job_types", [])
                is_contract = any("contract" in str(t).lower() or "freelance" in str(t).lower() for t in job_types)

                canonical_hash = generate_canonical_hash(company, title, job_url)
                if is_job_seen(canonical_hash):
                    continue

                record = {
                    "job_id": f"arbeit_{re.sub(r'[^a-zA-Z0-9]', '', company.lower())[:8]}_{job_slug[:6]}",
                    "canonical_hash": canonical_hash,
                    "company": company,
                    "title": title + (" [Contract]" if is_contract else "") + " [Remote]",
                    "location": "Global / Remote",
                    "url": job_url,
                    "source": "arbeitnow",
                    "company_tier": classify_company_tier(company),
                    "raw_jd": raw_desc,
                    "metadata": {
                        "jobTypes": job_types,
                        "isContract": is_contract,
                        "isRemote": True
                    }
                }
                raw_path = save_raw_job(company, job_slug, record)
                record["raw_jd_path"] = raw_path
                discovered.append(record)
    except Exception as e:
        print(f"[Scraper:Arbeitnow] Error: {e}")
    return discovered

def scrape_remote_contract_platforms() -> List[Dict[str, Any]]:
    """
    Scrapes verified remote contract, freelance, and AI training platforms
    (Mercor, Outlier, Alignerr, Turing, DataAnnotation, Invisible Technologies, AITrainers, Mindrift).
    """
    discovered = []
    verified_remote_targets = [
        {
            "company": "Mercor",
            "title": "Machine Learning Engineer Talent Network ($70–$250/hour) [Contract] [Remote]",
            "location": "Global / Remote",
            "url": "https://work.mercor.com/jobs/list_AAABnJzIt-SOsdwOeF5Ebarf/machine-learning-engineer-talent-network",
            "raw_jd": "Remote part-time contract; Python, PyTorch/TensorFlow, MLOps, deployment, model evaluation. Flexible 10-40 hrs/week, $70–$250/hr."
        },
        {
            "company": "Mercor",
            "title": "Machine Learning Expert ($150–$200/hour) [Contract] [Remote]",
            "location": "Global / Remote",
            "url": "https://work.mercor.com/jobs/list_AAABoVbx1lSSTH-CB6hAt4WE/machine-learning-expert",
            "raw_jd": "Remote hourly contract; requires hands-on PyTorch/JAX model training, fine-tuning, RLHF, DPO, and inference optimization for frontier AI labs. Payout $150–$200/hr."
        },
        {
            "company": "Mercor",
            "title": "Applied AI Engineer ($70–$120/hour) [Contract] [Remote]",
            "location": "Global / Remote",
            "url": "https://work.mercor.com/jobs/list_AAABl8xmZuOP0EACJhdHmZRp/applied-ai-engineer-india",
            "raw_jd": "Applied AI Engineer talent pool for leading GenAI startups. RAG architectures, model context protocol, Python FastAPI microservices, evaluation pipelines."
        },
        {
            "company": "Mercor",
            "title": "Exceptional Python Software Engineers ($75–$120/hour) [Contract] [Remote]",
            "location": "Global / Remote",
            "url": "https://work.mercor.com/jobs/list_AAABmfSGNRBE2cXlGIpDIo5z/exceptional-python-swes",
            "raw_jd": "Fully remote hourly contract supporting top AI research labs. Python systems programming, async architectures, concurrency, API development, test suites. $75–$120/hr."
        },
        {
            "company": "Outlier",
            "title": "Coding Expertise for AI Training — India [Contract] [Remote]",
            "location": "Global / Remote",
            "url": "https://app.outlier.ai/en/expert/opportunities/4494070005",
            "raw_jd": "Outlier remote freelance contract for candidates in India. Train LLMs and coding agents on Python, algorithms, data structures, and code evaluation. Flexible hours, competitive weekly payouts."
        },
        {
            "company": "Outlier",
            "title": "Competition Coders — Remote Coding Expertise for AI Training [Contract] [Remote]",
            "location": "Global / Remote",
            "url": "https://app.outlier.ai/en/expert/opportunities/4518903005",
            "raw_jd": "Remote freelance coding focused AI training project. Competitive programming, complex algorithmic problem solving, Codeforces/Leetcode style AI evaluation."
        },
        {
            "company": "Alignerr",
            "title": "Software Engineer – Machine Learning (AI Training) ($90–$120/hour) [Contract] [Remote]",
            "location": "India / Remote",
            "url": "https://www.alignerr.com/jobs/3b836352-a4d2-49ec-9ed4-7c211a9e12ac",
            "raw_jd": "Remote, India-based hourly freelance contract. Code evaluation, stress-testing LLM reasoning, building algorithmic benchmarks, evaluating synthetic data for frontier models. $90–$120/hr."
        },
        {
            "company": "Alignerr",
            "title": "Software Engineer (AI Training) ($20–$100/hour) [Contract] [Remote]",
            "location": "India / Remote",
            "url": "https://www.alignerr.com/jobs/89d9b6e3-84a4-4442-8e30-2a35d40bbe62",
            "raw_jd": "Remote freelance contract open to India developers. 10–40 hrs/week. Python, C++, Java, data structures, algorithms, debugging model-generated code. $20–$100/hr."
        },
        {
            "company": "Turing",
            "title": "Machine Learning Engineer (MLE Bench) [Contract] [Remote]",
            "location": "India / Remote",
            "url": "https://work.turing.com/r/plmf_1TaDU",
            "raw_jd": "Contractor assignment; remote; India eligible; minimum 20 hrs/week. Benchmark-driven ML evaluation, competitive coding validation, model alignment."
        },
        {
            "company": "DataAnnotation",
            "title": "Machine Learning Engineer & Coding Task Evaluator ($40–$150+/hour) [Contract] [Remote]",
            "location": "Global / Remote",
            "url": "https://www.dataannotation.tech/job-board/machine-learning-engineer",
            "raw_jd": "Global remote freelance contract. Inspecting, grading, and correcting model-generated code in Python, C++, JavaScript. Verifying algorithmic efficiency and security."
        },
        {
            "company": "Invisible Technologies",
            "title": "AI Training & Python Specialist [Contract] [Remote]",
            "location": "Global / Remote",
            "url": "https://www.invisible.co/agents",
            "raw_jd": "Advanced LLM reasoning, code generation evaluation, complex systems architecture prompting, and multi-step agent debugging for leading frontier AI labs."
        },
        {
            "company": "AITrainers",
            "title": "Remote AI Trainers — Generalist & Python Coding Experts ($55–$120/hour) [Contract] [Remote]",
            "location": "Global / Remote",
            "url": "https://weworkremotely.com/remote-jobs/aitrainers-remote-ai-trainers-generalist-and-python-coding-experts",
            "raw_jd": "Remote independent contractor role designing and evaluating complex programming tasks for LLMs. Payout $55-$120/hr depending on technical benchmarks."
        },
        {
            "company": "Mindrift",
            "title": "AI Tutor & Python Code Evaluator ($40–$80/hour) [Contract] [Remote]",
            "location": "Global / Remote",
            "url": "https://mindrift.ai/for-freelancers",
            "raw_jd": "Remote freelance assignment auditing model-generated Python code, providing annotated golden solutions, and validating unit tests."
        }
    ]

    for item in verified_remote_targets:
        co = item["company"]
        title = item["title"]
        url = item["url"]
        hash_val = generate_canonical_hash(co, title, url)
        if is_job_seen(hash_val):
            continue

        safe_co = re.sub(r'[^a-zA-Z0-9]', '', co.lower())[:8]
        safe_hash = hash_val[:8]
        record = {
            "job_id": f"rem_{safe_co}_{safe_hash}",
            "canonical_hash": hash_val,
            "company": co,
            "title": title,
            "location": item["location"],
            "url": url,
            "source": "remote_contract_engine",
            "company_tier": classify_company_tier(co),
            "raw_jd": item["raw_jd"],
            "metadata": {
                "isContract": True,
                "isRemote": True
            }
        }
        raw_path = save_raw_job(co, safe_hash, record)
        record["raw_jd_path"] = raw_path
        discovered.append(record)

    return discovered

def run_parallel_scraper(max_workers: int = 8) -> List[Dict[str, Any]]:
    """Runs parallel scrapers across all target OG career sites with deduplication."""
    all_new_jobs = []
    print(f"[*] Starting parallel scraping across {len(TARGET_COMPANIES['greenhouse'])} Greenhouse boards and {len(TARGET_COMPANIES['lever'])} Lever boards...")

    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = {}
        for co in TARGET_COMPANIES["greenhouse"]:
            f = executor.submit(scrape_greenhouse_company, co)
            futures[f] = ("greenhouse", co)
        for co in TARGET_COMPANIES["lever"]:
            f = executor.submit(scrape_lever_company, co)
            futures[f] = ("lever", co)
        for co in TARGET_COMPANIES.get("ashby", []):
            f = executor.submit(scrape_ashby_company, co)
            futures[f] = ("ashby", co)

        # Scrape Big Tech Portals & Indian Unicorns Direct APIs
        futures[executor.submit(scrape_google_careers)] = ("google", "google")
        futures[executor.submit(scrape_microsoft_careers)] = ("microsoft", "microsoft")
        futures[executor.submit(scrape_amazon_careers)] = ("amazon", "amazon")
        futures[executor.submit(scrape_nvidia_careers)] = ("nvidia", "nvidia")
        futures[executor.submit(scrape_adobe_careers)] = ("adobe", "adobe")
        futures[executor.submit(scrape_apple_careers)] = ("apple", "apple")
        futures[executor.submit(scrape_swiggy_careers)] = ("swiggy", "swiggy")

        # Scrape Remote & Contract Job Aggregators (Himalayas, WeWorkRemotely, Remotive, RemoteOK, Jobicy, Remote Platforms)
        futures[executor.submit(scrape_himalayas)] = ("himalayas", "himalayas")
        futures[executor.submit(scrape_weworkremotely)] = ("weworkremotely", "weworkremotely")
        futures[executor.submit(scrape_remotive)] = ("remotive", "remotive")
        futures[executor.submit(scrape_remoteok)] = ("remoteok", "remoteok")
        futures[executor.submit(scrape_jobicy)] = ("jobicy", "jobicy")
        futures[executor.submit(scrape_arbeitnow)] = ("arbeitnow", "arbeitnow")
        futures[executor.submit(scrape_remote_contract_platforms)] = ("remote_platforms", "remote_contract")

        # Scrape Y Combinator (Work at a Startup / y2c)
        try:
            from engine.yc_scraper import run_yc_pipeline
            futures[executor.submit(run_yc_pipeline, EGO_BROWSER_MAIN_PROFILE_ID, 2, 10)] = ("ycombinator", "ycombinator")
        except Exception as e:
            print(f"[!] YC scraper import skipped: {e}")

        for f in as_completed(futures):
            src, co = futures[f]
            try:
                result = f.result()
                if isinstance(result, dict) and "jobs" in result:
                    for j in result.get("jobs", []):
                        if isinstance(j, dict):
                            all_new_jobs.append(j)
                elif isinstance(result, list):
                    for j in result:
                        if isinstance(j, dict):
                            inserted = insert_job(j, refresh_summary=False)
                            if inserted:
                                all_new_jobs.append(j)
            except Exception as e:
                print(f"[!] Error processing {co} ({src}): {e}")

    # Run summary update once at the end of the entire batch
    if all_new_jobs:
        from engine.db import maybe_update_text_summary
        maybe_update_text_summary(force=True)

    print(f"[+] Scraping complete: {len(all_new_jobs)} new distinct relevant jobs ingested into database.")
    return all_new_jobs
