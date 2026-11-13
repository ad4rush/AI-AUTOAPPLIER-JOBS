#!/usr/bin/env python3
"""
Naukri Autonomous Job Scraper & Extractor Plugin.
Operates via ego-browser on Profile 1 (or configured profile) with CDP geolocation stubbing.
Scrapes verified India early-career (0-2 Yrs) and Remote tech postings from Naukri.com,
evaluates them against candidate criteria, and ingests into SQLite database.
"""

import sys
import re
import json
import time
import argparse
import subprocess
from pathlib import Path
from typing import Dict, Any, List

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from engine.config import EGO_BROWSER_MAIN_PROFILE_ID
from engine.db import insert_job, generate_canonical_hash, is_job_seen, update_text_summary
from engine.evaluator import evaluate_job_match
from engine.scraper import is_title_relevant, save_raw_job, classify_company_tier

NAUKRI_TARGET_PATHS = [
    ("https://www.naukri.com/ai-engineer-jobs-in-india?experience=0&experience=2", "India"),
    ("https://www.naukri.com/remote-ai-engineer-jobs", "Remote"),
    ("https://www.naukri.com/machine-learning-engineer-jobs-in-india?experience=0&experience=2", "India"),
    ("https://www.naukri.com/remote-software-engineer-jobs", "Remote"),
    ("https://www.naukri.com/software-engineer-jobs-in-delhi-ncr?experience=0&experience=2", "India"),
    ("https://www.naukri.com/software-engineer-jobs-in-bengaluru?experience=0&experience=2", "India"),
]

def scrape_naukri_jobs(
    max_per_query: int = 20,
    profile_id: str = EGO_BROWSER_MAIN_PROFILE_ID,
    task_space_name: str = "naukri_scraper"
) -> Dict[str, Any]:
    """
    Scrapes targeted engineering queries from Naukri.com using ego-browser.
    """
    urls_json = json.dumps([p[0] for p in NAUKRI_TARGET_PATHS])

    node_script = f"""
const spaces = await listTaskSpaces();
let existing = spaces.find(s => s.name === "{task_space_name}");
let task;
if (existing) {{
  if (existing.ownership === "agent") {{
    task = await taskSpace(existing.id);
  }} else {{
    try {{
      task = await takeOverTaskSpace(existing.id);
    }} catch(e) {{
      task = await taskSpace("{task_space_name}_" + Date.now(), {{ profileId: "{profile_id}" }});
    }}
  }}
}} else {{
  task = await taskSpace("{task_space_name}", {{ profileId: "{profile_id}" }});
}}

const page = task.page("p1");

// Prevent geolocation dialog from ever triggering pause
try {{
  await page.cdp("Page.addScriptToEvaluateOnNewDocument", {{
    source: `
      navigator.geolocation.getCurrentPosition = function(s, e) {{ if (e) e({{ code: 1, message: "denied" }}); }};
      navigator.geolocation.watchPosition = function(s, e) {{ if (e) e({{ code: 1, message: "denied" }}); return 0; }};
    `
  }});
}} catch (e) {{}}

const targetUrls = {urls_json};
const allJobs = [];
const seenUrls = new Set();

for (const targetUrl of targetUrls) {{
  console.log("[Naukri-Scraper] Loading: " + targetUrl);
  try {{
    await page.goto(targetUrl, {{ waitUntil: "domcontentloaded", timeout: 30000 }});
    await new Promise(r => setTimeout(r, 3500));

    const pageJobs = await page.evaluate((limit) => {{
      const cards = Array.from(document.querySelectorAll(".srp-jobtuple-wrapper, .cust-job-tuple"));
      const extracted = [];
      const localSeen = new Set();
      for (const c of cards) {{
        const title = c.querySelector("a.title")?.innerText?.trim();
        const comp = c.querySelector("a.comp-name, .comp-name-link")?.innerText?.trim() || "Tech Enterprise";
        const exp = c.querySelector(".exp-wrap")?.innerText?.trim() || "";
        const loc = c.querySelector(".loc-wrap")?.innerText?.trim() || "India";
        const href = c.querySelector("a.title")?.href;
        const desc = c.querySelector(".job-desc, .row4")?.innerText?.trim() || "";
        if (title && href && !localSeen.has(href)) {{
          localSeen.add(href);
          extracted.push({{ title, company: comp, exp, location: loc, url: href, desc }});
        }}
        if (extracted.length >= limit) break;
      }}
      return extracted;
    }}, {max_per_query});

    for (const j of pageJobs) {{
      if (!seenUrls.has(j.url)) {{
        seenUrls.add(j.url);
        allJobs.push(j);
      }}
    }}
  }} catch (e) {{
    console.log("[Naukri-Scraper] Error loading " + targetUrl + ": " + e.message);
  }}
}}

console.log("JSON_RESULT:" + JSON.stringify({{
  status: "SUCCESS",
  total_found: allJobs.length,
  jobs: allJobs
}}));
"""
    try:
        proc = subprocess.run(
            ["ego-browser", "nodejs"],
            input=node_script,
            text=True,
            capture_output=True,
            timeout=120
        )
        combined = (proc.stdout or "") + "\n" + (proc.stderr or "")
        for line in combined.splitlines():
            line = line.strip()
            if line.startswith("JSON_RESULT:"):
                payload = line.replace("JSON_RESULT:", "", 1).strip()
                return json.loads(payload)
        return {"status": "ERROR", "message": combined[:400]}
    except Exception as e:
        return {"status": "ERROR", "message": str(e)}


def ingest_naukri_jobs(raw_jobs: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """
    Filters, evaluates, and ingests scraped Naukri postings into jobs.db.
    """
    ingested = []
    for item in raw_jobs:
        title = item.get("title", "")
        company = item.get("company", "Tech Company")
        url = item.get("url", "")
        location = item.get("location", "India")
        exp = item.get("exp", "")
        desc = item.get("desc", "")

        # Skip high seniority: 4+ yrs, 5+, 8+
        if any(h in exp for h in ["4-", "5-", "6-", "7-", "8-", "9-", "10-", "5+", "8+", "10+"]):
            continue

        if not is_title_relevant(title):
            continue

        canon_hash = generate_canonical_hash(company, title, url)
        if is_job_seen(canon_hash):
            continue

        ev = evaluate_job_match(company, title, desc, location)
        status = "EVALUATED" if ev["priority_level"] != "SKIP" else "SKIPPED"

        job_id = f"nk_{re.sub(r'[^a-zA-Z0-9]', '', company.lower())[:8]}_{canon_hash[:8]}"
        record = {
            "job_id": job_id,
            "canonical_hash": canon_hash,
            "company": company,
            "title": title,
            "location": location,
            "url": url,
            "source": "naukri",
            "company_tier": ev["company_tier"],
            "match_score": ev["match_score"],
            "fit_verdict": ev["fit_verdict"],
            "priority_level": ev["priority_level"],
            "status": status,
            "raw_jd": desc or f"{title} at {company}. Experience: {exp}. Location: {location}.",
            "notes": f"[{ev['experience_status']}] Matched: {', '.join(ev['matched_skills'][:5])}"
        }

        raw_path = save_raw_job("naukri", job_id, record)
        record["raw_jd_path"] = raw_path

        if insert_job(record):
            ingested.append(record)
            print(f"[+] Ingested [{ev['priority_level']}] {company} — {title} ({ev['match_score']}%) -> {status}")

    if ingested:
        update_text_summary()
    return ingested


def run_naukri_pipeline(profile_id: str = EGO_BROWSER_MAIN_PROFILE_ID) -> Dict[str, Any]:
    """Runs end-to-end Naukri discovery and ingestion."""
    print(f"\n[*] Executing Naukri Multi-Query Discovery in {profile_id}...")
    res = scrape_naukri_jobs(max_per_query=20, profile_id=profile_id)
    if res.get("status") == "SUCCESS":
        jobs = res.get("jobs", [])
        ingested = ingest_naukri_jobs(jobs)
        print(f"[+] Naukri pipeline complete: {len(ingested)} new jobs ingested.")
        return {"status": "SUCCESS", "total_scraped": len(jobs), "total_ingested": len(ingested), "jobs": ingested}
    else:
        print(f"[!] Naukri scraper error: {res.get('message')}")
        return res

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Naukri Autonomous Job Scraper")
    parser.add_argument("--profile", default=EGO_BROWSER_MAIN_PROFILE_ID, help="Ego-browser profile ID")
    args = parser.parse_args()
    run_naukri_pipeline(profile_id=args.profile)
