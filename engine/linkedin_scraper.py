#!/usr/bin/env python3
"""
LinkedIn Jobs Autonomous Scraper & ATS Extractor Engine.
Operates deterministically via ego-browser on Profile 2 ("COLLEGE PROFILE").

Features:
- Deterministic extraction using stable LinkedIn DOM selectors (data-occludable-job-id, job-card-container).
- Multi-query targeted search across AI, ML, Data, Backend, Distributed Systems.
- Dual-tab architecture: p1 holds search results state while p2 resolves external ATS redirects.
- Never loses search page position or triggers feed reloads.
- Resolves exact external ATS apply URLs (Greenhouse, Lever, Ashby, Workday, etc.).
- Evaluates fit against candidate criteria and ingests directly into data/jobs.db.
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
from typing import Dict, Any, List, Optional

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from engine.config import DATA_DIR
from engine.db import insert_job, generate_canonical_hash, is_job_seen, update_text_summary
from engine.evaluator import evaluate_job_match
from engine.scraper import is_title_relevant, save_raw_job

LINKEDIN_DEFAULT_PROFILE = "Profile 2"  # College Profile

SEARCH_TARGETS = [
    {"keywords": "AI Engineer", "location": "India"},
    {"keywords": "Data Engineer", "location": "India"},
    {"keywords": "Backend Engineer", "location": "India"},
    {"keywords": "Machine Learning Engineer", "location": "India"},
    {"keywords": "Software Engineer", "location": "India"},
    {"keywords": "AI Engineer", "location": "Remote"},
    {"keywords": "Distributed Systems Engineer", "location": "Remote"},
    {"keywords": "Python Developer", "location": "India"},
]


def scrape_linkedin_search_query(
    keywords: str = "AI Engineer",
    location: str = "India",
    max_jobs_per_query: int = 15,
    profile_id: str = LINKEDIN_DEFAULT_PROFILE,
    task_space_name: str = "linkedin_scraper"
) -> Dict[str, Any]:
    """
    Executes a deterministic targeted search query on LinkedIn.
    Uses p1 for search navigation and p2 for external ATS URL resolution.
    """
    output_path = f"/tmp/linkedin_query_{int(time.time() * 1000)}.json"
    enc_keywords = urllib.parse.quote(keywords)
    enc_location = urllib.parse.quote(location)
    search_url = f"https://www.linkedin.com/jobs/search/?keywords={enc_keywords}&location={enc_location}&sortBy=DD"

    node_script = f"""
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
      task = await taskSpace("{task_space_name}", {{ profileId: "{profile_id}" }});
    }}
  }}
}} else {{
  task = await taskSpace("{task_space_name}", {{ profileId: "{profile_id}" }});
}}

const p1 = task.page("p1");

console.log("[LinkedIn-Scraper] Navigating to: {search_url}");
await p1.goto("{search_url}", {{ waitUntil: "domcontentloaded", timeout: 25000 }});
await new Promise(r => setTimeout(r, 4000));

const currentUrl = await p1.url();
if (currentUrl.includes("/login") || currentUrl.includes("/checkpoint/")) {{
  console.log("[LinkedIn-Scraper] Auth required. Handing off to user...");
  await task.handOff();
  await fs.writeFile("{output_path}", JSON.stringify({{
    status: "AUTH_REQUIRED",
    message: "LinkedIn session needs login in {profile_id}."
  }}));
  process.exit(0);
}}

// Scroll container slightly to load initial items
await p1.evaluate(() => {{
  const list = document.querySelector(".scaffold-layout__list, .jobs-search-results-list") || window;
  list.scrollBy(0, 500);
}});
await new Promise(r => setTimeout(r, 1500));

// 1. Extract job cards deterministically
const cardMetadata = await p1.evaluate((maxLimit) => {{
  const results = [];
  const seenJobIds = new Set();

  // Primary: occludable items and card containers
  const items = Array.from(document.querySelectorAll(
    "li[data-occludable-job-id], .job-card-container, [data-job-id], li.jobs-search-results__list-item"
  ));

  for (const item of items) {{
    let jobId = item.getAttribute("data-occludable-job-id") || item.getAttribute("data-job-id");
    
    // Fallback: extract jobId from link
    const titleLink = item.querySelector("a[href*='/jobs/view/'], a.job-card-list__title--link, a.job-card-container__link");
    if (!jobId && titleLink) {{
      const m = titleLink.href.match(/\\/jobs\\/view\\/(\\d+)/);
      if (m) jobId = m[1];
    }}

    if (!jobId || seenJobIds.has(jobId)) continue;
    seenJobIds.add(jobId);

    const titleEl = item.querySelector(".job-card-list__title, strong, a.job-card-container__link");
    const rawTitle = titleEl ? titleEl.innerText.trim() : "";
    const cleanTitle = rawTitle.replace(/^(Selected,\\s*|Verified job|\\s*\\(Verified job\\))/gi, "").replace(/[\\r\\n]+/g, " ").trim();
    if (!cleanTitle || cleanTitle.length < 3) continue;

    const companyEl = item.querySelector(".job-card-container__primary-description, .artdeco-entity-lockup__subtitle, a[href*='/company/']");
    const company = companyEl ? companyEl.innerText.trim() : "Tech Company";

    const locEl = item.querySelector(".job-card-container__metadata-item, .artdeco-entity-lockup__caption");
    const location = locEl ? locEl.innerText.trim() : "India";

    results.push({{
      jobId,
      title: cleanTitle,
      company: company,
      location: location,
      url: `https://www.linkedin.com/jobs/view/${{jobId}}/`,
      snippet: `${{company}} | ${{cleanTitle}} | ${{location}}`
    }});

    if (results.length >= maxLimit) break;
  }}

  // Secondary fallback: query all job view links if items were empty
  if (results.length === 0) {{
    const allLinks = Array.from(document.querySelectorAll("a[href*='/jobs/view/']"));
    for (const a of allLinks) {{
      const m = a.href.match(/\\/jobs\\/view\\/(\\d+)/);
      if (!m || seenJobIds.has(m[1])) continue;
      const jId = m[1];
      seenJobIds.add(jId);

      const t = a.innerText.trim().replace(/[\\r\\n]+/g, " ");
      if (t.length > 3) {{
        results.push({{
          jobId: jId,
          title: t,
          company: "Tech Enterprise",
          location: "India",
          url: `https://www.linkedin.com/jobs/view/${{jId}}/`,
          snippet: t
        }});
      }}
      if (results.length >= maxLimit) break;
    }}
  }}

  return results;
}}, {max_jobs_per_query});

console.log("[LinkedIn-Scraper] Discovered " + cardMetadata.length + " deterministic candidates for '{keywords}'.");

// 2. Resolve external ATS URLs using tab p2 without disturbing p1
let p2;
try {{
  p2 = task.page("p2");
}} catch(e) {{
  p2 = task.newPage("p2");
}}

const enriched = [];
for (let item of cardMetadata) {{
  try {{
    if (!item.jobId) {{
      enriched.push(item);
      continue;
    }}

    console.log(`[LinkedIn-Scraper] Resolving ATS for ${{item.company}} - ${{item.title}} (ID: ${{item.jobId}})...`);
    const externalUrl = `https://www.linkedin.com/jobs/view/externalApply/${{item.jobId}}/`;

    try {{
      await p2.goto(externalUrl, {{ waitUntil: "domcontentloaded", timeout: 12000 }});
      await new Promise(r => setTimeout(r, 2500));
      const finalUrl = await p2.url();
      if (finalUrl && !finalUrl.includes("/login") && !finalUrl.includes("linkedin.com/jobs/view/externalApply")) {{
        item.externalUrl = finalUrl;
        console.log(`[LinkedIn-Scraper] -> Resolved ATS: ${{finalUrl.slice(0, 70)}}...`);
      }} else {{
        item.externalUrl = item.url;
      }}
    }} catch(redirErr) {{
      item.externalUrl = item.url;
    }}

    enriched.push(item);
  }} catch(err) {{
    item.externalUrl = item.url;
    enriched.push(item);
  }}
}}

await task.finish({{ keep: [] }});

await fs.writeFile("{output_path}", JSON.stringify({{
  status: "SUCCESS",
  count: enriched.length,
  jobs: enriched
}}));
"""

    try:
        proc = subprocess.run(
            ["ego-browser", "nodejs"],
            input=node_script,
            text=True,
            capture_output=True,
            timeout=180
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


def ingest_scraped_linkedin_jobs(scraped_jobs: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Evaluates and ingests LinkedIn jobs into jobs.db."""
    ingested = []
    for j in scraped_jobs:
        title = j.get("title", "")
        company = j.get("company", "")
        location = j.get("location", "India")
        url = j.get("externalUrl") or j.get("url") or f"https://www.linkedin.com/jobs/view/{j.get('jobId')}/"
        raw_jd = j.get("rawJd", j.get("snippet", title))

        if not is_title_relevant(title):
            print(f"[-] Dropped non-target/senior title: {company} — {title}")
            continue

        canon_hash = generate_canonical_hash(company, title, url)
        if is_job_seen(canon_hash):
            continue

        # Smart location fallback for LinkedIn
        combined_text = (location + " " + raw_jd + " " + j.get("snippet", "")).lower()
        if any(city in combined_text for city in ["india", "hyderabad", "bengaluru", "bangalore", "gurugram", "gurgaon", "noida", "pune", "mumbai", "delhi"]):
            location = "India"
        elif "remote" in combined_text:
            location = "Remote"

        ev = evaluate_job_match(company, title, raw_jd, location)
        status = "EVALUATED" if ev["priority_level"] != "SKIP" else "SKIPPED"

        job_id = f"li_{re.sub(r'[^a-zA-Z0-9]', '', company.lower())[:8]}_{canon_hash[:8]}"
        record = {
            "job_id": job_id,
            "canonical_hash": canon_hash,
            "company": company,
            "title": title,
            "location": location,
            "url": url,
            "source": "linkedin_ats",
            "company_tier": ev["company_tier"],
            "match_score": ev["match_score"],
            "fit_verdict": ev["fit_verdict"],
            "priority_level": ev["priority_level"],
            "status": status,
            "raw_jd": raw_jd,
            "notes": f"[{ev['experience_status']}] Matched: {', '.join(ev['matched_skills'][:5])}"
        }

        raw_path = save_raw_job("linkedin", job_id, record)
        record["raw_jd_path"] = raw_path

        if insert_job(record):
            ingested.append(record)
            print(f"[+] Ingested [{ev['priority_level']}] {company} — {title} ({ev['match_score']}%) -> {status} (ATS: {url[:50]}...)")

    if ingested:
        update_text_summary()
    return ingested


def run_linkedin_pipeline(
    profile_id: str = LINKEDIN_DEFAULT_PROFILE,
    max_queries: int = 4,
    jobs_per_query: int = 10
) -> Dict[str, Any]:
    """Runs full multi-query LinkedIn discovery and ingestion."""
    print(f"\n[*] Executing Deterministic LinkedIn ATS Discovery Pipeline in {profile_id}...")
    total_ingested = 0
    all_ingested = []

    queries_to_run = SEARCH_TARGETS[:max_queries]
    for q in queries_to_run:
        kw = q["keywords"]
        loc = q["location"]
        print(f"\n[+] Searching LinkedIn for: '{kw}' in '{loc}'...")
        res = scrape_linkedin_search_query(
            keywords=kw,
            location=loc,
            max_jobs_per_query=jobs_per_query,
            profile_id=profile_id
        )

        if res.get("status") == "SUCCESS":
            jobs = res.get("jobs", [])
            ingested = ingest_scraped_linkedin_jobs(jobs)
            total_ingested += len(ingested)
            all_ingested.extend(ingested)
            print(f"[+] Query '{kw}' ({loc}) complete: {len(ingested)} new jobs ingested.")
        else:
            print(f"[!] Query '{kw}' returned: {res.get('status')} — {res.get('message')}")

    print(f"\n[=== LinkedIn Discovery Complete: {total_ingested} total new jobs ingested ===]")
    return {
        "status": "SUCCESS",
        "total_ingested": total_ingested,
        "jobs": all_ingested
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="LinkedIn Deterministic Multi-Query ATS Scraper")
    parser.add_argument("--profile", default=LINKEDIN_DEFAULT_PROFILE, help="Profile ID (default: Profile 2)")
    parser.add_argument("--queries", type=int, default=2, help="Number of queries to run")
    parser.add_argument("--jobs-per-query", type=int, default=10, help="Max jobs per query")
    args = parser.parse_args()

    run_linkedin_pipeline(profile_id=args.profile, max_queries=args.queries, jobs_per_query=args.jobs_per_query)
