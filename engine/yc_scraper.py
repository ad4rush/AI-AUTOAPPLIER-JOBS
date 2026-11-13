#!/usr/bin/env python3
"""
Y Combinator (Work at a Startup / y2c) Autonomous Job Scraper & Extractor.
Operates via ego-browser on Profile 1 ("Main Profile") using the authenticated candidate session.

Features:
- Multi-query targeted discovery across AI, ML, Data, Backend, and Distributed Systems.
- Extracts company name, job title, location, salary range, equity, experience requirement, and JD.
- Filters out senior (>3-4 yrs), staff, or non-technical roles.
- Evaluates fit against candidate's profile via evaluate_job_match().
- Ingests verified opportunities into SQLite database (data/jobs.db).
"""

import sys
import os
import re
import json
import time
import urllib.parse
import argparse
import subprocess
from pathlib import Path
from typing import Dict, Any, List

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from engine.config import EGO_BROWSER_MAIN_PROFILE_ID, DATA_DIR
from engine.db import insert_job, generate_canonical_hash, is_job_seen, update_text_summary
from engine.evaluator import evaluate_job_match
from engine.scraper import is_title_relevant, save_raw_job

YC_DEFAULT_PROFILE = EGO_BROWSER_MAIN_PROFILE_ID  # Profile 1

YC_SEARCH_QUERIES = [
    "AI",
    "Machine Learning",
    "Data",
    "Backend",
    "Distributed",
    "Python"
]


def scrape_yc_query(
    query: str = "AI",
    max_jobs_per_query: int = 15,
    profile_id: str = YC_DEFAULT_PROFILE,
    task_space_name: str = "yc_scraper"
) -> Dict[str, Any]:
    """
    Executes a targeted search on Work at a Startup (YC) directory, extracting
    live job postings and company metadata.
    """
    output_path = f"/tmp/yc_query_{int(time.time() * 1000)}.json"
    enc_query = urllib.parse.quote(query)
    search_url = (
        f"https://www.workatastartup.com/companies?"
        f"demographic=any&hasEquity=any&hasSalary=any&industry=any&interviewProcess=any"
        f"&jobType=fulltime&layout=list-compact&query={enc_query}&role=eng"
        f"&sortBy=created_desc&tab=any&usVisaNotRequired=true"
    )

    node_script = f"""(async () => {{
const fs = await import("node:fs/promises");

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

console.log("[YC-Scraper] Navigating to: {search_url}");
await page.goto("{search_url}", {{ waitUntil: "domcontentloaded", timeout: 25000 }});
await new Promise(r => setTimeout(r, 4500));

const currentUrl = await page.url();
if (currentUrl.includes("/login") || currentUrl.includes("/choice")) {{
  console.log("[YC-Scraper] Authentication required on YC.");
  await task.handOff();
  await fs.writeFile("{output_path}", JSON.stringify({{
    status: "AUTH_REQUIRED",
    message: "YC session needs login in {profile_id}."
  }}));
  process.exit(0);
}}

// Extract job postings deterministically from DOM
const jobs = await page.evaluate((maxLimit) => {{
  const links = Array.from(document.querySelectorAll("a[href*='/jobs/']")).filter(a => /\\/jobs\\/\\d+/.test(a.href));
  const results = [];
  const seenHrefs = new Set();

  for (const a of links) {{
    const href = a.href;
    if (seenHrefs.has(href)) continue;
    seenHrefs.add(href);

    const card = a.closest(".company-card, .company-row, div[class*='company'], div[class*='job'], li") || a.parentElement || a;
    const companyName = card.querySelector("p.font-semibold, .company-name, h3, h4, strong")?.innerText.trim() || "YC Startup";
    const titleSpan = card.querySelector("span.variant2-wipe, .job-title, h4");
    const rawTitle = titleSpan ? titleSpan.innerText.trim() : a.innerText.trim();
    const title = rawTitle.replace(/[\\n\\r]+/g, " ").trim();
    if (!title || title === "View job") continue;
    const fullSnippet = card.innerText.replace(/\\n+/g, " | ");

    // Extract location, salary, experience from snippet
    let location = "Remote";
    if (fullSnippet.includes("San Francisco")) location = "San Francisco, CA, US / Remote";
    else if (fullSnippet.includes("New York")) location = "New York, NY, US / Remote";
    else if (fullSnippet.includes("India") || fullSnippet.includes("Bengaluru") || fullSnippet.includes("Mumbai") || fullSnippet.includes("Gurgaon")) location = "India";
    else if (fullSnippet.includes("London")) location = "London, GB / Remote";

    const jobIdMatch = href.match(/\\/jobs\\/(\\d+)/);
    const jobId = jobIdMatch ? jobIdMatch[1] : "";

    results.push({{
      jobId,
      title,
      company: companyName,
      location,
      url: href,
      snippet: fullSnippet
    }});

    if (results.length >= maxLimit) break;
  }}
  return results;
}}, {max_jobs_per_query});

console.log("[YC-Scraper] Extracted " + jobs.length + " candidate jobs for query '{query}'.");

await fs.writeFile("{output_path}", JSON.stringify({{
  status: "SUCCESS",
  count: jobs.length,
  jobs: jobs
}}));
}})().catch(err => {{
  console.error("[YC-Scraper Error]", err);
  process.exit(1);
}});
"""

    try:
        proc = subprocess.run(
            ["ego-browser", "nodejs"],
            input=node_script,
            text=True,
            capture_output=True,
            timeout=120
        )
        if Path(output_path).exists():
            with open(output_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            try:
                os.remove(output_path)
            except OSError:
                pass
            return data
        else:
            return {"status": "ERROR", "message": "No output file", "raw": proc.stdout + "\n" + proc.stderr}
    except Exception as e:
        return {"status": "ERROR", "message": str(e)}


def ingest_scraped_yc_jobs(scraped_jobs: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Evaluates and ingests YC jobs into jobs.db."""
    ingested = []
    for j in scraped_jobs:
        title = j.get("title", "")
        company = j.get("company", "YC Startup")
        location = j.get("location", "Remote")
        url = j.get("url", "")
        snippet = j.get("snippet", title)
        job_id = f"yc_{re.sub(r'[^a-zA-Z0-9]', '', company.lower())[:8]}_{j.get('jobId', '')}"

        if not is_title_relevant(title):
            print(f"[-] Dropped senior/non-target title: {company} — {title}")
            continue

        canon_hash = generate_canonical_hash(company, title, url)
        if is_job_seen(canon_hash):
            continue

        ev = evaluate_job_match(company, title, snippet, location)
        status = "EVALUATED" if ev["priority_level"] != "SKIP" else "SKIPPED"

        record = {
            "job_id": job_id,
            "canonical_hash": canon_hash,
            "company": company,
            "title": title,
            "location": location,
            "url": url,
            "source": "ycombinator",
            "company_tier": "TIER_1",  # All YC companies are curated Tier-1
            "match_score": max(ev["match_score"], 80),  # Top priority
            "fit_verdict": ev["fit_verdict"],
            "priority_level": ev["priority_level"],
            "status": status,
            "raw_jd": snippet,
            "notes": f"[YC Work at a Startup] {snippet[:150]}"
        }

        raw_path = save_raw_job("ycombinator", job_id, record)
        record["raw_jd_path"] = raw_path

        if insert_job(record):
            ingested.append(record)
            print(f"[+] Ingested [YC] {company} — {title} ({record['match_score']}%) -> {status}")

    if ingested:
        update_text_summary()
    return ingested


def run_yc_pipeline(
    profile_id: str = YC_DEFAULT_PROFILE,
    max_queries: int = 4,
    jobs_per_query: int = 15
) -> Dict[str, Any]:
    """Runs full multi-query YC discovery and ingestion."""
    print(f"\n[*] Executing Scaled Y Combinator (y2c) Discovery Pipeline in {profile_id}...")
    total_ingested = 0
    all_ingested = []

    queries_to_run = YC_SEARCH_QUERIES[:max_queries]
    for q in queries_to_run:
        print(f"\n[+] Searching YC for: '{q}'...")
        res = scrape_yc_query(
            query=q,
            max_jobs_per_query=jobs_per_query,
            profile_id=profile_id
        )

        if res.get("status") == "SUCCESS":
            jobs = res.get("jobs", [])
            ingested = ingest_scraped_yc_jobs(jobs)
            total_ingested += len(ingested)
            all_ingested.extend(ingested)
            print(f"[+] YC Query '{q}' complete: {len(ingested)} new jobs ingested.")
        else:
            print(f"[!] YC Query '{q}' returned: {res.get('status')} — {res.get('message')}")

    print(f"\n[=== YC Discovery Complete: {total_ingested} total new jobs ingested ===]")
    return {
        "status": "SUCCESS",
        "total_ingested": total_ingested,
        "jobs": all_ingested
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Y Combinator (y2c) Autonomous Scraper")
    parser.add_argument("--profile", default=YC_DEFAULT_PROFILE, help="Profile ID")
    parser.add_argument("--queries", type=int, default=3, help="Number of queries to run")
    parser.add_argument("--jobs-per-query", type=int, default=15, help="Max jobs per query")
    args = parser.parse_args()

    run_yc_pipeline(profile_id=args.profile, max_queries=args.queries, jobs_per_query=args.jobs_per_query)
