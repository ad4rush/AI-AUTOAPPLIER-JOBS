#!/usr/bin/env python3
"""
LinkedIn Jobs Autonomous Scraper & ATS Extractor Plugin.
Operates via ego-browser on Profile 2 ("COLLEGE PROFILE").
Scrapes live postings from LinkedIn, resolves exact external ATS URLs (Google Careers,
Apple Jobs, Greenhouse, Lever, Workday, etc.) using /jobs/view/externalApply/{jobId}/,
extracts full JD text, filters by seniority & location, and ingests into jobs.db.
"""

import sys
import os
import json
import re
import time
import argparse
import subprocess
from pathlib import Path
from typing import Dict, Any, List, Optional

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from engine.config import DATA_DIR
from engine.db import insert_job, generate_canonical_hash, is_job_seen, update_text_summary
from engine.evaluator import evaluate_job_match
from engine.scraper import is_title_relevant, save_raw_job, classify_company_tier

LINKEDIN_DEFAULT_PROFILE = "Profile 2"  # College Profile

def scrape_linkedin_jobs(
    max_jobs: int = 15,
    profile_id: str = LINKEDIN_DEFAULT_PROFILE,
    task_space_name: str = "linkedin_scraper"
) -> Dict[str, Any]:
    """
    Scrapes curated engineering openings from LinkedIn Jobs, resolves external ATS links,
    and returns full structured job details.
    """
    output_path = f"/tmp/linkedin_scraped_{int(time.time())}.json"

    print(f"[*] Connecting to authenticated LinkedIn in ego-browser ({profile_id})...")

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
      task = await taskSpace("{task_space_name}_" + Date.now(), {{ profileId: "{profile_id}" }});
    }}
  }}
}} else {{
  task = await taskSpace("{task_space_name}", {{ profileId: "{profile_id}" }});
}}

const page = task.page("p1");

console.log("[LinkedIn-Scraper] Navigating to LinkedIn Jobs home...");
await page.goto("https://www.linkedin.com/jobs/", {{ waitUntil: "domcontentloaded", timeout: 25000 }});
await new Promise(r => setTimeout(r, 4000));

const currentUrl = await page.url();
const pageTitle = await page.title();
console.log("[LinkedIn-Scraper] Reached: " + currentUrl + " (" + pageTitle + ")");

if (currentUrl.includes("/login") || currentUrl.includes("/checkpoint/")) {{
  console.log("[LinkedIn-Scraper] Auth required. Handing off to user...");
  await task.handOff();
  await fs.writeFile("{output_path}", JSON.stringify({{
    status: "AUTH_REQUIRED",
    message: "LinkedIn session needs login in {profile_id}."
  }}));
  process.exit(0);
}}

// Extract candidate job links from recommendation cards and preferences
const candidates = await page.evaluate((maxLimit) => {{
  const links = Array.from(document.querySelectorAll("a[href*='currentJobId='], a[href*='/jobs/view/']"));
  const seenIds = new Set();
  const results = [];

  for (let a of links) {{
    const text = (a.innerText || "").trim().replace(/\\n+/g, " | ");
    if (text.length < 5) continue;
    
    // Extract Job ID
    let jobId = "";
    const m1 = a.href.match(/currentJobId=(\\d+)/);
    const m2 = a.href.match(/\\/jobs\\/view\\/(\\d+)/);
    if (m1) jobId = m1[1];
    else if (m2) jobId = m2[1];

    if (jobId && !seenIds.has(jobId)) {{
      seenIds.add(jobId);
      
      // Parse Title, Company, Location from card text snippet
      const parts = text.split(" | ").map(s => s.trim()).filter(s => s && !s.startsWith("•") && !s.includes("works here") && !s.includes("ago"));
      const title = parts[0] ? parts[0].replace(/\\s*\\(Verified job\\)/gi, "").trim() : "Software Engineer";
      const company = parts[1] || "Tech Company";
      const location = parts[2] || "India";

      results.push({{
        jobId: jobId,
        title: title,
        company: company,
        location: location,
        cardSnippet: text
      }});
      if (results.length >= maxLimit) break;
    }}
  }}
  return results;
}}, {max_jobs});

console.log("[LinkedIn-Scraper] Extracted " + candidates.length + " job candidates. Resolving external ATS apply links...");

const enriched = [];
for (let j of candidates) {{
  try {{
    console.log("[LinkedIn-Scraper] Resolving external ATS for: " + j.company + " — " + j.title + " (ID: " + j.jobId + ")");
    
    // Navigate to externalApply endpoint to resolve real redirect
    await page.goto("https://www.linkedin.com/jobs/view/externalApply/" + j.jobId + "/", {{ waitUntil: "domcontentloaded", timeout: 20000 }});
    await new Promise(r => setTimeout(r, 3500));

    const finalUrl = await page.url();
    const finalTitle = await page.title();
    console.log("[LinkedIn-Scraper] Redirected to ATS: " + finalUrl);

    // Extract text snippet from destination page for JD evaluation
    const jdText = await page.evaluate(() => {{
      return (document.body ? document.body.innerText.slice(0, 3000) : "");
    }});

    j.externalUrl = finalUrl;
    j.pageTitle = finalTitle;
    j.rawJd = jdText || j.cardSnippet;
    enriched.push(j);
  }} catch(e) {{
    console.log("[LinkedIn-Scraper] Error resolving ATS: " + e.message);
    j.externalUrl = "https://www.linkedin.com/jobs/view/" + j.jobId + "/";
    j.rawJd = j.cardSnippet;
    enriched.push(j);
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

def ingest_scraped_linkedin_jobs(scraped_jobs: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Evaluates and ingests LinkedIn jobs into jobs.db."""
    ingested = []
    for j in scraped_jobs:
        title = j.get("title", "")
        company = j.get("company", "")
        location = j.get("location", "India")
        url = j.get("externalUrl") or f"https://www.linkedin.com/jobs/view/{j.get('jobId')}/"
        raw_jd = j.get("rawJd", title)

        # Smart location fallback for LinkedIn
        combined_text = (location + " " + raw_jd + " " + j.get("cardSnippet", "")).lower()
        if any(city in combined_text for city in ["india", "hyderabad", "bengaluru", "bangalore", "gurugram", "gurgaon", "noida", "pune", "mumbai", "delhi"]):
            location = "India"
        elif "remote" in combined_text:
            location = "Remote"

        if not is_title_relevant(title):
            print(f"[-] Dropped non-target/senior title: {company} — {title}")
            continue

        canon_hash = generate_canonical_hash(company, title, url)
        if is_job_seen(canon_hash):
            continue

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
            print(f"[+] Ingested [{ev['priority_level']}] {company} — {title} ({ev['match_score']}%) -> {status}")

    if ingested:
        update_text_summary()
    return ingested

def run_linkedin_pipeline(profile_id: str = LINKEDIN_DEFAULT_PROFILE) -> Dict[str, Any]:
    """Runs full LinkedIn discovery and ingestion."""
    print(f"\n[*] Executing LinkedIn ATS Discovery Pipeline in {profile_id}...")
    res = scrape_linkedin_jobs(max_jobs=10, profile_id=profile_id)
    if res.get("status") == "SUCCESS":
        jobs = res.get("jobs", [])
        ingested = ingest_scraped_linkedin_jobs(jobs)
        print(f"[+] Pipeline complete: {len(ingested)} new jobs ingested from LinkedIn.")
        return {"status": "SUCCESS", "total_ingested": len(ingested), "jobs": ingested}
    else:
        print(f"[!] Scraper returned: {res.get('status')} — {res.get('message')}")
        return res

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="LinkedIn Autonomous ATS Scraper")
    parser.add_argument("--profile", default=LINKEDIN_DEFAULT_PROFILE, help="Profile ID (default: Profile 2)")
    parser.add_argument("--max", type=int, default=10, help="Max jobs to scrape")
    args = parser.parse_args()

    run_linkedin_pipeline(profile_id=args.profile)
