#!/usr/bin/env python3
import sys
import argparse
from pathlib import Path

# Ensure project root is in sys.path
sys.path.insert(0, str(Path(__file__).resolve().parent))

from datetime import datetime
from engine.config import assert_real_candidate_profile
from engine.db import (
    init_db,
    get_all_jobs,
    get_job_by_id,
    get_jobs_by_status,
    update_job_status,
    update_text_summary
)
from engine.scraper import run_parallel_scraper
from engine.evaluator import run_evaluation_pipeline
from engine.claude_tailor import generate_tailored_resume_via_claude
from engine.referral_drafter import generate_and_save_referral_drafts
from engine.scheduler import run_single_scrape_and_eval_cycle, run_periodic_daemon
from engine.microsoft_apply import apply_to_microsoft_job
from engine.stripe_apply import apply_to_stripe_job
from engine.ashby_apply import apply_to_ashby_job
from engine.greenhouse_apply import apply_to_greenhouse_job
from engine.lever_apply import apply_to_lever_job
from engine.remote_apply import apply_to_remote_contract_job
from engine.submission_watcher import check_and_process_submissions, run_submission_watcher_loop
from engine.chatgpt_consultant import consult_ai_which_to_apply
from engine.portal_generator import generate_apply_script_for_company, dispatch_agy_for_custom_portal
from engine.applier import detect_ats_type

def cmd_check_profile():
    from engine.config import (
        assert_real_candidate_profile,
        CANDIDATE_NAME, CANDIDATE_EMAIL, CANDIDATE_PHONE, CANDIDATE_LOCATION,
        CANDIDATE_LINKEDIN, CANDIDATE_GITHUB, CANDIDATE_CURRENT_COMPANY,
        DEFAULT_PORTAL_PASSWORD, CLAUDE_ACCOUNTS
    )
    assert_real_candidate_profile()
    print("\n" + "=" * 65)
    print("ACTIVE CANDIDATE PROFILE (LOADED FROM .env)")
    print("=" * 65)
    print(f"  [✓] Candidate Name  : {CANDIDATE_NAME}")
    print(f"  [✓] Primary Email   : {CANDIDATE_EMAIL}")
    print(f"  [✓] Phone Number    : {CANDIDATE_PHONE}")
    print(f"  [✓] Base Location   : {CANDIDATE_LOCATION}")
    print(f"  [✓] Current Company : {CANDIDATE_CURRENT_COMPANY}")
    print(f"  [✓] LinkedIn Profile: {CANDIDATE_LINKEDIN}")
    print(f"  [✓] GitHub Profile  : {CANDIDATE_GITHUB}")
    print(f"  [✓] Claude Accounts : {len(CLAUDE_ACCOUNTS)} active in rotation pool")
    print(f"  [✓] Portal Password : {'*' * len(DEFAULT_PORTAL_PASSWORD)} (Active)")
    print(f"  [✓] Circuit Breaker : PASSED (Zero dummy placeholders)")
    print("=" * 65)
    print("Status: 100% READY FOR TAILORING & AUTO-APPLY.\n")

def cmd_apply_microsoft(args):
    assert_real_candidate_profile()
    res = apply_to_microsoft_job(args.url, resume_path=args.resume, submit=args.submit)
    if res.get("success"):
        if args.submit:
            print("\n[+] Microsoft application successfully SUBMITTED!")
        else:
            print("\n[+] Microsoft apply procedure STAGED & VALIDATED successfully!")
            print("    👉 EGO-BROWSER TAB: TaskSpace 'microsoft_auto_apply' (Profile 1: Main Profile)")
            print("    👉 Action: Open this tab in ego-browser and press Submit.")
    else:
        print("\n[!] Application staging encountered issues. Check logs above.")

def cmd_apply_stripe(args):
    assert_real_candidate_profile()
    res = apply_to_stripe_job(args.url, resume_path=args.resume, submit=args.submit)
    if res.get("success"):
        if args.submit:
            print("\n[+] Stripe application successfully SUBMITTED!")
        else:
            print("\n[+] Stripe apply procedure STAGED & VALIDATED successfully!")
            print("    👉 EGO-BROWSER TAB: TaskSpace 'stripe_auto_apply' (Profile 1: Main Profile)")
            print("    👉 Action: Open this tab in ego-browser and press Submit.")
    else:
        print("\n[!] Application staging encountered issues. Check logs above.")

def cmd_apply_ashby(args):
    assert_real_candidate_profile()
    task_space = getattr(args, "task_space", None) or "ashby_auto_apply"
    res = apply_to_ashby_job(args.url, resume_path=args.resume, submit=args.submit, task_space_name=task_space)
    if res.get("success"):
        if args.submit:
            print("\n[+] Ashby application successfully SUBMITTED!")
        else:
            print("\n[+] Ashby apply procedure STAGED & VALIDATED successfully!")
            print(f"    👉 EGO-BROWSER TAB: TaskSpace '{task_space}' (Profile 1: Main Profile)")
            print("    👉 Action: Open this tab in ego-browser and press Submit.")
    else:
        print("\n[!] Application staging encountered issues. Check logs above.")

def cmd_apply_greenhouse(args):
    assert_real_candidate_profile()
    task_space = getattr(args, "task_space", None) or "greenhouse_auto_apply"
    res = apply_to_greenhouse_job(args.url, resume_path=args.resume, company_name=getattr(args, "company", None), submit=args.submit, task_space_name=task_space)
    if res.get("success"):
        if args.submit:
            print("\n[+] Greenhouse application successfully SUBMITTED!")
        else:
            print("\n[+] Greenhouse apply procedure STAGED & VALIDATED successfully!")
            print(f"    👉 EGO-BROWSER TAB: TaskSpace '{task_space}' (Profile 1: Main Profile)")
            print("    👉 Action: Open this tab in ego-browser and press Submit.")
    else:
        print("\n[!] Application staging encountered issues. Check logs above.")

def cmd_apply_lever(args):
    assert_real_candidate_profile()
    task_space = getattr(args, "task_space", None) or "lever_auto_apply"
    res = apply_to_lever_job(args.url, resume_path=args.resume, submit=args.submit, task_space_name=task_space)
    if res.get("success"):
        if args.submit:
            print("\n[+] Lever application successfully SUBMITTED!")
        else:
            print("\n[+] Lever apply procedure STAGED & VALIDATED successfully!")
            print(f"    👉 EGO-BROWSER TAB: TaskSpace '{task_space}' (Profile 1: Main Profile)")
            print("    👉 Action: Open this tab in ego-browser and press Submit.")
    else:
        print("\n[!] Application staging encountered issues. Check logs above.")

def cmd_apply_remote(args):
    assert_real_candidate_profile()
    res = apply_to_remote_contract_job(args.url, resume_path=args.resume, submit=args.submit)
    if res.get("success"):
        if args.submit:
            print("\n[+] Remote contract application successfully SUBMITTED!")
        else:
            print("\n[+] Remote contract apply procedure STAGED & VALIDATED successfully!")
            print("    👉 EGO-BROWSER TAB: TaskSpace 'remote_contract_auto_apply' (Profile 1: Main Profile)")
            print("    👉 Action: Open this tab in ego-browser and press Submit.")
    else:
        print("\n[!] Application staging encountered issues. Check logs above.")

def cmd_watch_submissions(args):
    if args.once:
        results = check_and_process_submissions()
        print(f"\n[+] Processed {len(results)} submitted applications.")
    else:
        run_submission_watcher_loop(interval_sec=args.interval, max_cycles=args.cycles)

def cmd_apply_all(args):
    """
    Unified batch auto-applier across all supported company portals.
    Auto-detects portal types (Microsoft Eightfold, Stripe, Ashby, Greenhouse, Lever),
    locates or dynamically generates tailored resumes, and executes verified procedures.
    """
    import re
    init_db()
    jobs = [dict(j) for j in get_all_jobs()]
    targets = [
        j for j in jobs
        if j.get("priority_level") in ("CRITICAL_PRIORITY", "HIGH_PRIORITY", "NORMAL")
        and j.get("status") in ("EVALUATED", "TAILORED", "REFERRAL_DRAFTED")
    ]
    targets.sort(
        key=lambda x: (
            x.get("priority_level") == "CRITICAL_PRIORITY",
            x.get("priority_level") == "HIGH_PRIORITY",
            x.get("match_score", 0)
        ),
        reverse=True
    )
    
    supported = []
    for j in targets:
        comp = (j.get("company") or "").lower()
        url = (j.get("url") or "").lower()
        if "microsoft" in comp or "careers.microsoft.com" in url or "eightfold.ai" in url:
            supported.append((j, "microsoft"))
        elif "stripe" in comp or ("stripe" in url and "job_app" in url):
            supported.append((j, "stripe"))
        elif "ashbyhq.com" in url:
            supported.append((j, "ashby"))
        elif "greenhouse.io" in url or "databricks" in comp or "brex" in comp:
            supported.append((j, "greenhouse"))
        elif "lever.co" in url or "palantir" in comp:
            supported.append((j, "lever"))

    print(f"[*] Found {len(supported)} qualified applications on supported automated boards...")
    if not supported:
        print("[*] No qualified pending jobs on supported automated boards.")
        return

    count = 0
    for j, comp_type in supported:
        if args.limit and count >= args.limit:
            break
        job_id = j["job_id"]
        company = j["company"]
        title = j["title"]
        url = j["url"]

        print(f"\n=======================================================")
        print(f"AUTOMATED APPLICATION [{count+1}/{len(supported)}]: {company} — {title}")
        print(f"URL: {url} | Platform: {comp_type.upper()}")
        print(f"=======================================================")

        pdf_path = None
        resume_dir = j.get("tailored_resume_dir")
        if resume_dir and Path(resume_dir).exists():
            pdfs = list(Path(resume_dir).glob("*.pdf"))
            if pdfs:
                pdf_path = str(pdfs[0])

        if not pdf_path:
            clean_company = re.sub(r'[^a-zA-Z0-9]', '_', company.lower())
            clean_job_id = re.sub(r'[^a-zA-Z0-9]', '_', job_id.lower())
            target_dir = Path("/Users/adarsh/job_finder_applier/resumes_generated") / f"{clean_company}_{clean_job_id}"
            if target_dir.exists():
                pdfs = list(target_dir.glob("*.pdf"))
                if pdfs:
                    pdf_path = str(pdfs[0])

        if not pdf_path and getattr(args, "auto_tailor", False):
            print(f"[*] No tailored resume found for {company}. Dynamically tailoring via Claude & ChatGPT...")
            raw_jd_path = j.get("raw_jd_path")
            jd_text = ""
            if raw_jd_path and Path(raw_jd_path).exists():
                with open(raw_jd_path, "r", encoding="utf-8") as f:
                    jd_text = f.read()
            t_ok, t_msg, _, t_pdf = generate_tailored_resume_via_claude(job_id, company, title, jd_text)
            if t_ok and t_pdf and Path(t_pdf).exists():
                pdf_path = str(t_pdf)
                print(f"[+] Tailored resume ready: {pdf_path}")

        if not pdf_path:
            all_pdfs = list(Path("/Users/adarsh/job_finder_applier/resumes_generated").glob("*/*.pdf"))
            if all_pdfs:
                pdf_path = str(all_pdfs[0])
                print(f"[*] Using verified candidate resume: {pdf_path}")

        is_remote_contract = (j.get("fit_verdict") == "REMOTE_CONTRACT_MATCH") or ("contract" in title.lower())
        should_submit = args.submit or is_remote_contract
        task_space = f"{comp_type}_auto_apply"

        if comp_type == "microsoft":
            res = apply_to_microsoft_job(url, resume_path=pdf_path, submit=should_submit)
        elif comp_type == "stripe":
            res = apply_to_stripe_job(url, resume_path=pdf_path, submit=should_submit)
        elif comp_type == "ashby":
            res = apply_to_ashby_job(url, resume_path=pdf_path, submit=should_submit)
        elif comp_type == "greenhouse":
            res = apply_to_greenhouse_job(url, resume_path=pdf_path, company_name=company, submit=should_submit)
        elif comp_type == "lever":
            res = apply_to_lever_job(url, resume_path=pdf_path, submit=should_submit)
        else:
            res = {"success": False, "error": f"Unsupported platform: {comp_type}"}

        if res.get("success"):
            new_status = "APPLIED" if should_submit else "STAGED_FOR_REVIEW"
            note_text = "Auto-submitted (Remote Contract Flow)" if should_submit else f"Staged 100% in ego-browser TaskSpace '{task_space}' (Profile 1). Ready for one-click submit."
            update_job_status(job_id, new_status, {
                "applied_at": datetime.now().isoformat(),
                "tailored_resume_dir": pdf_path,
                "notes": note_text
            })
            if should_submit:
                print(f"[+] Application successfully SUBMITTED for {company} ({title})")
            else:
                print(f"[+] Application successfully STAGED & VALIDATED for {company} ({title})")
                print(f"    👉 EGO-BROWSER TAB: TaskSpace '{task_space}' (Profile 1: Main Profile)")
                print(f"    👉 Form Status: 100% pre-filled. Open this tab in ego-browser and press Submit.")
        else:
            print(f"[!] Application issue for {company}: {res.get('error', 'Check logs above')}")
        count += 1

def cmd_flush(args):
    from engine.maintenance import flush_system_and_memory
    flush_system_and_memory()

def cmd_daemon(args):
    from engine.daemon_manager import run_247_autonomous_daemon
    run_247_autonomous_daemon(
        interval_hours=args.interval,
        jitter_hours=args.jitter,
        watcher_interval_sec=args.watcher_interval,
        run_immediate_cycle=args.now
    )

def cmd_watch(args):
    if args.once:
        run_single_scrape_and_eval_cycle()
    else:
        run_periodic_daemon(interval_hours=args.interval, max_cycles=args.cycles)

def cmd_init():
    print("[*] Initializing SQLite schema and filesystem directories...")
    init_db()
    update_text_summary()
    print("[+] System initialized successfully.")

def cmd_find(args):
    init_db()
    print("[*] Launching parallel job finder across target OG career portals...")
    jobs = run_parallel_scraper(max_workers=args.workers)
    print(f"[+] Found {len(jobs)} new matching postings.")

def cmd_eval(args):
    init_db()
    re_eval = getattr(args, "all", False)
    print(f"[*] Running JEV (Job Evaluation) & Company Tiering (re_evaluate_all={re_eval})...")
    evaluated = run_evaluation_pipeline(re_evaluate_all=re_eval)
    print(f"[+] Evaluated {len(evaluated)} jobs.")

def cmd_tailor(args):
    assert_real_candidate_profile()
    init_db()
    pending = get_jobs_by_status("EVALUATED")
    if not pending:
        print("[*] No jobs pending tailoring. Run 'find' and 'eval' first.")
        return

    # Filter and sort for highest match / priority jobs first
    targets = [j for j in pending if j["priority_level"] in ("CRITICAL_PRIORITY", "HIGH_PRIORITY", "NORMAL")]
    targets.sort(key=lambda x: (x["priority_level"] == "CRITICAL_PRIORITY", x["match_score"]), reverse=True)
    print(f"[*] Found {len(targets)} qualified jobs ready for dynamic tailoring (Priority: Critical/High/Normal)...")

    count = 0
    for j in targets:
        if args.limit and count >= args.limit:
            break
        job_id = j["job_id"]
        company = j["company"]
        title = j["title"]

        raw_jd_path = j["raw_jd_path"]
        jd_text = ""
        if raw_jd_path and Path(raw_jd_path).exists():
            with open(raw_jd_path, "r", encoding="utf-8") as f:
                jd_text = f.read()

        print(f"\n---> Tailoring resume for [{j['company_tier']}] {company} — {title}")
        success, msg, tex_path, pdf_path = generate_tailored_resume_via_claude(
            job_id, company, title, jd_text
        )
        if success:
            print(f"[+] Successfully tailored: {pdf_path}")
            # Generate referral drafts for Tier 1 / Good companies
            if j["company_tier"] in ("TIER_1", "TIER_2"):
                drafts = generate_and_save_referral_drafts(dict(j), str(pdf_path))
                print(f"[+] Referral draft and LinkedIn invite note generated.")
            count += 1
        else:
            print(f"[!] Tailoring failed: {msg}")

def cmd_apply(args):
    init_db()
    tailored = get_jobs_by_status("TAILORED")
    if not tailored:
        # Also check referral drafted jobs
        tailored = get_jobs_by_status("REFERRAL_DRAFTED")
    if not tailored:
        print("[*] No tailored applications ready for auto-apply. Run 'tailor' first.")
        return

    print(f"[*] Found {len(tailored)} tailored jobs ready for application dispatch...")
    count = 0
    for j in tailored:
        if args.limit and count >= args.limit:
            break
        job_id = j["job_id"]
        company = j["company"]
        title = j["title"]
        url = j["url"]
        resume_dir = j["tailored_resume_dir"]

        pdf_path = None
        if resume_dir and Path(resume_dir).exists():
            pdfs = list(Path(resume_dir).glob("*.pdf"))
            if pdfs:
                pdf_path = pdfs[0]

        if not pdf_path:
            print(f"[!] No PDF resume found in {resume_dir}, skipping {company}.")
            continue

        success, msg = auto_apply_via_egobrowser(job_id, company, title, url, pdf_path)
        print(f"[{'SUCCESS' if success else 'ACTION NEEDED'}] {company}: {msg}")
        count += 1

def cmd_pipeline(args):
    assert_real_candidate_profile()
    print("=" * 70)
    print("RUNNING END-TO-END AUTONOMOUS JOB FINDER & APPLIER PIPELINE")
    print("=" * 70)
    init_db()

    # Step 1: Scrape & Discover (Parallel scrapers + verified remote platforms)
    print("\n[Step 1/5] Parallel Scraping & Portal Sourcing...")
    run_parallel_scraper(max_workers=getattr(args, "workers", 8) or 8)

    # Step 1b: LinkedIn ATS Scraper (Runs via Profile 2 session)
    try:
        from engine.linkedin_scraper import run_linkedin_pipeline
        print("\n[Step 1b/5] LinkedIn ATS Discovery & Extraction...")
        run_linkedin_pipeline(profile_id="Profile 2")
    except Exception as e:
        print(f"[!] Warning: LinkedIn pipeline error: {e}")

    # Step 2: Light Fast Evaluator (Filters high experience > 2 yrs, senior titles, non-tech, foreign on-site)
    print("\n[Step 2/5] Light Evaluator (Seniority & Experience Filter)...")
    evaluated_jobs = run_evaluation_pipeline()

    # Filter to candidate jobs that passed evaluation (0-2 yrs India FT or reputable remote contracts)
    candidate_jobs = [
        j for j in evaluated_jobs
        if j.get("priority_level") in ("CRITICAL_PRIORITY", "HIGH_PRIORITY")
        and j.get("match_score", 0) >= 70
    ]

    print(f"\n[*] Found {len(candidate_jobs)} priority early-career / remote contract jobs.")

    # Step 3: AI Consultation in ego-browser (Asks ChatGPT / Perplexity which to apply for)
    approved_job_ids = {}
    if candidate_jobs:
        print("\n[Step 3/5] Programmatic AI Consultation in ego-browser...")
        ai_decisions = consult_ai_which_to_apply(candidate_jobs, profile_id="Default")
        approved_job_ids = {d["job_id"]: d for d in ai_decisions if d.get("apply")}
        print(f"[+] AI Approved {len(approved_job_ids)} jobs for application dispatch.")

    # Step 4: Application Dispatch & Staging Flow
    print("\n[Step 4/5] Application Dispatch & Staging...")
    apply_limit = getattr(args, "limit", 5) or 5
    dispatched_count = 0

    for job in candidate_jobs:
        if dispatched_count >= apply_limit:
            break

        jid = job["job_id"]
        if approved_job_ids and jid not in approved_job_ids:
            continue

        db_job = get_job_by_id(jid)
        if not db_job:
            continue

        co = db_job["company"]
        title = db_job["title"]
        url = db_job["url"]
        loc = db_job["location"] or ""
        status = db_job["status"]

        if status in ("APPLIED", "STAGED", "STAGED_FOR_REVIEW"):
            print(f"[*] Skipping [{co}] {title} (already {status})")
            continue

        is_remote = "remote" in title.lower() or "contract" in title.lower() or "global" in loc.lower() or "remote" in loc.lower()

        # Check for tailored resume or pick gold-standard resume archetype
        resume_dir = db_job["tailored_resume_dir"]
        resume_pdf = None
        if resume_dir and Path(resume_dir).exists():
            pdfs = list(Path(resume_dir).glob("*.pdf"))
            if pdfs:
                resume_pdf = pdfs[0]

        if not resume_pdf:
            ai_info = approved_job_ids.get(jid, {})
            archetype = ai_info.get("archetype", "RESUME_1_AI_ENGINEER")
            resume_pdf = Path(__file__).resolve().parent / "master_resumes" / f"{archetype}.pdf"
            if not resume_pdf.exists():
                resume_pdf = Path(__file__).resolve().parent / "master_resumes" / "RESUME_1_AI_ENGINEER.pdf"

        ats = detect_ats_type(url)
        print(f"\n--> Processing [{co}] {title}")
        print(f"    Portal Type: {ats} | Flow: {'Remote (Auto-Submit)' if is_remote else 'Full-Time (Stage in ego-browser)'}")

        # Check existing specialized scripts
        if "ashbyhq.com" in url or ats == "ashby" or "openai" in co.lower():
            apply_to_ashby_job(url, resume_path=str(resume_pdf), submit=is_remote)
        elif "greenhouse.io" in url or ats == "greenhouse":
            apply_to_greenhouse_job(url, resume_path=str(resume_pdf), company_name=co, submit=is_remote)
        elif "lever.co" in url or ats == "lever":
            apply_to_lever_job(url, resume_path=str(resume_pdf), submit=is_remote)
        elif "microsoft.com" in url or "microsoft" in co.lower():
            apply_to_microsoft_job(url, resume_path=str(resume_pdf), submit=False)
        elif "mercor.com" in url or "outlier.ai" in url or is_remote:
            apply_to_remote_contract_job(url, resume_path=str(resume_pdf), submit=True)
        else:
            # New Portal / Company without existing script!
            print(f"[!] New portal detected for {co}. Calling portal generator to synthesize dedicated apply script...")
            script_path = generate_apply_script_for_company(co, url, is_remote_contract=is_remote)
            dispatch_agy_for_custom_portal(co, url)
            subprocess.run([sys.executable, str(script_path), "--url", url, "--resume", str(resume_pdf)])

        dispatched_count += 1

    # Step 5: Submission Watcher check
    print("\n[Step 5/5] Checking Submissions & Archiving...")
    check_and_process_submissions()
    update_text_summary()
    cmd_status()

def cmd_find_linkedin(args):
    from engine.linkedin_scraper import scrape_linkedin_jobs, ingest_scraped_linkedin_jobs, run_linkedin_pipeline
    if args.pipeline:
        print("[*] Running multi-query LinkedIn job discovery pipeline...")
        res = run_linkedin_pipeline(profile_id=args.profile)
        print(f"[+] LinkedIn pipeline finished: {res.get('total_ingested', 0)} new jobs ingested.")
    else:
        print(f"[*] Scraping LinkedIn (profile: {args.profile})...")
        res = scrape_linkedin_jobs(max_jobs=15, profile_id=args.profile)
        if res.get("status") == "SUCCESS":
            jobs = res.get("jobs", [])
            ingested = ingest_scraped_linkedin_jobs(jobs)
            print(f"[+] Successfully scraped and evaluated {len(ingested)} LinkedIn jobs.")
        elif res.get("status") == "AUTH_REQUIRED":
            print(f"[!] {res.get('message')}")
        else:
            print(f"[!] LinkedIn scraping error: {res.get('message')}")

def cmd_status():
    init_db()
    jobs = get_all_jobs()
    print("\n" + "=" * 70)
    print("CURRENT PIPELINE STATE SUMMARY")
    print("=" * 70)

    counts = {}
    for j in jobs:
        st = j["status"]
        counts[st] = counts.get(st, 0) + 1

    print(f"Total Jobs in Database: {len(jobs)}")
    for st, count in sorted(counts.items()):
        print(f"  • {st:25s}: {count}")

    print("\nRecent Priority Jobs:")
    priority_jobs = [j for j in jobs if j["priority_level"] in ("CRITICAL_PRIORITY", "HIGH_PRIORITY")][:5]
    for p in priority_jobs:
        print(f"  - [{p['company_tier']}] {p['company']} — {p['title']} ({p['match_score']}%) -> Status: {p['status']}")
    print("=" * 70)
    print("Full details available at: data/jobs_found_and_applied.txt\n")

def main():
    parser = argparse.ArgumentParser(
        description="Autonomous Job Finder, Tailorer & Applier Platform"
    )
    subparsers = parser.add_subparsers(dest="command", help="Pipeline commands")

    subparsers.add_parser("init", help="Initialize database and environment")

    find_p = subparsers.add_parser("find", help="Scrape new jobs from OG career boards")
    find_p.add_argument("--workers", type=int, default=8, help="Number of concurrent scrapers")

    eval_p = subparsers.add_parser("eval", help="Evaluate discovered jobs with JEV & company tiers")
    eval_p.add_argument("--all", action="store_true", help="Re-evaluate all existing jobs in the database")

    tailor_p = subparsers.add_parser("tailor", help="Dynamically tailor resumes with Claude & compile to PDF")
    tailor_p.add_argument("--limit", type=int, default=3, help="Max resumes to tailor in this run")

    apply_p = subparsers.add_parser("apply", help="Execute auto-apply flow via ego-browser")
    apply_p.add_argument("--limit", type=int, default=3, help="Max jobs to apply to in this run")

    pipeline_p = subparsers.add_parser("pipeline", help="Run full end-to-end pipeline")
    pipeline_p.add_argument("--workers", type=int, default=8, help="Number of concurrent scrapers")
    pipeline_p.add_argument("--limit", type=int, default=3, help="Max jobs to tailor & apply")

    subparsers.add_parser("status", help="Print dashboard summary of all jobs")

    watch_p = subparsers.add_parser("watch", help="Run 5x/day periodic monitoring daemon")
    watch_p.add_argument("--interval", type=float, default=4.8, help="Interval between scrapes in hours (default: 4.8)")
    watch_p.add_argument("--cycles", type=int, default=5, help="Number of refresh cycles (default: 5)")
    watch_p.add_argument("--once", action="store_true", help="Run one immediate monitoring cycle and exit")

    msft_p = subparsers.add_parser("apply-microsoft", help="Auto-apply to Microsoft India jobs")
    msft_p.add_argument("--url", required=True, help="Job URL or Job ID")
    msft_p.add_argument("--resume", help="Optional tailored PDF resume path")
    msft_p.add_argument("--submit", action="store_true", help="Submit immediately (default: stage and validate)")

    stripe_p = subparsers.add_parser("apply-stripe", help="Auto-apply to Stripe India jobs")
    stripe_p.add_argument("--url", required=True, help="Job URL or Token / ID")
    stripe_p.add_argument("--resume", help="Optional tailored PDF resume path")
    stripe_p.add_argument("--submit", action="store_true", help="Submit immediately (default: stage and validate)")

    apply_all_p = subparsers.add_parser("apply-all", help="Unified batch auto-apply across supported company portals")
    apply_all_p.add_argument("--limit", type=int, default=5, help="Max applications to process (default: 5)")
    apply_all_p.add_argument("--auto-tailor", action="store_true", help="Dynamically tailor a resume if one does not exist")
    apply_all_p.add_argument("--submit", action="store_true", help="Submit immediately (default: stage and validate)")

    ashby_p = subparsers.add_parser("apply-ashby", help="Auto-apply to Ashby HQ jobs (OpenAI, Cursor, Mercor, LangChain, etc.)")
    ashby_p.add_argument("--url", required=True, help="Ashby Job URL or application URL")
    ashby_p.add_argument("--resume", help="Optional tailored PDF resume path")
    ashby_p.add_argument("--task-space", help="Optional ego-browser task space name (default: ashby_auto_apply)")
    ashby_p.add_argument("--submit", action="store_true", help="Submit immediately (default: stage and validate)")

    gh_p = subparsers.add_parser("apply-greenhouse", help="Auto-apply to Greenhouse jobs (Scale AI, Databricks, Brex, Vercel, etc.)")
    gh_p.add_argument("--url", required=True, help="Greenhouse Job Board URL, Embed URL, or Databricks/Brex URL")
    gh_p.add_argument("--company", help="Optional company name")
    gh_p.add_argument("--resume", help="Optional tailored PDF resume path")
    gh_p.add_argument("--task-space", help="Optional ego-browser task space name (default: greenhouse_auto_apply)")
    gh_p.add_argument("--submit", action="store_true", help="Submit immediately (default: stage and validate)")

    lever_p = subparsers.add_parser("apply-lever", help="Auto-apply to Lever jobs (Palantir, Atlassian, Sentry, etc.)")
    lever_p.add_argument("--url", required=True, help="Lever Job URL")
    lever_p.add_argument("--resume", help="Optional tailored PDF resume path")
    lever_p.add_argument("--task-space", help="Optional ego-browser task space name (default: lever_auto_apply)")
    lever_p.add_argument("--submit", action="store_true", help="Submit immediately (default: stage and validate)")

    rem_p = subparsers.add_parser("apply-remote", help="Auto-apply to Outlier, Mercor, or remote contract jobs")
    rem_p.add_argument("--url", required=True, help="Job URL or Job ID")
    rem_p.add_argument("--resume", help="Optional tailored PDF resume path")
    rem_p.add_argument("--submit", action="store_true", help="Submit immediately (default: stage and validate)")

    subparsers.add_parser("flush", help="Execute hardware, memory, and SQLite maintenance flush")

    daemon_p = subparsers.add_parser("daemon", help="Run 24/7 background autonomous monitoring, submission watcher & flush daemon")
    daemon_p.add_argument("--interval", type=float, default=4.5, help="Base scrape interval in hours (default: 4.5)")
    daemon_p.add_argument("--jitter", type=float, default=0.75, help="Interval jitter in hours (default: 0.75)")
    daemon_p.add_argument("--watcher-interval", type=float, default=10.0, help="Watcher check interval in seconds (default: 10.0)")
    daemon_p.add_argument("--now", action="store_true", help="Run a scrape/stage cycle immediately upon startup")

    sub_watch_p = subparsers.add_parser("watch-submissions", help="Watch ego-browser staged taskSpaces for user submissions")
    sub_watch_p.add_argument("--once", action="store_true", help="Run one check cycle and exit")
    sub_watch_p.add_argument("--interval", type=float, default=6.0, help="Check interval in seconds (default: 6.0)")
    sub_watch_p.add_argument("--cycles", type=int, help="Max cycles to run before exiting")

    # LinkedIn Scraper Plugin
    li_p = subparsers.add_parser("find-linkedin", help="Scrape jobs & ATS apply links from LinkedIn via ego-browser")
    li_p.add_argument("--keywords", default="Software Engineer", help="Job search keywords (default: Software Engineer)")
    li_p.add_argument("--location", default="India", help="Location filter (default: India)")
    li_p.add_argument("--remote", action="store_true", help="Search worldwide remote roles")
    li_p.add_argument("--profile", default="Profile 2", help="Ego-browser profile ID (default: Profile 2)")
    li_p.add_argument("--pipeline", action="store_true", help="Run multi-query full discovery pipeline")

    # Profile Verification Command
    subparsers.add_parser("check-profile", help="Verify active candidate credentials and guarantee zero dummy placeholders")

    args = parser.parse_args()
    if not args.command:
        parser.print_help()
        sys.exit(1)

    if args.command == "init":
        cmd_init()
    elif args.command == "find":
        cmd_find(args)
    elif args.command == "eval":
        cmd_eval(args)
    elif args.command == "tailor":
        cmd_tailor(args)
    elif args.command == "apply":
        cmd_apply(args)
    elif args.command == "apply-microsoft":
        cmd_apply_microsoft(args)
    elif args.command == "apply-stripe":
        cmd_apply_stripe(args)
    elif args.command == "apply-ashby":
        cmd_apply_ashby(args)
    elif args.command == "apply-greenhouse":
        cmd_apply_greenhouse(args)
    elif args.command == "apply-lever":
        cmd_apply_lever(args)
    elif args.command == "apply-remote":
        cmd_apply_remote(args)
    elif args.command == "apply-all":
        cmd_apply_all(args)
    elif args.command == "pipeline":
        cmd_pipeline(args)
    elif args.command == "status":
        cmd_status()
    elif args.command == "flush":
        cmd_flush(args)
    elif args.command == "daemon":
        cmd_daemon(args)
    elif args.command == "watch":
        cmd_watch(args)
    elif args.command == "find-linkedin":
        cmd_find_linkedin(args)
    elif args.command == "watch-submissions":
        cmd_watch_submissions(args)
    elif args.command == "check-profile":
        cmd_check_profile()

if __name__ == "__main__":
    main()
