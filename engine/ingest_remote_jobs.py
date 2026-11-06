#!/usr/bin/env python3
"""
Ingests verified remote contract and freelance postings into SQLite database.
Evaluates them against JEV and priority criteria.
"""

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from engine.db import init_db, insert_job, update_text_summary
from engine.evaluator import evaluate_job_match

def run_remote_ingest():
    init_db()

    verified_jobs = [
        {
            "job_id": "outlier_4494070005",
            "company": "Outlier",
            "title": "Coding Expertise for AI Training — India [Contract] [Remote]",
            "location": "Global / Remote",
            "url": "https://app.outlier.ai/en/expert/opportunities/4494070005",
            "source": "perplexity_outlier",
            "raw_jd": "Outlier remote freelance contract for candidates in India. Train LLMs and coding agents on Python, algorithms, data structures, and code evaluation. Flexible hours, competitive weekly payouts."
        },
        {
            "job_id": "outlier_4476589005",
            "company": "Outlier",
            "title": "Coding Expertise for AI Training — English/India [Contract] [Remote]",
            "location": "Global / Remote",
            "url": "https://app.outlier.ai/opportunities/4476589005",
            "source": "perplexity_outlier",
            "raw_jd": "Remote freelance contract for software engineering and coding work training LLMs. Evaluating, classifying, and creating coding problems for AI-model training."
        },
        {
            "job_id": "outlier_4671609005",
            "company": "Outlier",
            "title": "Full Stack Software Engineer for AI Training [Contract] [Remote]",
            "location": "Global / Remote",
            "url": "https://app.outlier.ai/opportunities/4671609005",
            "source": "perplexity_outlier",
            "raw_jd": "Remote freelance contract explicitly open to India candidates. Full stack software engineering and AI evaluation on cutting edge models."
        },
        {
            "job_id": "outlier_4518903005",
            "company": "Outlier",
            "title": "Competition Coders — Remote Coding Expertise for AI Training [Contract] [Remote]",
            "location": "Global / Remote",
            "url": "https://app.outlier.ai/en/expert/opportunities/4518903005",
            "source": "perplexity_outlier",
            "raw_jd": "Remote freelance coding focused AI training project. Competitive programming, complex algorithmic problem solving, Codeforces/Leetcode style AI evaluation."
        },
        {
            "job_id": "mercor_ml_india",
            "company": "Mercor",
            "title": "Machine Learning Engineer ($70–$120/hour) [Contract] [Remote]",
            "location": "Global / Remote",
            "url": "https://work.mercor.com/jobs/list_AAABmjiUIi0G5k4QxsdNur1T/machine-learning-engineer-india",
            "source": "perplexity_mercor",
            "raw_jd": "Independent contractor network matching verified engineers to US tech clients. ML engineering, LLM post-training, prompt engineering, agentic workflows. Weekly payout $70-$120/hr via Stripe/Wise."
        },
        {
            "job_id": "mercor_ai_india",
            "company": "Mercor",
            "title": "Applied AI Engineer ($70–$120/hour) [Contract] [Remote]",
            "location": "Global / Remote",
            "url": "https://work.mercor.com/jobs/list_AAABl8xmZuOP0EACJhdHmZRp/applied-ai-engineer-india",
            "source": "perplexity_mercor",
            "raw_jd": "Applied AI Engineer talent pool for leading GenAI startups. RAG architectures, model context protocol, Python FastAPI microservices, evaluation pipelines."
        },
        {
            "job_id": "mercor_ml_expert",
            "company": "Mercor",
            "title": "Machine Learning Expert ($150–$200/hour) [Contract] [Remote]",
            "location": "Global / Remote",
            "url": "https://work.mercor.com/jobs/list_AAABoVbx1lSSTH-CB6hAt4WE/machine-learning-expert?referralCode=91f98f81-d904-4305-a7ab-6d34dfce550d",
            "source": "perplexity_mercor",
            "raw_jd": "Remote hourly contract; requires hands-on PyTorch/JAX model training, fine-tuning, RLHF, DPO, and inference optimization for frontier AI labs. Payout $150–$200/hr."
        },
        {
            "job_id": "mercor_mle_talent",
            "company": "Mercor",
            "title": "Machine Learning Engineer Talent Network ($70–$250/hour) [Contract] [Remote]",
            "location": "Global / Remote",
            "url": "https://work.mercor.com/jobs/list_AAABnJzIt-SOsdwOeF5Ebarf/machine-learning-engineer-talent-network",
            "source": "perplexity_mercor",
            "raw_jd": "Remote part-time contract; Python, PyTorch/TensorFlow, MLOps, deployment, model evaluation. Flexible 10-40 hrs/week, $70–$250/hr."
        },
        {
            "job_id": "mercor_data_expert",
            "company": "Mercor",
            "title": "Senior Data Scientist & Data Engineering Experts ($120–$180/hour) [Contract] [Remote]",
            "location": "Global / Remote",
            "url": "https://work.mercor.com/jobs/list_AAABoX3-UIdE0bwI7L9Ox6qj/senior-data-scientist-and-data-engineering-experts",
            "source": "perplexity_mercor",
            "raw_jd": "Fully remote hourly contract. Scalable distributed data architectures, Spark, Kafka, AWS Glue, Athena, high-throughput feature stores and data lakes. $120–$180/hr."
        },
        {
            "job_id": "mercor_python_swe",
            "company": "Mercor",
            "title": "Exceptional Python Software Engineers ($75–$120/hour) [Contract] [Remote]",
            "location": "Global / Remote",
            "url": "https://work.mercor.com/jobs/list_AAABmfSGNRBE2cXlGIpDIo5z/exceptional-python-swes",
            "source": "perplexity_mercor",
            "raw_jd": "Fully remote hourly contract supporting top AI research labs. Python systems programming, async architectures, concurrency, API development, test suites. $75–$120/hr."
        },
        {
            "job_id": "alignerr_ml_swe",
            "company": "Alignerr",
            "title": "Software Engineer – Machine Learning (AI Training) ($90–$120/hour) [Contract] [Remote]",
            "location": "India / Remote",
            "url": "https://www.alignerr.com/jobs/3b836352-a4d2-49ec-9ed4-7c211a9e12ac",
            "source": "perplexity_alignerr",
            "raw_jd": "Remote, India-based hourly freelance contract. Code evaluation, stress-testing LLM reasoning, building algorithmic benchmarks, evaluating synthetic data for frontier models. $90–$120/hr."
        },
        {
            "job_id": "alignerr_ai_swe",
            "company": "Alignerr",
            "title": "Software Engineer (AI Training) ($20–$100/hour) [Contract] [Remote]",
            "location": "India / Remote",
            "url": "https://www.alignerr.com/jobs/89d9b6e3-84a4-4442-8e30-2a35d40bbe62",
            "source": "perplexity_alignerr",
            "raw_jd": "Remote freelance contract open to India developers. 10–40 hrs/week. Python, C++, Java, data structures, algorithms, debugging model-generated code. $20–$100/hr."
        },
        {
            "job_id": "turing_python_swe",
            "company": "Turing",
            "title": "Senior Software Engineer – Python (LLM Evaluation & Repo Validation) [Contract] [Remote]",
            "location": "India / Remote",
            "url": "https://work.turing.com/r/HI0DUNXvgk",
            "source": "perplexity_turing",
            "raw_jd": "Contractor assignment; remote; India eligible; minimum 20 hrs/week; 3-month contract. LLM evaluation, repository code verification, test generation, and automated auditing."
        },
        {
            "job_id": "turing_mle_bench",
            "company": "Turing",
            "title": "Machine Learning Engineer (MLE Bench) [Contract] [Remote]",
            "location": "India / Remote",
            "url": "https://work.turing.com/r/plmf_1TaDU",
            "source": "perplexity_turing",
            "raw_jd": "Contractor assignment; remote; India eligible; minimum 20 hrs/week. Benchmark-driven ML evaluation, competitive coding validation, model alignment."
        },
        {
            "job_id": "wwr_aitrainers_python",
            "company": "AITrainers",
            "title": "Remote AI Trainers (Python Coding Experts) ($55–$120/hour) [Contract] [Remote]",
            "location": "Global / Remote",
            "url": "https://weworkremotely.com/remote-jobs/aitrainers-remote-ai-trainers-generalist-and-python-coding-experts",
            "source": "perplexity_wwr",
            "raw_jd": "Global remote contract. Training LLMs on complex Python coding tasks, writing reference solutions, stress-testing edge cases, automated test suites. $55–$120/hr."
        },
        {
            "job_id": "dataannotation_ml",
            "company": "DataAnnotation",
            "title": "Machine Learning Engineer & Coding Task Evaluator ($40–$150+/hour) [Contract] [Remote]",
            "location": "Global / Remote",
            "url": "https://www.dataannotation.tech/job-board/machine-learning-engineer",
            "source": "perplexity_dataannotation",
            "raw_jd": "Global remote freelance contract. Inspecting, grading, and correcting model-generated code in Python, C++, JavaScript. Verifying algorithmic efficiency and security."
        },
        {
            "job_id": "invisible_ai_python",
            "company": "Invisible Technologies",
            "title": "AI Training & Python Specialist [Contract] [Remote]",
            "location": "Global / Remote",
            "url": "https://www.invisible.co/agents",
            "source": "perplexity_invisible",
            "raw_jd": "Advanced LLM reasoning, code generation evaluation, complex systems architecture prompting, and multi-step agent debugging for leading frontier AI labs."
        }
    ]

    added = 0
    for j in verified_jobs:
        ev = evaluate_job_match(j["company"], j["title"], j["raw_jd"], j["location"])
        j["company_tier"] = ev["company_tier"]
        j["match_score"] = ev["match_score"]
        j["fit_verdict"] = ev["fit_verdict"]
        j["priority_level"] = ev["priority_level"]
        j["status"] = "EVALUATED"

        raw_jd_path = PROJECT_ROOT / "data" / "raw_jobs" / "remote_contracts" / f"{j['job_id']}.txt"
        raw_jd_path.parent.mkdir(parents=True, exist_ok=True)
        with open(raw_jd_path, "w", encoding="utf-8") as f_jd:
            f_jd.write(j["raw_jd"])
        j["raw_jd_path"] = str(raw_jd_path)

        inserted = insert_job(j)
        if inserted:
            added += 1
            print(f"[+] Ingested [{j['priority_level']}] {j['company']}: {j['title']} ({j['match_score']}%)")
        else:
            print(f"[*] Already exists: {j['company']}: {j['title']}")

    update_text_summary()
    print(f"\n[+] Ingestion complete: {added} new remote contract postings added.")

if __name__ == "__main__":
    run_remote_ingest()
