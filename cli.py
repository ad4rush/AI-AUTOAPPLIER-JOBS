#!/usr/bin/env python3
import sys
import re
import json
import argparse
import subprocess
from pathlib import Path

# Ensure project root is in sys.path
sys.path.insert(0, str(Path(__file__).resolve().parent))

from datetime import datetime, timedelta
from engine.config import assert_real_candidate_profile, RESUMES_GENERATED_DIR, PROJECT_ROOT, APPLIED_JOBS_DIR
from engine.db import (
    init_db,
    get_all_jobs,
    get_job_by_id,
    get_jobs_by_status,
    update_job_status,
    update_text_summary,
    record_agent_dispatch
)
from engine.scraper import run_parallel_scraper
from engine.evaluator import run_evaluation_pipeline
from engine.claude_tailor import generate_tailored_resume_via_claude
from engine.referral_drafter import generate_and_save_referral_drafts
from engine.scheduler import run_single_scrape_and_eval_cycle, run_periodic_daemon
from engine.microsoft_apply import apply_to_microsoft_job
from engine.stripe_apply import apply_to_stripe_job
from engine.barclays_apply import apply_to_barclays_workday
from engine.ashby_apply import apply_to_ashby_job
from engine.greenhouse_apply import apply_to_greenhouse_job
from engine.lever_apply import apply_to_lever_job
from engine.remote_apply import apply_to_remote_contract_job
from engine.jazzhr_apply import apply_to_jazzhr_job
from engine.submission_watcher import check_and_process_submissions, run_submission_watcher_loop
from engine.chatgpt_consultant import consult_ai_which_to_apply
from engine.portal_generator import generate_apply_script_for_company, dispatch_agy_for_custom_portal
from engine.applier import detect_ats_type

from engine.procedure_registry import (
    get_procedure,
    list_all_procedures,
    save_procedure,
    record_apply_event,
    dispatch_application,
)

def cmd_list_procedures(args):
    """Prints formatted table of all memorized company apply procedures."""
    procs = list_all_procedures()
    if getattr(args, "json", False):
        print(json.dumps(procs, indent=2))
        return

    print("\n" + "=" * 105)
    print(f"MEMORIZED COMPANY APPLY PROCEDURES ({len(procs)} Companies Registered in Memory)")
    print("=" * 105)
    fmt = "{:<16} {:<24} {:<22} {:<18} {:<12} {:<8}"
    print(fmt.format("COMPANY", "ATS PLATFORM", "AUTH METHOD", "POLICY", "ENGINE", "APPS"))
    print("-" * 105)
    for p in procs:
        print(fmt.format(
            p["company"][:15],
            p["ats_platform"][:23],
            p["auth_method"][:21],
            p["submission_policy"][:17],
            p["dispatch_engine"][:11],
            str(p["total_applications"])
        ))
    print("=" * 105)
    print("💡 To apply directly using memorized procedure:")
    print("   python3 cli.py apply --company <name> --url <job_url>")
    print("💡 To inspect full memorized procedure and selectors for any company:")
    print("   python3 cli.py show-procedure --company <name>\n")

def cmd_show_procedure(args):
    """Displays detailed JSON procedure for a specific company."""
    proc = get_procedure(company=args.company)
    if not proc:
        print(f"[!] No memorized procedure found for company: '{args.company}'")
        return
    print("\n" + "=" * 70)
    print(f"MEMORIZED APPLY PROCEDURE: {proc.get('company', args.company)}")
    print("=" * 70)
    print(json.dumps(proc, indent=2))
    print("=" * 70 + "\n")

def cmd_record_procedure(args):
    """Records or updates a company procedure in memory."""
    existing = get_procedure(company=args.company) or {}
    existing.update({
        "company": args.company,
        "ats_platform": args.ats,
        "supported_urls": [args.url] if args.url else existing.get("supported_urls", []),
        "authentication": {"method": args.auth},
        "submission_policy": args.policy,
        "resume_archetype": args.archetype,
        "dispatch_engine": args.engine or existing.get("dispatch_engine", "auto"),
        "cli_apply_command": f"python3 cli.py apply --company {args.company.lower()} --url <url>"
    })
    path = save_procedure(args.company, existing)
    print(f"[+] Successfully memorized apply procedure for {args.company} at: {path}")

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
        record_apply_event("Microsoft", args.url, "APPLIED" if args.submit else "STAGED_FOR_REVIEW", args.submit, args.resume or "")
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
        record_apply_event("Stripe", args.url, "APPLIED" if args.submit else "STAGED_FOR_REVIEW", args.submit, args.resume or "")
        if args.submit:
            print("\n[+] Stripe application successfully SUBMITTED!")
        else:
            print("\n[+] Stripe apply procedure STAGED & VALIDATED successfully!")
            print("    👉 EGO-BROWSER TAB: TaskSpace 'stripe_auto_apply' (Profile 1: Main Profile)")
            print("    👉 Action: Open this tab in ego-browser and press Submit.")
    else:
        print("\n[!] Application staging encountered issues. Check logs above.")

def cmd_apply_barclays(args):
    assert_real_candidate_profile()
    res = apply_to_barclays_workday(args.url, resume_path=args.resume, submit=args.submit)
    if res.get("success"):
        record_apply_event("Barclays", args.url, "APPLIED" if args.submit else "STAGED_FOR_REVIEW", args.submit, args.resume or "")
        print("\n[+] Barclays apply procedure STAGED & VALIDATED successfully!")
        print("    👉 EGO-BROWSER TAB: TaskSpace 'barclays_apply' (Profile 1: Main Profile)")
        print("    👉 Action: Confirm Workday verification email, then sign in to complete Step 7/7 Review.")
    else:
        print("\n[!] Application staging encountered issues. Check logs above.")

def cmd_apply_ashby(args):
    assert_real_candidate_profile()
    task_space = getattr(args, "task_space", None) or "ashby_auto_apply"
    res = apply_to_ashby_job(args.url, resume_path=args.resume, submit=args.submit, task_space_name=task_space)
    if res.get("success"):
        m_comp = re.search(r"ashbyhq\.com/([^/]+)", args.url, re.IGNORECASE)
        comp = getattr(args, "company", None) or (m_comp.group(1).capitalize() if m_comp else "Ashby Supported Company")
        record_apply_event(comp, args.url, "APPLIED" if args.submit else "STAGED_FOR_REVIEW", args.submit, args.resume or "")
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
        comp = getattr(args, "company", None) or ("Anthropic" if "anthropic" in args.url.lower() else "Greenhouse Supported Company")
        record_apply_event(comp, args.url, "APPLIED" if args.submit else "STAGED_FOR_REVIEW", args.submit, args.resume or "")
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
        comp = getattr(args, "company", None) or ("Palantir" if "palantir" in args.url.lower() else "Lever Supported Company")
        record_apply_event(comp, args.url, "APPLIED" if args.submit else "STAGED_FOR_REVIEW", args.submit, args.resume or "")
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
        record_apply_event("Mercor", args.url, "APPLIED" if args.submit else "STAGED_FOR_REVIEW", args.submit, args.resume or "")
        if args.submit:
            print("\n[+] Remote contract application successfully SUBMITTED!")
        else:
            print("\n[+] Remote contract apply procedure STAGED & VALIDATED successfully!")
            print("    👉 EGO-BROWSER TAB: TaskSpace 'remote_contract_auto_apply' (Profile 1: Main Profile)")
            print("    👉 Action: Open this tab in ego-browser and press Submit.")
    else:
        print("\n[!] Application staging encountered issues. Check logs above.")

def cmd_apply_jazzhr(args):
    assert_real_candidate_profile()
    task_space = getattr(args, "task_space", None) or "jazzhr_auto_apply"
    res = apply_to_jazzhr_job(args.url, resume_path=args.resume, company_name=getattr(args, "company", None), submit=args.submit, task_space_name=task_space)
    if res.get("success"):
        comp = getattr(args, "company", None) or res.get("company") or "JazzHR Supported Company"
        new_status = "APPLIED" if res.get("submitted") else "STAGED_FOR_REVIEW"
        record_apply_event(comp, args.url, new_status, res.get("submitted", False), args.resume or "")
        if res.get("submitted"):
            print(f"\n[+] JazzHR application for {comp} successfully SUBMITTED!")
        else:
            print(f"\n[+] JazzHR apply procedure for {comp} STAGED & VALIDATED successfully!")
            print(f"    👉 EGO-BROWSER TAB: TaskSpace '{task_space}' (Profile 1: Main Profile)")
            print("    👉 Action: Solve human reCAPTCHA in ego-browser and click Submit Application.")
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
    days_limit = getattr(args, "days", None)
    cutoff = (datetime.now() - timedelta(days=days_limit)).strftime("%Y-%m-%d") if days_limit else None

    targets = [
        j for j in jobs
        if j.get("priority_level") in ("CRITICAL_PRIORITY", "HIGH_PRIORITY", "NORMAL")
        and j.get("status") in ("EVALUATED", "TAILORED", "REFERRAL_DRAFTED")
        and (not cutoff or (j.get("created_at") or "")[:10] >= cutoff)
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
        comp = j.get("company") or ""
        url = j.get("url") or ""
        proc = get_procedure(company=comp, url=url)
        if proc and proc.get("dispatch_engine"):
            supported.append((j, proc))

    print(f"[*] Found {len(supported)} qualified applications with memorized apply procedures...")
    if not supported:
        print("[*] No qualified pending jobs on supported automated boards.")
        return

    count = 0
    for j, proc in supported:
        if args.limit and count >= args.limit:
            break
        job_id = j["job_id"]
        company = j["company"]
        title = j["title"]
        url = j["url"]
        ats_plat = proc.get("ats_platform", "ATS")

        print(f"\n=======================================================")
        print(f"AUTOMATED APPLICATION [{count+1}/{len(supported)}]: {company} — {title}")
        print(f"URL: {url} | Platform: {ats_plat.upper()}")
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
            target_dir = RESUMES_GENERATED_DIR / f"{clean_company}_{clean_job_id}"
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
            # Deterministic, archetype-aware resume compilation: NEVER leak another company's PDF!
            from engine.claude_tailor import select_specialization_resume, inject_candidate_profile
            from engine.resume_ats_sanitizer import compile_and_guarantee_single_page
            raw_jd = ""
            if j.get("raw_jd_path") and Path(j["raw_jd_path"]).exists():
                try:
                    with open(j["raw_jd_path"], "r", encoding="utf-8") as f:
                        raw_jd = f.read()
                except Exception:
                    pass

            spec_tex, spec_name = select_specialization_resume(title, raw_jd)
            print(f"[*] Compiling dedicated {spec_name} archetype for {comp}...")
            clean_company = re.sub(r'[^a-zA-Z0-9]', '_', comp.lower())
            clean_job_id = re.sub(r'[^a-zA-Z0-9]', '_', str(job_id).lower())
            target_dir = RESUMES_GENERATED_DIR / f"{clean_company}_{clean_job_id}"
            target_dir.mkdir(parents=True, exist_ok=True)

            with open(spec_tex, "r", encoding="utf-8") as f:
                tex_content = f.read()
            tex_content = inject_candidate_profile(tex_content)

            out_tex = target_dir / f"resume_{clean_company}_{clean_job_id}.tex"
            with open(out_tex, "w", encoding="utf-8") as f:
                f.write(tex_content)

            comp_ok, comp_log, comp_pdf, page_count = compile_and_guarantee_single_page(out_tex, target_dir)
            if comp_ok and comp_pdf and comp_pdf.exists():
                pdf_path = str(comp_pdf)
                print(f"[+] Compiled dedicated archetype resume (Page count: {page_count}): {pdf_path}")
                print(f"[*] Using verified candidate resume: {pdf_path}")

        is_remote_contract = (j.get("fit_verdict") == "REMOTE_CONTRACT_MATCH") or ("contract" in title.lower())
        policy = proc.get("submission_policy", "STAGE_AND_VALIDATE")
        should_submit = args.submit or (policy == "AUTO_SUBMIT" and is_remote_contract)
        slug_name = re.sub(r"[^a-z0-9]", "", company.lower())
        task_space = f"{slug_name}_auto_apply"

        res = dispatch_application(
            company=company,
            url=url,
            resume_path=pdf_path,
            submit=should_submit,
            task_space=task_space
        )

        if res.get("success"):
            new_status = "APPLIED" if should_submit else "STAGED_FOR_REVIEW"
            note_text = "Auto-submitted (Immediate Submit Flow)" if should_submit else f"Staged 100% in ego-browser TaskSpace '{task_space}' (Profile 1). Ready for one-click submit."
            update_job_status(job_id, new_status, {
                "applied_at": datetime.now().isoformat(),
                "tailored_resume_dir": pdf_path,
                "notes": note_text
            })

            # Record agent dispatch in SQLite memory
            try:
                record_agent_dispatch(
                    company=company,
                    job_id=job_id,
                    agent_type=ats_plat,
                    conversation_id=f"auto-apply-{clean_job_id}",
                    status="SUBMITTED" if should_submit else "STAGED_FOR_REVIEW",
                    role_title=title,
                    notes=note_text
                )
            except Exception as e:
                pass

            # Archive submitted PDF
            if should_submit and pdf_path and Path(pdf_path).exists():
                try:
                    import shutil
                    archive_dir = APPLIED_JOBS_DIR / f"{clean_company}_{clean_job_id}"
                    archive_dir.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(pdf_path, archive_dir / "submitted_resume.pdf")
                    meta_path = archive_dir / "application_status.json"
                    with open(meta_path, "w", encoding="utf-8") as f:
                        json.dump({
                            "company": company,
                            "job_id": job_id,
                            "title": title,
                            "url": url,
                            "applied_at": datetime.now().isoformat(),
                            "status": "APPLIED",
                            "resume_submitted": str(archive_dir / "submitted_resume.pdf"),
                            "notes": note_text
                        }, f, indent=2)
                except Exception:
                    pass

            if should_submit:
                print(f"[+] Application successfully SUBMITTED for {company} ({title})")
            else:
                print(f"[+] Application successfully STAGED & VALIDATED for {company} ({title})")
                print(f"    👉 EGO-BROWSER TAB: TaskSpace '{task_space}' (Profile 1: Main Profile)")
                print(f"    👉 Form Status: 100% pre-filled. Open this tab in ego-browser and press Submit.")
        else:
            print(f"[!] Application issue for {company}: {res.get('error', 'Check logs above')}")
        count += 1

def cmd_list_accounts(args):
    from engine.account_switcher import list_registered_accounts
    accounts = list_registered_accounts()
    if getattr(args, "json", False):
        print(json.dumps(accounts, indent=2))
        return
    print("\n" + "=" * 95)
    print("REGISTERED ACCOUNTS & SERVICE PROFILES (ego-browser Routing Matrix)")
    print("=" * 95)
    print(f"{'SERVICE':<32} | {'PROFILE':<10} | {'EMAIL':<28} | {'AUTH TYPE':<20}")
    print("-" * 95)
    for a in accounts:
        print(f"{a['service_name']:<32} | {a['profile_id']:<10} | {a['email']:<28} | {a['auth_type']:<20}")
    print("=" * 95 + "\n")

def cmd_switch_account(args):
    from engine.account_switcher import open_service_in_profile
    res = open_service_in_profile(args.service, target_url=getattr(args, "url", None))
    print(json.dumps(res, indent=2))

def cmd_consult_chatgpt(args):
    from engine.chatgpt_consultant import query_chatgpt, evaluate_job_with_chatgpt
    from pathlib import Path

    company = getattr(args, "company", None)
    title = getattr(args, "title", None)

    if company and title:
        jd_input = getattr(args, "jd", None) or ""
        jd_text = jd_input
        if jd_input and len(jd_input) < 260:
            try:
                p = Path(jd_input)
                if p.exists() and p.is_file():
                    jd_text = p.read_text(encoding="utf-8")
            except Exception:
                pass

        print(f"[*] Asking ChatGPT (Profile 1) to evaluate whole JD for {company} — {title}...")
        evaluation = evaluate_job_with_chatgpt(
            company=company,
            title=title,
            jd_text=jd_text,
            location=getattr(args, "location", "Remote"),
            salary_info=getattr(args, "salary", ""),
            url=getattr(args, "url", "")
        )

        print("\n" + "=" * 70)
        print("CHATGPT STRATEGIC JOB EVALUATION & RESUME POLICY ANALYSIS")
        print("=" * 70)
        apply_verdict = "✓ YES (APPLY)" if evaluation.get("should_apply") else "✗ NO (SKIP)"
        custom_resume_verdict = "★ YES — TAILOR CUSTOM RESUME (Claude Sonnet 3.5)" if evaluation.get("custom_resume_required") else "● NO — USE GOLD MASTER RESUME"

        print(f"  Target Company        : {company}")
        print(f"  Target Role           : {title}")
        print(f"  Fit Score             : {evaluation.get('fit_score', 'N/A')}/100")
        print(f"  Should Apply?         : {apply_verdict}")
        print(f"  Custom Resume Policy  : {custom_resume_verdict}")
        print(f"  Recommended Resume    : {evaluation.get('recommended_master_resume', 'RESUME_1_AI_ENGINEER')}")
        print(f"  Company Reputation    : {evaluation.get('company_tier_and_reputation', 'Standard')}")
        print(f"  Compensation Level    : {evaluation.get('compensation_estimate', 'N/A')}")
        print("-" * 70)
        print(f"  Reasoning:\n    {evaluation.get('reasoning', '')}")
        if evaluation.get("key_matches"):
            print(f"  Key Technical Matches:\n    {', '.join(evaluation.get('key_matches'))}")
        if evaluation.get("potential_concerns"):
            print(f"  Potential Concerns:\n    {', '.join(evaluation.get('potential_concerns'))}")
        if evaluation.get("tailoring_focus"):
            print(f"  Tailoring Focus:\n    {evaluation.get('tailoring_focus')}")
        print("=" * 70 + "\n")
        print(json.dumps(evaluation, indent=2))
        return

    if not getattr(args, "prompt", None):
        print("[!] Error: Either provide --prompt OR provide --company and --title (--jd).")
        return

    from engine.config import resolve_candidate_tokens
    resolved_prompt = resolve_candidate_tokens(args.prompt)
    print(f"[*] Querying ChatGPT in Profile 1 with prompt: {resolved_prompt[:100]}...")
    ans = query_chatgpt(resolved_prompt)
    print("\n" + "=" * 60)
    print("CHATGPT RESPONSE:")
    print("=" * 60)
    print(ans)
    print("=" * 60 + "\n")

def cmd_generate_pitch(args):
    from engine.chatgpt_consultant import generate_application_pitch
    skills = args.skills.split(",") if getattr(args, "skills", None) else None
    print(f"[*] Generating application pitch for {args.company} — {args.title}...")
    pitch = generate_application_pitch(
        company=args.company,
        title=args.title,
        jd_text=getattr(args, "jd", "") or "",
        matched_skills=skills
    )
    print("\n" + json.dumps(pitch, indent=2))

def cmd_delegate(args):
    from engine.agent_delegator import delegate_job_to_agent
    from engine.db import get_job_by_id

    job_row = get_job_by_id(args.job_id)
    if not job_row:
        print(f"[-] Error: Job ID '{args.job_id}' not found in database.")
        sys.exit(1)

    job = dict(job_row)
    print(f"[*] Delegating job '{args.job_id}' ({job.get('company')} — {job.get('title')}) to AGY worker agent...")
    res = delegate_job_to_agent(
        job_id=job["job_id"],
        company=job["company"],
        title=job["title"],
        url=job["url"],
        location=job.get("location", ""),
        submit=args.submit,
        archetype=job.get("archetype", "RESUME_1_AI_ENGINEER"),
        conversation_id=getattr(args, "convo", None),
        sync=args.sync
    )
    print("\n" + json.dumps(res, indent=2))

def cmd_delegate_batch(args):
    from engine.agent_delegator import delegate_batch_jobs
    from engine.db import get_jobs_by_status

    jobs = get_jobs_by_status(args.status)
    if not jobs:
        print(f"[*] No jobs found with status '{args.status}'.")
        return

    print(f"[*] Found {len(jobs)} jobs with status '{args.status}'. Delegating up to {args.limit} to AGY worker agents...")
    results = delegate_batch_jobs(jobs[:args.limit], submit=args.submit, max_concurrent=args.limit)
    print("\n" + json.dumps(results, indent=2))

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

def cmd_find_remote(args):
    init_db()
    from engine.remote_scraper import scrape_and_resolve_himalayas_matches
    pages = getattr(args, "pages", 2)
    max_resolve = getattr(args, "limit", 8)
    jobs = scrape_and_resolve_himalayas_matches(pages=pages, max_resolve=max_resolve)
    print(f"[+] Discovered and resolved {len(jobs)} fresh remote ATS jobs.")

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

def cmd_tailor_claude(args):
    assert_real_candidate_profile()
    init_db()
    from engine.claude_tailor import generate_tailored_resume_via_claude
    from engine.db import get_job_by_id, get_all_jobs

    target_job = None
    if args.job_id:
        target_job = get_job_by_id(args.job_id)
    elif args.company:
        jobs = [j for j in get_all_jobs() if args.company.lower() in j["company"].lower()]
        if jobs:
            target_job = jobs[0]

    if not target_job:
        print(f"[!] Could not find job for company='{args.company}', job_id='{args.job_id}'")
        return

    job_id = target_job["job_id"]
    company = target_job["company"]
    title = target_job["title"]
    raw_jd_path = target_job["raw_jd_path"]
    jd_text = ""
    if raw_jd_path and Path(raw_jd_path).exists():
        with open(raw_jd_path, "r", encoding="utf-8") as f:
            jd_text = f.read()

    print(f"\n[*] Tailoring resume with Claude Sonnet 3.5 for {company} — {title} (ID: {job_id})...")
    success, msg, tex_path, pdf_path = generate_tailored_resume_via_claude(
        job_id, company, title, jd_text
    )
    if success:
        print(f"[+] Tailoring SUCCESS: {pdf_path}")
    else:
        print(f"[!] Tailoring FAILED: {msg}")

def cmd_record_dispatch(args):
    init_db()
    from engine.db import record_agent_dispatch
    did = record_agent_dispatch(
        company=args.company,
        job_id=args.job_id,
        agent_type=args.agent,
        conversation_id=args.convo,
        status=args.status,
        role_title=args.role or "",
        notes=args.notes or ""
    )
    print(f"[+] Agent dispatch #{did} recorded for {args.company} (Convo: {args.convo})")

def cmd_list_dispatches(args):
    init_db()
    from engine.db import get_dispatches_by_company, list_all_dispatches
    if args.company:
        rows = get_dispatches_by_company(args.company)
        print(f"\nDispatches for company '{args.company}' ({len(rows)} found):")
    else:
        rows = list_all_dispatches(limit=args.limit)
        print(f"\nRecent Agent Dispatches across all companies ({len(rows)} found):")
    print("-" * 80)
    for r in rows:
        print(f"[{r['id']}] Company: {r['company']:18s} | Agent: {r['agent_type']:16s} | Status: {r['status']:10s}")
        print(f"    Conversation ID: {r['conversation_id']}")
        if r['job_id']:
            print(f"    Job ID: {r['job_id']} | Role: {r['role_title']}")
        if r['notes']:
            print(f"    Notes: {r['notes']}")
        print(f"    Timestamp: {r['created_at']}")
        print("")

def cmd_apply(args):
    init_db()
    url = getattr(args, "url", None)
    company = getattr(args, "company", None) or ""
    resume_path = getattr(args, "resume", None)
    submit = getattr(args, "submit", False)

    # 1. Direct apply via memorized procedure
    if url:
        proc = get_procedure(company=company, url=url)
        comp_name = proc.get("company") if proc else (company or "Target Company")
        ats = proc.get("ats_platform") if proc else "Unknown ATS"
        policy = proc.get("submission_policy") if proc else ("AUTO_SUBMIT" if submit else "STAGE_AND_VALIDATE")
        print("\n" + "=" * 70)
        print(f"APPLYING DIRECTLY VIA MEMORIZED PROCEDURE")
        print(f"Company: {comp_name} | ATS: {ats} | Policy: {policy}")
        print(f"URL: {url}")
        print("=" * 70)
        res = dispatch_application(company=comp_name, url=url, resume_path=resume_path, submit=submit)
        if res.get("success"):
            new_status = "APPLIED" if submit else "STAGED_FOR_REVIEW"
            print(f"\n[+] Application {'SUBMITTED' if submit else 'STAGED & VALIDATED'} successfully for {comp_name}!")
            try:
                for j in get_all_jobs():
                    j_url = j["url"] or ""
                    if (j_url and url and (j_url in url or url in j_url)) or (company and j["company"].lower() == company.lower() and j["status"] in ("TAILORED", "EVALUATED")):
                        update_job_status(j["job_id"], new_status, {
                            "applied_at": datetime.now().isoformat() if submit else None,
                            "notes": f"{new_status} via direct apply procedure ({url})"
                        })
                        print(f"    [+] Updated database record (ID: {j['job_id']}) to {new_status}")
                        break
            except Exception as e:
                print(f"    [!] Warning: Could not update DB status: {e}")
        else:
            print(f"\n[!] Application issue for {comp_name}: {res.get('error', 'Check output above')}")
        return

    # 2. Batch apply over tailored/evaluated jobs
    tailored = get_jobs_by_status("TAILORED")
    if not tailored:
        tailored = get_jobs_by_status("REFERRAL_DRAFTED")
    if not tailored:
        # Also check priority evaluated jobs
        jobs = [dict(j) for j in get_all_jobs()]
        tailored = [
            j for j in jobs
            if j.get("priority_level") in ("CRITICAL_PRIORITY", "HIGH_PRIORITY")
            and j.get("status") in ("EVALUATED", "TAILORED", "REFERRAL_DRAFTED")
        ]
    if not tailored:
        print("[*] No qualified jobs ready for auto-apply. Run 'eval' or 'tailor' first.")
        return

    print(f"[*] Found {len(tailored)} priority jobs ready for application dispatch...")
    count = 0
    for j in tailored:
        if args.limit and count >= args.limit:
            break
        job_id = j["job_id"]
        comp = j["company"]
        title = j["title"]
        j_url = j["url"]
        resume_dir = j.get("tailored_resume_dir")

        pdf_path = None
        if resume_dir and Path(resume_dir).exists():
            pdfs = list(Path(resume_dir).glob("*.pdf"))
            if pdfs:
                pdf_path = str(pdfs[0])

        if not pdf_path:
            clean_company = re.sub(r'[^a-zA-Z0-9]', '_', comp.lower())
            clean_job_id = re.sub(r'[^a-zA-Z0-9]', '_', job_id.lower())
            target_dir = RESUMES_GENERATED_DIR / f"{clean_company}_{clean_job_id}"
            if target_dir.exists():
                pdfs = list(target_dir.glob("*.pdf"))
                if pdfs:
                    pdf_path = str(pdfs[0])

        if not pdf_path:
            # Deterministic, archetype-aware resume compilation: NEVER leak another company's PDF!
            from engine.claude_tailor import select_specialization_resume, inject_candidate_profile
            from engine.resume_ats_sanitizer import compile_and_guarantee_single_page
            raw_jd = ""
            if j.get("raw_jd_path") and Path(j["raw_jd_path"]).exists():
                try:
                    with open(j["raw_jd_path"], "r", encoding="utf-8") as f:
                        raw_jd = f.read()
                except Exception:
                    pass

            spec_tex, spec_name = select_specialization_resume(title, raw_jd)
            print(f"[*] Compiling dedicated {spec_name} archetype for {comp}...")
            clean_company = re.sub(r'[^a-zA-Z0-9]', '_', comp.lower())
            clean_job_id = re.sub(r'[^a-zA-Z0-9]', '_', str(job_id).lower())
            target_dir = RESUMES_GENERATED_DIR / f"{clean_company}_{clean_job_id}"
            target_dir.mkdir(parents=True, exist_ok=True)

            with open(spec_tex, "r", encoding="utf-8") as f:
                tex_content = f.read()
            tex_content = inject_candidate_profile(tex_content)

            out_tex = target_dir / f"resume_{clean_company}_{clean_job_id}.tex"
            with open(out_tex, "w", encoding="utf-8") as f:
                f.write(tex_content)

            comp_ok, comp_log, comp_pdf, page_count = compile_and_guarantee_single_page(out_tex, target_dir)
            if comp_ok and comp_pdf and comp_pdf.exists():
                pdf_path = str(comp_pdf)
                print(f"[+] Compiled dedicated archetype resume (Page count: {page_count}): {pdf_path}")

        proc = get_procedure(company=comp, url=j_url)
        is_remote_contract = (j.get("fit_verdict") == "REMOTE_CONTRACT_MATCH") or ("contract" in title.lower())
        policy = proc.get("submission_policy", "STAGE_AND_VALIDATE") if proc else "STAGE_AND_VALIDATE"
        should_submit = submit or (policy == "AUTO_SUBMIT" and is_remote_contract)

        print(f"\n[*] Dispatching application [{count+1}/{len(tailored)}]: {comp} — {title}")
        res = dispatch_application(company=comp, url=j_url, resume_path=pdf_path, submit=should_submit)
        if res.get("success"):
            new_status = "APPLIED" if should_submit else "STAGED_FOR_REVIEW"
            update_job_status(job_id, new_status, {
                "applied_at": datetime.now().isoformat(),
                "tailored_resume_dir": str(pdf_path) if pdf_path else "",
                "notes": f"Applied via memorized {comp} procedure"
            })
            print(f"[+] Application {'SUBMITTED' if should_submit else 'STAGED & VALIDATED'} for {comp} ({title})")
        else:
            print(f"[!] Application issue for {comp}: {res.get('error', 'Check logs')}")
        count += 1

def cmd_pipeline(args):
    from engine.pipeline import run_pipeline_cycle
    workers = getattr(args, "workers", 8) or 8
    limit = getattr(args, "limit", 5) or 5
    run_pipeline_cycle(workers=workers, limit=limit, assert_candidate=True)
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

def cmd_daily(args):
    """
    Daily autonomous job discovery, resume tailoring, remote auto-apply,
    FTE form staging, and inbox monitoring execution.
    Triggered once when candidate starts their work session.
    """
    assert_real_candidate_profile()
    print("\n" + "=" * 80)
    print("🌅 STARTING DAILY AUTONOMOUS DISCOVERY & AUTO-APPLY CYCLE")
    print("=" * 80)

    # 1. Broad multi-board scraping
    print("\n[Daily Phase 1/5] Comprehensive Multi-Board Scraping (Greenhouse, Lever, Ashby, RemoteOK, Jobicy, Himalayas, WWR)...")
    new_jobs = run_parallel_scraper(max_workers=getattr(args, "workers", 8) or 8)
    
    # Ingest Naukri
    if not getattr(args, "skip_naukri", False):
        try:
            from engine.naukri_scraper import run_naukri_pipeline
            run_naukri_pipeline()
        except Exception as e:
            print(f"[!] Naukri scraping note: {e}")

    # Ingest LinkedIn
    if not getattr(args, "skip_linkedin", False):
        try:
            from engine.linkedin_scraper import run_linkedin_pipeline
            run_linkedin_pipeline()
        except Exception as e:
            print(f"[!] LinkedIn scraping note: {e}")

    # Ingest Y Combinator (y2c)
    if not getattr(args, "skip_yc", False):
        try:
            from engine.yc_scraper import run_yc_pipeline
            run_yc_pipeline(max_queries=3, jobs_per_query=15)
        except Exception as e:
            print(f"[!] YC scraping note: {e}")

    # 2. Evaluation
    print("\n[Daily Phase 2/5] Running JEV & Tier Evaluation...")
    run_evaluation_pipeline()

    # 3. Dynamic Tailoring & Auto-Apply
    print("\n[Daily Phase 3/5] Dynamic Tailoring & Application Dispatch (Auto-Apply Remote / Stage FTE)...")
    cmd_apply_all(args)

    # 4. Check staged submissions
    print("\n[Daily Phase 4/5] Checking Submissions & Archiving...")
    check_and_process_submissions()
    update_text_summary()

    # 5. Inbox Scan
    print("\n[Daily Phase 5/5] Scanning Inboxes for Application Receipts...")
    try:
        from engine.email_reader import fetch_inbox_emails, format_email_table, PROFILES_CONFIG
        results = fetch_inbox_emails(profile="all", limit=5)
        for prof_key, prof_res in results.items():
            if prof_res.get("success"):
                title = PROFILES_CONFIG[prof_key]["display_name"]
                print(format_email_table(prof_res.get("emails", []), title))
    except Exception as e:
        print(f"[!] Email reader note: {e}")

    print("\n" + "=" * 80)
    print("✅ DAILY RUN COMPLETE. STATUS DASHBOARD:")
    print("=" * 80)
    cmd_status()

def cmd_check_emails(args):
    import json
    from engine.email_reader import (
        fetch_inbox_emails,
        read_email_message,
        format_email_table,
        format_email_detail,
        PROFILES_CONFIG
    )
    if args.read:
        target_prof = "college" if args.profile == "all" else args.profile
        print(f"[*] Reading full body of email #{args.read} from {target_prof} profile...")
        detail = read_email_message(profile_key=target_prof, index=args.read)
        if args.json:
            print(json.dumps(detail, indent=2))
        else:
            if detail.get("success"):
                print(format_email_detail(detail))
            else:
                print(f"[!] Error reading email: {detail.get('error')}")
    else:
        results = fetch_inbox_emails(profile=args.profile, limit=args.limit, search_query=args.search)
        if args.json:
            print(json.dumps(results, indent=2))
        else:
            for prof_key, prof_res in results.items():
                if prof_res.get("success"):
                    title = PROFILES_CONFIG[prof_key]["display_name"]
                    if args.search:
                        title += f" [Filtered: '{args.search}']"
                    print(format_email_table(prof_res.get("emails", []), title))
                else:
                    print(f"[!] Failed to fetch emails for {prof_key}: {prof_res.get('error')}")

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

    find_remote_p = subparsers.add_parser("find-remote", help="Scrape personalized remote match cards on Himalayas and resolve real ATS URLs")
    find_remote_p.add_argument("--pages", type=int, default=2, help="Number of match pages to scan (default: 2)")
    find_remote_p.add_argument("--limit", type=int, default=8, help="Max fresh jobs to resolve destination ATS for (default: 8)")

    eval_p = subparsers.add_parser("eval", help="Evaluate discovered jobs with JEV & company tiers")
    eval_p.add_argument("--all", action="store_true", help="Re-evaluate all existing jobs in the database")

    tailor_p = subparsers.add_parser("tailor", help="Dynamically tailor resumes with Claude & compile to PDF")
    tailor_p.add_argument("--limit", type=int, default=3, help="Max resumes to tailor in this run")

    apply_p = subparsers.add_parser("apply", help="Execute auto-apply flow via memorized company procedure")
    apply_p.add_argument("--url", help="Direct job URL to apply to using memorized company procedure")
    apply_p.add_argument("--company", help="Optional company name to match procedure")
    apply_p.add_argument("--resume", help="Optional tailored PDF resume path")
    apply_p.add_argument("--submit", action="store_true", help="Submit immediately (default: stage and validate)")
    apply_p.add_argument("--limit", type=int, default=3, help="Max jobs to apply to in batch run")

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

    barclays_p = subparsers.add_parser("apply-barclays", help="Auto-apply to Barclays India jobs (Workday)")
    barclays_p.add_argument("--url", default="https://search.jobs.barclays/job/-/-/13015/98815634656?src=JB-12860", help="Job URL")
    barclays_p.add_argument("--resume", help="Optional tailored PDF resume path")
    barclays_p.add_argument("--submit", action="store_true", help="Submit immediately (default: stage and validate)")

    apply_all_p = subparsers.add_parser("apply-all", help="Unified batch auto-apply across supported company portals")
    apply_all_p.add_argument("--limit", type=int, default=5, help="Max applications to process (default: 5)")
    apply_all_p.add_argument("--days", type=int, default=4, help="Apply only to jobs found within the last N days (default: 4)")
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

    jazzhr_p = subparsers.add_parser("apply-jazzhr", help="Auto-apply to JazzHR (applytojob.com) jobs (ArangoDB, etc.)")
    jazzhr_p.add_argument("--url", required=True, help="JazzHR Job URL")
    jazzhr_p.add_argument("--company", help="Optional company name")
    jazzhr_p.add_argument("--resume", help="Optional tailored PDF resume path")
    jazzhr_p.add_argument("--task-space", help="Optional ego-browser task space name (default: jazzhr_auto_apply)")
    jazzhr_p.add_argument("--submit", action="store_true", help="Submit immediately (default: stage and validate)")

    subparsers.add_parser("flush", help="Execute hardware, memory, and SQLite maintenance flush")

    daemon_p = subparsers.add_parser("daemon", help="Run 24/7 background autonomous monitoring, submission watcher & flush daemon")
    daemon_p.add_argument("--interval", type=float, default=6.0, help="Base scrape interval in hours (default: 6.0)")
    daemon_p.add_argument("--jitter", type=float, default=0.5, help="Interval jitter in hours (default: 0.5)")
    daemon_p.add_argument("--watcher-interval", type=float, default=10.0, help="Watcher check interval in seconds (default: 10.0)")
    daemon_p.add_argument("--now", action="store_true", help="Run a scrape/stage cycle immediately upon startup")

    prime_p = subparsers.add_parser("prime-chatgpt", help="Prime ChatGPT across ego-browser profiles with master dossier for permanent memorization")
    prime_p.add_argument("--force", action="store_true", help="Force re-priming even if cached")
    prime_p.add_argument("--profile", default="all", choices=["all", "Profile 1", "Default", "Profile 2"], help="Ego-browser profile to prime (default: all)")

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

    # Naukri Scraper Plugin
    naukri_p = subparsers.add_parser("find-naukri", help="Scrape jobs from Naukri.com via ego-browser")
    naukri_p.add_argument("--profile", default="Profile 1", help="Ego-browser profile ID (default: Profile 1)")

    # Daily Autonomous Workflow Command (Zero background daemons, runs on user initiation)
    daily_p = subparsers.add_parser("daily", help="Run complete daily cycle: multi-board scraping, evaluation, remote auto-apply & FTE staging")
    daily_p.add_argument("--workers", type=int, default=8, help="Scraper worker threads (default: 8)")
    daily_p.add_argument("--limit", type=int, default=5, help="Max jobs to process/apply (default: 5)")
    daily_p.add_argument("--auto-tailor", action="store_true", default=True, help="Auto-tailor resumes if needed")
    daily_p.add_argument("--skip-naukri", action="store_true", help="Skip Naukri scraping")
    daily_p.add_argument("--skip-linkedin", action="store_true", help="Skip LinkedIn scraping")

    # Autonomous Email Reader Command
    email_p = subparsers.add_parser("check-emails", help="Inspect top emails from personal and college inboxes via ego-browser")
    email_p.add_argument("--profile", choices=["personal", "college", "all"], default="all", help="Which Gmail profile to check (default: all)")
    email_p.add_argument("--limit", type=int, default=10, help="Number of emails to fetch (default: 10)")
    email_p.add_argument("--search", help="Optional keyword filter (case-insensitive across sender, subject, snippet)")
    email_p.add_argument("--read", type=int, help="Read full message body of email at specified index")
    email_p.add_argument("--json", action="store_true", help="Output raw JSON instead of table")

    # Procedure Memory Subparsers
    proc_list_p = subparsers.add_parser("list-procedures", help="List all memorized company apply procedures, ATS engines, and policies")
    proc_list_p.add_argument("--json", action="store_true", help="Output raw JSON format")

    proc_show_p = subparsers.add_parser("show-procedure", help="Show full memorized procedure details for a company")
    proc_show_p.add_argument("--company", required=True, help="Company name (e.g. microsoft, stripe, barclays, openai, anthropic)")

    proc_rec_p = subparsers.add_parser("record-procedure", help="Record or update a company apply procedure")
    proc_rec_p.add_argument("--company", required=True, help="Company name")
    proc_rec_p.add_argument("--ats", required=True, help="ATS platform (eightfold, workday, greenhouse, ashby, lever, etc.)")
    proc_rec_p.add_argument("--url", help="Canonical job board or application URL pattern")
    proc_rec_p.add_argument("--auth", default="Public / Direct", help="Authentication method (e.g. Google OAuth, Workday)")
    proc_rec_p.add_argument("--policy", choices=["STAGE_AND_VALIDATE", "AUTO_SUBMIT"], default="STAGE_AND_VALIDATE", help="Submission policy")
    proc_rec_p.add_argument("--archetype", default="RESUME_1_AI_ENGINEER", help="Resume archetype")
    proc_rec_p.add_argument("--engine", help="Dispatch engine (microsoft_apply, stripe_apply, barclays_apply, ashby_apply, greenhouse_apply, lever_apply, remote_apply)")

    # Profile Verification Command
    subparsers.add_parser("check-profile", help="Verify active candidate credentials and guarantee zero dummy placeholders")

    # Account Switcher & Profile Matrix Subparsers
    accounts_p = subparsers.add_parser("list-accounts", help="List all registered accounts, services, and profile routing matrix")
    accounts_p.add_argument("--json", action="store_true", help="Output raw JSON format")

    switch_p = subparsers.add_parser("switch-account", help="Open a target service or portal in its assigned browser profile")
    switch_p.add_argument("--service", required=True, help="Service name (e.g. mercor, chatgpt, dataannotation, turing, alignerr, linkedin, personal_gmail, college_gmail)")
    switch_p.add_argument("--url", help="Optional target URL to navigate to")

    # ChatGPT Consultation Subparsers
    gpt_p = subparsers.add_parser("consult-chatgpt", help="Query candidate's authenticated ChatGPT session in Profile 1 or evaluate whole JD")
    gpt_p.add_argument("--prompt", help="Raw prompt text to submit to ChatGPT")
    gpt_p.add_argument("--company", help="Target company name for strategic job evaluation")
    gpt_p.add_argument("--title", help="Target job title for strategic job evaluation")
    gpt_p.add_argument("--jd", help="Target whole job description text or file path")
    gpt_p.add_argument("--location", default="Remote", help="Job location (default: Remote)")
    gpt_p.add_argument("--salary", default="", help="Stated compensation or hourly rate info")
    gpt_p.add_argument("--url", default="", help="Target job posting URL")

    pitch_p = subparsers.add_parser("generate-pitch", help="Ask ChatGPT to generate a 3-sentence application pitch for a target role")
    pitch_p.add_argument("--company", required=True, help="Target company name")
    pitch_p.add_argument("--title", required=True, help="Target job title")
    pitch_p.add_argument("--jd", help="Optional job description text")
    pitch_p.add_argument("--skills", help="Comma-separated matched technical skills")

    # Claude Direct Tailoring Subparser
    tc_p = subparsers.add_parser("tailor-claude", help="Programmatically tailor resume with Claude Sonnet 3.5 and compile to 1-page PDF")
    tc_p.add_argument("--company", help="Target company name")
    tc_p.add_argument("--job-id", help="Target job ID in database")

    # Agent Dispatch Tracking Subparsers
    rec_disp_p = subparsers.add_parser("record-dispatch", help="Track agent dispatch and conversation ID for a company")
    rec_disp_p.add_argument("--company", required=True, help="Target company name")
    rec_disp_p.add_argument("--convo", required=True, help="AGY or chat conversation ID")
    rec_disp_p.add_argument("--agent", required=True, help="Agent role / type")
    rec_disp_p.add_argument("--job-id", help="Optional job ID")
    rec_disp_p.add_argument("--role", help="Optional role title")
    rec_disp_p.add_argument("--status", default="ACTIVE", help="Dispatch status")
    rec_disp_p.add_argument("--notes", help="Dispatch notes or outcomes")

    list_disp_p = subparsers.add_parser("list-dispatches", help="List previous agent dispatches by company or across all companies")
    list_disp_p.add_argument("--company", help="Optional company filter")
    list_disp_p.add_argument("--limit", type=int, default=20, help="Max records to show")

    del_p = subparsers.add_parser("delegate", help="Delegate single job application to autonomous AGY worker agent with full context and dangerously-skip-permissions")
    del_p.add_argument("--job-id", required=True, help="Job ID from database")
    del_p.add_argument("--submit", action="store_true", help="Submit directly (defaults to staging/review)")
    del_p.add_argument("--sync", action="store_true", help="Wait synchronously for AGY agent completion")
    del_p.add_argument("--convo", help="Optional conversation ID to resume")

    del_batch_p = subparsers.add_parser("delegate-batch", help="Delegate batch of jobs to autonomous AGY worker agents")
    del_batch_p.add_argument("--status", default="EVALUATED", help="Job status to filter by (default: EVALUATED)")
    del_batch_p.add_argument("--limit", type=int, default=5, help="Max jobs to delegate (default: 5)")
    del_batch_p.add_argument("--submit", action="store_true", help="Submit directly (defaults to staging/review)")

    args = parser.parse_args()
    if not args.command:
        parser.print_help()
        sys.exit(1)

    if args.command == "init":
        cmd_init()
    elif args.command == "list-accounts":
        cmd_list_accounts(args)
    elif args.command == "switch-account":
        cmd_switch_account(args)
    elif args.command == "consult-chatgpt":
        cmd_consult_chatgpt(args)
    elif args.command == "generate-pitch":
        cmd_generate_pitch(args)
    elif args.command == "list-procedures":
        cmd_list_procedures(args)
    elif args.command == "show-procedure":
        cmd_show_procedure(args)
    elif args.command == "record-procedure":
        cmd_record_procedure(args)
    elif args.command == "find":
        cmd_find(args)
    elif args.command == "find-remote":
        cmd_find_remote(args)
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
    elif args.command == "apply-barclays":
        cmd_apply_barclays(args)
    elif args.command == "apply-ashby":
        cmd_apply_ashby(args)
    elif args.command == "apply-greenhouse":
        cmd_apply_greenhouse(args)
    elif args.command == "apply-lever":
        cmd_apply_lever(args)
    elif args.command == "apply-remote":
        cmd_apply_remote(args)
    elif args.command == "apply-jazzhr":
        cmd_apply_jazzhr(args)
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
    elif args.command == "find-naukri":
        from engine.naukri_scraper import run_naukri_pipeline
        run_naukri_pipeline(profile_id=args.profile)
    elif args.command == "daily":
        cmd_daily(args)
    elif args.command == "watch-submissions":
        cmd_watch_submissions(args)
    elif args.command == "check-emails":
        cmd_check_emails(args)
    elif args.command == "check-profile":
        cmd_check_profile()
    elif args.command == "tailor-claude":
        cmd_tailor_claude(args)
    elif args.command == "record-dispatch":
        cmd_record_dispatch(args)
    elif args.command == "list-dispatches":
        cmd_list_dispatches(args)
    elif args.command == "delegate":
        cmd_delegate(args)
    elif args.command == "delegate-batch":
        cmd_delegate_batch(args)
    elif args.command == "prime-chatgpt":
        from engine.chatgpt_consultant import prime_chatgpt_with_master_dossier
        res = prime_chatgpt_with_master_dossier(force=args.force, profile_id=args.profile)
        print(f"[+] Priming Result: {res}")

if __name__ == "__main__":
    main()
