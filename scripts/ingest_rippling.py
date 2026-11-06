#!/usr/bin/env python3
import sys
from pathlib import Path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from engine.db import insert_job, generate_canonical_hash, update_text_summary
from engine.evaluator import evaluate_job_match

rippling_jobs = [
    {
        "company": "Rippling",
        "title": "Software Engineer I - Data Infrastructure",
        "location": "Bangalore, India",
        "url": "https://ats.rippling.com/rippling/jobs/28e76743-13cf-4e30-94f2-bbaa021a2d9b",
        "source": "perplexity_rippling",
        "raw_jd": "SDE-1 Data Infrastructure role. Build scalable streaming and batch data architectures using Apache Spark, Kafka, AWS, lakehouse storage (Parquet/Hudi), and distributed systems in Python and Go. 0 to 2 years experience."
    },
    {
        "company": "Rippling",
        "title": "Software Engineer-1",
        "location": "Bangalore, India",
        "url": "https://ats.rippling.com/rippling/jobs/277b7caf-3092-44a7-9e8c-45769e5a3ea5",
        "source": "perplexity_rippling",
        "raw_jd": "SDE-1 / L5 Platform Engineering. Designing microservices, backend architectures, Python, Docker, Kubernetes, distributed systems. 0 to 2 years experience."
    },
    {
        "company": "Rippling",
        "title": "Software Engineer I - FullStack",
        "location": "Bangalore, India",
        "url": "https://ats.rippling.com/rippling/jobs/acf82f7d-5595-47c4-8e08-45c9d9a93529",
        "source": "perplexity_rippling",
        "raw_jd": "Software Engineer I FullStack. Build high-availability customer-facing products, Python, Django/FastAPI, React, PostgreSQL. 1+ years experience."
    },
    {
        "company": "Rippling",
        "title": "Software Engineer I",
        "location": "Bangalore, India",
        "url": "https://ats.rippling.com/rippling/jobs/472ecc5e-9610-477b-bbb9-8b075c8f5a67",
        "source": "perplexity_rippling",
        "raw_jd": "Software Engineer I. 1-2 years experience at top-tier product companies. Python, Go, Java, or C++, algorithms, data structures, backend platform scale."
    }
]

added = 0
for j in rippling_jobs:
    ch = generate_canonical_hash(j["company"], j["title"], j["url"])
    ev = evaluate_job_match(j["company"], j["title"], j["raw_jd"], j["location"])
    skills_str = ", ".join(ev["matched_skills"][:5])
    exp_status = ev["experience_status"]
    record = {
        "job_id": f"rippling_{ch[:8]}",
        "canonical_hash": ch,
        "company": j["company"],
        "title": j["title"],
        "location": j["location"],
        "url": j["url"],
        "source": j["source"],
        "company_tier": ev["company_tier"],
        "match_score": ev["match_score"],
        "fit_verdict": ev["fit_verdict"],
        "priority_level": ev["priority_level"],
        "status": "EVALUATED",
        "raw_jd": j["raw_jd"],
        "notes": f"[{exp_status}] Matched: {skills_str}"
    }
    if insert_job(record):
        added += 1
        print(f"[+] Ingested [{ev['priority_level']}] {j['company']} — {j['title']} ({ev['match_score']}%)")

update_text_summary()
print(f"[+] Total new Rippling jobs ingested: {added}")
