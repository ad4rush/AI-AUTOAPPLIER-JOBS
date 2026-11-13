#!/usr/bin/env python3
"""
Autonomous Remote & Contract Job Scraper with Real ATS Destination Resolution.
Uses ego-browser on Profile 1 (Main Profile) where the candidate is authenticated.
1. Navigates to https://himalayas.app/jobs/matches to scrape personalized match cards.
2. For each relevant job, clicks "Apply now", follows the outbound redirect, and resolves
   the real underlying ATS destination URL (Greenhouse, Ashby, Rippling, micro1, Breezy, etc.).
3. Ingests the real ATS URL, rich JD, and contract metadata directly into SQLite (data/jobs.db).
4. Enables the background daemon and pipeline to auto-apply without encountering intermediate job board barriers.
"""

import re
import sys
import json
import hashlib
import subprocess
from pathlib import Path
from datetime import datetime
from typing import Dict, Any, List, Optional

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from engine.config import (
    EGO_BROWSER_MAIN_PROFILE_ID,
    RAW_JOBS_DIR,
    DATA_DIR,
    classify_company_tier
)
from engine.db import (
    init_db,
    is_job_seen,
    generate_canonical_hash,
    insert_job,
    update_text_summary
)
from engine.applier import detect_ats_type

RELEVANT_KEYWORDS = [
    "ai", "artificial intelligence", "machine learning", "ml", "prompt", "llm",
    "agent", "eval", "evaluation", "trainer", "data", "engineer", "software",
    "backend", "full stack", "fullstack", "python", "developer", "distributed",
    "platform", "cloud", "forward deployed", "solutions"
]

EXCLUDED_KEYWORDS = [
    "director", "vp ", "vice president", "head of", "recruiter", "sales",
    "account executive", "marketing", "legal", "counsel", "product manager",
    "scrum master", "human resources", "talent acquisition"
]

def is_title_relevant(title: str) -> bool:
    t_lower = (title or "").lower()
    if any(ex in t_lower for ex in EXCLUDED_KEYWORDS):
        return False
    return any(rel in t_lower for rel in RELEVANT_KEYWORDS)

def save_raw_jd(company: str, job_id: str, data: Dict[str, Any]) -> str:
    safe_company = re.sub(r"[^a-zA-Z0-9_-]", "_", company.strip().lower())
    company_dir = RAW_JOBS_DIR / safe_company
    company_dir.mkdir(parents=True, exist_ok=True)
    file_path = company_dir / f"{job_id}.json"
    file_path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    return str(file_path)

def scrape_and_resolve_himalayas_matches(
    pages: int = 1,
    max_resolve: int = 8,
    task_space_name: str = "remote_sourcing_worker"
) -> List[Dict[str, Any]]:
    """
    Scrapes Himalayas matched jobs and resolves their outbound apply links
    to the real underlying employer ATS destination URLs.
    """
    init_db()
    print(f"\n[*] Launching ego-browser Remote Scraper on Profile 1 ({pages} pages)...")

    # Step 1: Extract match cards via ego-browser
    js_extract_cards = f"""
(async () => {{
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
        task = await taskSpace("{task_space_name}_runner", {{ profileId: "{EGO_BROWSER_MAIN_PROFILE_ID}" }});
      }}
    }}
  }} else {{
    task = await taskSpace("{task_space_name}", {{ profileId: "{EGO_BROWSER_MAIN_PROFILE_ID}" }});
  }}

  const page = task.page("p1");
  const allCards = [];

  for (let p = 1; p <= {pages}; p++) {{
    const url = `https://himalayas.app/jobs/matches?page=${{p}}`;
    console.log(`[Himalayas] Navigating to page ${{p}}...`);
    try {{
      await page.goto(url, {{ waitUntil: "domcontentloaded", timeout: 35000 }});
      await page.waitForTimeout(3000);

      const cards = await page.evaluate(() => {{
        const seen = new Set();
        const list = [];
        for (const a of Array.from(document.querySelectorAll("a[href*='/companies/'][href*='/jobs/']"))) {{
          const href = a.href;
          const linkText = (a.innerText || "").trim();
          if (linkText === "View job" || !linkText) continue;
          if (seen.has(href)) continue;
          seen.add(href);

          const card = a.closest("article, div.border-b, div[class*='flex-col'], div[class*='rounded']") || a.parentElement;
          const fullText = card ? card.innerText : "";
          const isApplied = fullText.includes("Applied");

          // Extract company
          const compEl = card ? card.querySelector("a[href*='/companies/']:not([href*='/jobs/'])") : null;
          const company = compEl ? compEl.innerText.trim().split("\\n")[0] : "";

          list.push({{
            company: company || "Remote Employer",
            title: linkText,
            url: href,
            applied: isApplied,
            cardText: (fullText || "").slice(0, 500).replace(/\\s+/g, " ")
          }});
        }}
        return list;
      }});
      allCards.push(...cards);
    }} catch(e) {{
      console.log(`[Himalayas] Error on page ${{p}}: ` + e.message);
    }}
  }}

  console.log("===HIMALAYAS_CARDS===");
  console.log(JSON.stringify(allCards));
  console.log("===END_HIMALAYAS_CARDS===");
}})();
"""

    cards_script = DATA_DIR / "company_apply_procedures" / "_extract_cards.js"
    cards_script.write_text(js_extract_cards, encoding="utf-8")

    proc = subprocess.run(["ego-browser", "nodejs"], stdin=open(cards_script, "r"), capture_output=True, text=True, timeout=90)
    combined = proc.stdout + "\n" + proc.stderr
    
    cards = []
    if "===HIMALAYAS_CARDS===" in combined:
        raw_json = combined.split("===HIMALAYAS_CARDS===")[1].split("===END_HIMALAYAS_CARDS===")[0].strip()
        try:
            cards = json.loads(raw_json)
        except Exception:
            pass

    print(f"[+] Sourced {len(cards)} matching cards from Himalayas.")

    # Filter for relevant candidates
    candidates_to_resolve = []
    for c in cards:
        if c.get("applied"):
            continue
        title = c.get("title", "")
        co = c.get("company", "")
        himalayas_url = c.get("url", "")
        card_text = c.get("cardText", "")

        if not is_title_relevant(title):
            continue

        canon_hash = generate_canonical_hash(co, title, himalayas_url)
        if is_job_seen(canon_hash):
            continue

        candidates_to_resolve.append(c)

    print(f"[*] Found {len(candidates_to_resolve)} fresh candidate roles to resolve ATS destinations for.")
    candidates_to_resolve = candidates_to_resolve[:max_resolve]

    if not candidates_to_resolve:
        return []

    # Step 2: Resolve real ATS destinations in ego-browser
    js_resolve = f"""
(async () => {{
  const spaces = await listTaskSpaces();
  let existing = spaces.find(s => s.name === "{task_space_name}");
  const task = await taskSpace(existing ? existing.id : "{task_space_name}");
  const page = task.page("p1");

  const candidates = {json.dumps(candidates_to_resolve)};
  const resolved = [];

  for (const c of candidates) {{
    try {{
      console.log(`[Resolver] Navigating to: ${{c.url}}`);
      await page.goto(c.url, {{ waitUntil: "domcontentloaded", timeout: 35000 }});
      await page.waitForTimeout(2000);

      // Extract full description text from Himalayas posting page
      const details = await page.evaluate(() => {{
        const h1 = document.querySelector("h1") ? document.querySelector("h1").innerText.trim() : "";
        const body = (document.body.innerText || "").slice(0, 4000).replace(/\\s+/g, " ");
        
        // Find Apply button
        const btn = Array.from(document.querySelectorAll("button, a")).find(b => (b.innerText || "").toLowerCase().includes("apply now"));
        if (btn) btn.click();
        
        return {{ h1, body }};
      }});

      await page.waitForTimeout(1500);

      // Extract modal link
      const applyHref = await page.evaluate(() => {{
        const modalA = document.querySelector("a[href*='/apply/']");
        if (modalA) return modalA.href;
        const directA = Array.from(document.querySelectorAll("a")).find(a => (a.innerText || "").toLowerCase().includes("apply now"));
        return directA ? directA.href : null;
      }});

      if (applyHref) {{
        console.log(`[Resolver] Following outbound apply: ${{applyHref}}`);
        await page.goto(applyHref, {{ waitUntil: "domcontentloaded", timeout: 35000 }});
        await page.waitForTimeout(3000);

        const destUrl = await page.url();
        const destTitle = await page.title();
        console.log(`[Resolver] Resolved destination: ${{destUrl}} (${{destTitle}})`);

        resolved.push({{
          ...c,
          resolved_title: details.h1 || c.title,
          resolved_url: destUrl,
          resolved_title_page: destTitle,
          full_jd_text: details.body
        }});
      }} else {{
        resolved.push({{
          ...c,
          resolved_title: details.h1 || c.title,
          resolved_url: c.url,
          full_jd_text: details.body
        }});
      }}
    }} catch(e) {{
      console.log(`[Resolver] Error resolving ${{c.url}}: ` + e.message);
    }}
  }}

  console.log("===RESOLVED_ATS===");
  console.log(JSON.stringify(resolved));
  console.log("===END_RESOLVED_ATS===");
}})();
"""

    resolve_script = DATA_DIR / "company_apply_procedures" / "_resolve_ats.js"
    resolve_script.write_text(js_resolve, encoding="utf-8")

    proc2 = subprocess.run(["ego-browser", "nodejs"], stdin=open(resolve_script, "r"), capture_output=True, text=True, timeout=240)
    comb2 = proc2.stdout + "\n" + proc2.stderr

    resolved_list = []
    if "===RESOLVED_ATS===" in comb2:
        raw_res = comb2.split("===RESOLVED_ATS===")[1].split("===END_RESOLVED_ATS===")[0].strip()
        try:
            resolved_list = json.loads(raw_res)
        except Exception:
            pass

    # Step 3: Ingest resolved jobs into SQLite database
    ingested_jobs = []
    for item in resolved_list:
        final_url = item.get("resolved_url") or item.get("url")
        co = item.get("company", "Remote Tech")
        title = item.get("resolved_title") or item.get("title")
        full_jd = item.get("full_jd_text") or item.get("cardText") or ""
        card_text = item.get("cardText", "")

        is_contract = any(k in (title + " " + card_text).lower() for k in ["contract", "contractor", "freelance", "hourly", "$/hr", "/hour"])
        emp_type = "Contract" if is_contract else "Full Time"

        ats = detect_ats_type(final_url)
        ats_prefix = ats if ats != "generic" else "him"

        job_hash = hashlib.sha256(f"{co}:{title}:{final_url}".encode()).hexdigest()[:8]
        job_id = f"{ats_prefix}_{re.sub(r'[^a-zA-Z0-9]', '', co.lower())[:8]}_{job_hash}"

        canonical_hash = generate_canonical_hash(co, title, final_url)
        if is_job_seen(canonical_hash):
            continue

        raw_record = {
            "job_id": job_id,
            "canonical_hash": canonical_hash,
            "company": co,
            "title": title + (" [Contract]" if is_contract else "") + " [Remote]",
            "location": "Global / Remote",
            "url": final_url,
            "source": "himalayas_matches",
            "company_tier": classify_company_tier(co),
            "raw_jd": full_jd,
            "metadata": {
                "employmentType": emp_type,
                "isContract": is_contract,
                "isRemote": True,
                "ats": ats,
                "himalayasSourceUrl": item.get("url")
            }
        }

        raw_path = save_raw_jd(co, job_id, raw_record)
        raw_record["raw_jd_path"] = raw_path

        # Insert directly into SQLite database
        success = insert_job(raw_record)
        if success:
            print(f"[+] Ingested resolved ATS job: [{co}] {title} -> {final_url} (ATS: {ats})")
            ingested_jobs.append(raw_record)

    update_text_summary()
    print(f"\n[+] Remote Scraper complete. Ingested {len(ingested_jobs)} fresh resolved ATS jobs into database.\n")
    return ingested_jobs

def run_remote_sourcing_pipeline():
    """Entry point callable by daemon or pipeline."""
    return scrape_and_resolve_himalayas_matches(pages=2, max_resolve=8)

if __name__ == "__main__":
    jobs = run_remote_sourcing_pipeline()
    print(f"Total newly ingested: {len(jobs)}")
