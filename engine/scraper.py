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
    EGO_BROWSER_PROFILE_ID
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

# Curated list of target tech companies using Greenhouse, Lever, and Ashby
TARGET_COMPANIES = {
    "greenhouse": [
        "databricks", "stripe", "scaleai", "figma", "notion", "glean",
        "pinecone", "cohere", "anthropic", "browserbase", "modal", "vercel",
        "postman", "brex", "ramp", "rippling", "airtable", "supabase", "inmobi"
    ],
    "lever": [
        "atlassian", "together", "baseten", "perplexity", "replicate", "meesho", "cred"
    ],
    "ashby": [
        "openai", "langchain", "mercor", "cursor"
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
        "systems", "platform", "infrastructure", "etl", "python", "developer", "swe", "sde"
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
    script = """
const fs = await import("node:fs/promises");
const task = await taskSpace("job_scraper_google", { profileId: "Default" });
const p1 = task.page("p1");
await p1.goto("https://www.google.com/about/careers/applications/jobs/results/?q=Software%20Engineer&location=India");
await p1.waitForTimeout(4000);
const jobs = await p1.evaluate(() => {
  const items = Array.from(document.querySelectorAll("a[href*=\\"/jobs/results/\\"]"));
  return items.map(el => ({
    title: el.innerText.split("\\n")[0].trim(),
    text: el.innerText.slice(0, 300),
    url: el.href
  })).filter(x => x.title && x.title.length > 5 && !x.title.includes("Search"));
});
await task.finish({ keep: [] });
await fs.writeFile("/tmp/google_jobs.json", JSON.stringify(jobs));
"""
    try:
        proc = subprocess.run(["ego-browser", "nodejs", "-e", script], stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=40)
        if Path("/tmp/google_jobs.json").exists():
            with open("/tmp/google_jobs.json", "r") as f:
                jobs = json.load(f)
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

def scrape_microsoft_careers() -> List[Dict[str, Any]]:
    """Scrapes Microsoft Careers for Software & AI Engineering roles."""
    discovered = []
    script = """
const fs = await import("node:fs/promises");
const task = await taskSpace("job_scraper_msft", { profileId: "Default" });
const p1 = task.page("p1");
await p1.goto("https://jobs.careers.microsoft.com/global/en/search?q=Software%20Engineer&lc=India");
await p1.waitForTimeout(4000);
const jobs = await p1.evaluate(() => {
  const items = Array.from(document.querySelectorAll("a[href*=\\"/job/\\"]"));
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
await task.finish({ keep: [] });
await fs.writeFile("/tmp/msft_jobs.json", JSON.stringify(jobs));
"""
    try:
        proc = subprocess.run(["ego-browser", "nodejs", "-e", script], stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=40)
        if Path("/tmp/msft_jobs.json").exists():
            with open("/tmp/msft_jobs.json", "r") as f:
                jobs = json.load(f)
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
                m = re.search(r"/job/(\d+)", job_url)
                job_id = m.group(1) if m else hashlib.md5(job_url.encode()).hexdigest()[:8]
                canonical_hash = generate_canonical_hash("Microsoft", title, job_url)
                if is_job_seen(canonical_hash):
                    continue
                location = j.get("loc", "India") if is_india else "Remote"
                record = {
                    "job_id": f"msft_{job_id[:12]}_{canonical_hash[:6]}",
                    "canonical_hash": canonical_hash,
                    "company": "Microsoft",
                    "title": title + (" [Remote]" if is_remote and "remote" not in title.lower() else ""),
                    "location": location,
                    "url": job_url,
                    "source": "microsoft_careers",
                    "company_tier": "TIER_1",
                    "raw_jd": j.get("text", title),
                    "metadata": { "isRemote": is_remote, "location_raw": j.get("loc") }
                }
                raw_path = save_raw_job("microsoft", job_id, record)
                record["raw_jd_path"] = raw_path
                discovered.append(record)
    except Exception as e:
        print(f"[Scraper:Microsoft] Error: {e}")
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
        "https://weworkremotely.com/categories/remote-devops-sysadmin-jobs.rss"
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

def scrape_remote_contract_platforms() -> List[Dict[str, Any]]:
    """
    Scrapes verified remote contract, freelance, and AI training platforms
    (Mercor, Outlier, Alignerr, Turing, DataAnnotation, Invisible Technologies).
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

        # Scrape Google & Microsoft
        futures[executor.submit(scrape_google_careers)] = ("google", "google")
        futures[executor.submit(scrape_microsoft_careers)] = ("microsoft", "microsoft")

        # Scrape Remote & Contract Job Aggregators (Himalayas, WeWorkRemotely, Remotive, Remote Platforms)
        futures[executor.submit(scrape_himalayas)] = ("himalayas", "himalayas")
        futures[executor.submit(scrape_weworkremotely)] = ("weworkremotely", "weworkremotely")
        futures[executor.submit(scrape_remotive)] = ("remotive", "remotive")
        futures[executor.submit(scrape_remote_contract_platforms)] = ("remote_platforms", "remote_contract")

        for f in as_completed(futures):
            src, co = futures[f]
            try:
                jobs = f.result()
                for j in jobs:
                    inserted = insert_job(j)
                    if inserted:
                        all_new_jobs.append(j)
            except Exception as e:
                print(f"[!] Error processing {co} ({src}): {e}")

    print(f"[+] Scraping complete: {len(all_new_jobs)} new distinct relevant jobs ingested into database.")
    return all_new_jobs
