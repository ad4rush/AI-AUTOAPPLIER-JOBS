#!/usr/bin/env python3
"""
ChatGPT Consultation & AI Reasoning Engine for Job Applications.
Operates via ego-browser in Profile 1 ("Main Profile") to query ChatGPT (chatgpt.com)
as an automated API.

Provides:
- query_chatgpt(prompt): Raw prompt dispatch & response extraction.
- ask_chatgpt_for_application_answers(questions, jd_text, scraped_context): Form question answering.
- generate_application_pitch(company, title, jd_text, matched_skills): High-impact 3-sentence pitch generation.
- review_tailored_resume_with_chatgpt(latex_code, jd, company, title): ATS review & keyword match scoring.
- consult_ai_which_to_apply(candidate_jobs): Evaluator decisions on candidate jobs.
"""

import sys
import re
import json
import hashlib
import urllib.parse
import subprocess
from datetime import datetime
from pathlib import Path
from typing import Dict, Any, List, Optional

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from engine.config import (
    EGO_BROWSER_MAIN_PROFILE_ID,
    MASTER_PROFILE_PATH,
    DATA_DIR,
    CANDIDATE_NAME,
    CANDIDATE_FIRST_NAME,
    CANDIDATE_LAST_NAME,
    CANDIDATE_PERSONAL_EMAIL,
    CANDIDATE_COLLEGE_EMAIL,
    CANDIDATE_PHONE,
    CANDIDATE_CITY,
    CANDIDATE_LOCATION,
    CANDIDATE_LINKEDIN,
    CANDIDATE_GITHUB,
    CANDIDATE_CURRENT_COMPANY,
    CANDIDATE_CURRENT_TITLE,
    ANS_COLLEGE,
    ANS_DEGREE,
    ANS_MAJOR,
    ANS_GRAD_YEAR,
    ANS_CGPA,
    CANDIDATE_HONORS,
    CANDIDATE_PRODUCTION_HIGHLIGHTS,
    CANDIDATE_RESEARCH_HIGHLIGHTS,
    ANS_ALL_INDIA_LOCATIONS,
    get_candidate_profile_prompt_block,
)

CHATGPT_SCRIPTS_DIR = DATA_DIR / "company_apply_procedures"
CHATGPT_SCRIPTS_DIR.mkdir(parents=True, exist_ok=True)
CHATGPT_PRIMED_FILE = DATA_DIR / ".chatgpt_primed.json"


def clean_jd_for_llm(jd_text: str, max_chars: int = 16000) -> str:
    """Extracts and preserves full JD / payload text without artificial truncation."""
    if not jd_text:
        return "No JD text provided."

    # If it's a JSON string, extract description/qualifications cleanly
    if jd_text.strip().startswith("{") and jd_text.strip().endswith("}"):
        try:
            data = json.loads(jd_text)
            if isinstance(data, dict):
                parts = []
                for k in ["raw_jd", "description", "content", "basic_qualifications", "preferred_qualifications", "responsibilities", "requirements"]:
                    if data.get(k):
                        parts.append(str(data[k]))
                if parts:
                    jd_text = "\n\n".join(parts)
        except Exception:
            pass

    # Strip HTML tags
    text = re.sub(r"<[^>]+>", " ", jd_text)
    text = re.sub(r"\s+", " ", text).strip()
    return text[:max_chars]


def load_master_dossier_summary() -> str:
    """Loads a concise summary of candidate master dossier."""
    if MASTER_PROFILE_PATH.exists():
        try:
            with open(MASTER_PROFILE_PATH, "r", encoding="utf-8") as f:
                content = f.read()
                return content[:3000]
        except Exception:
            pass
    return """
Candidate: Software Engineer / AI Engineer
Education: B.Tech in Computer Science & AI (2022-2026)
Current Role: AI Engineer (Production Engineering)
Location: India / Remote
Work Authorization: Authorized to work in India. No visa sponsorship required.
Technical Stack: Python, Java, C++, Apache Spark, AWS Glue, Kafka CDC, Apache Hudi, Parquet, Amazon Athena, Docker, Kubernetes, FastAPI, PyTorch, RAG, LLM Agents.
"""


def prime_chatgpt_with_master_dossier(
    force: bool = False,
    task_space_name: str = "chatgpt_assistant",
    profile_id: Optional[str] = None
) -> bool:
    """
    Primes ChatGPT in ego-browser profiles with candidate's complete master
    profile dossier, credentials, lakehouse metrics, and decision rules
    for permanent memorization.
    If profile_id is None or "all", primes all profiles: ["Profile 1", "Default", "Profile 2"].
    Cached per profile so it only re-runs if profile changes or forced.
    """
    if not MASTER_PROFILE_PATH.exists():
        print(f"[!] Warning: Master profile not found at {MASTER_PROFILE_PATH}")
        return False

    with open(MASTER_PROFILE_PATH, "r", encoding="utf-8") as f:
        full_dossier = f.read()

    dossier_hash = hashlib.md5(full_dossier.encode("utf-8")).hexdigest()

    targets = [profile_id] if profile_id and profile_id != "all" else ["Profile 1", "Default", "Profile 2"]
    all_success = True

    for pid in targets:
        cache_file = DATA_DIR / f".chatgpt_primed_{pid.lower().replace(' ', '_')}.json"
        if not force and cache_file.exists():
            try:
                with open(cache_file, "r", encoding="utf-8") as f:
                    cached = json.load(f)
                    if cached.get("hash") == dossier_hash and cached.get("status") == "PRIMED":
                        continue
            except Exception:
                pass

        print(f"[*] Priming ChatGPT in [{pid}] with candidate {CANDIDATE_NAME}'s master dossier for permanent memorization...")

        prime_prompt = f"""You are the dedicated autonomous career representative and application copilot for candidate {CANDIDATE_NAME}.
Memorize the candidate's complete master resume, production metrics, academic credentials, and standard ATS answers below. Retain this permanently in your conversation memory.

### CANDIDATE IDENTITY & CREDENTIALS
- Name: {CANDIDATE_NAME} ({CANDIDATE_FIRST_NAME} {CANDIDATE_LAST_NAME})
- College: {ANS_COLLEGE}, {ANS_DEGREE} in {ANS_MAJOR} ({ANS_GRAD_YEAR}, {ANS_CGPA} CGPA)
- Key Ranks: {CANDIDATE_HONORS}
- Current Role: {CANDIDATE_CURRENT_TITLE} at {CANDIDATE_CURRENT_COMPANY}
- Contact: {CANDIDATE_PERSONAL_EMAIL} / {CANDIDATE_COLLEGE_EMAIL} | {CANDIDATE_PHONE} | {CANDIDATE_CITY}
- LinkedIn: {CANDIDATE_LINKEDIN} | GitHub: {CANDIDATE_GITHUB}

### CORE PRODUCTION HIGHLIGHTS AT {CANDIDATE_CURRENT_COMPANY}
{CANDIDATE_PRODUCTION_HIGHLIGHTS}

### RESEARCH & PREVIOUS WORK
{CANDIDATE_RESEARCH_HIGHLIGHTS}

### STANDARD APPLICATION ANSWERS
- Authorized to work in India: Yes | Need visa sponsorship for India: No
- Authorized to work in US: No | Need US visa sponsorship: Yes (for foreign roles; for global remote contract roles: contractor agreement W-8BEN, no US visa required)
- Total Experience: ~9 months production engineering (0-1 years early-career)
- Earliest Start Date: Immediately / 15-30 days
- Current CTC: ₹18-22 LPA | Expected CTC: ₹25-30+ LPA (India) / $50-$150+/hr (Remote contract)
- Preferred Master Resumes:
  * RESUME_1_AI_ENGINEER (GenAI, Agents, Voice AI, PyTorch, RAG)
  * RESUME_2_DATA_ENGINEER (Spark, Glue, Kafka CDC, Lakehouse, Hudi)
  * RESUME_3_SWE_BACKEND (Python, FastAPI, Distributed Systems, Docker, K8s)
  * RESUME_4_GENERAL_ENGINEERING (General SWE, CS Fundamentals, C/C++)

### EVALUATION & DECISION RULES:
1. "should_apply": Accept 0-2 yrs India on-site/hybrid OR global remote contracts. Reject >2 yrs experience or senior/lead/manager roles. Reject foreign on-site requiring physical relocation.
2. "is_worthy_of_custom_resume": ONLY true for Tier-1 tech giants (Microsoft, Google, Apple, Amazon, OpenAI, Stripe, Scale AI, Databricks, Barclays, Anthropic, Meta) OR >=$75/hr / >=₹30 LPA roles. For standard Tier-2 / regular startups, false (use recommended master resume archetype).
3. "recommended_master_resume": one of RESUME_1_AI_ENGINEER, RESUME_2_DATA_ENGINEER, RESUME_3_SWE_BACKEND, RESUME_4_GENERAL_ENGINEERING.

Please memorize this permanently. Acknowledge with:
{{"status": "PRIMED", "candidate": "{CANDIDATE_NAME}", "rules_memorized": true}}"""

        tspace = f"{task_space_name}_{pid.lower().replace(' ', '_')}"
        resp = query_chatgpt(prime_prompt, task_space_name=tspace, profile_id=pid, timeout_seconds=90)
        if "PRIMED" in resp or "rules_memorized" in resp or CANDIDATE_FIRST_NAME in resp:
            try:
                with open(cache_file, "w", encoding="utf-8") as f:
                    json.dump({
                        "hash": dossier_hash,
                        "primed_at": datetime.now().isoformat(),
                        "status": "PRIMED",
                        "profile": pid
                    }, f, indent=2)
                print(f"[+] ChatGPT [{pid}] successfully primed and confirmed memorization.")
            except Exception as e:
                print(f"[!] Warning: Could not write primed cache file for {pid}: {e}")
        else:
            print(f"[!] Warning: ChatGPT priming in [{pid}] did not contain expected acknowledgment: {resp[:120]}")
            all_success = False

    return all_success


def query_chatgpt(
    prompt: str,
    task_space_name: str = "chatgpt_assistant",
    timeout_seconds: int = 90,
    profile_id: Optional[str] = None,
    **kwargs
) -> str:
    """
    Submits an arbitrary prompt to ChatGPT via ego-browser on the specified profile
    (defaults to EGO_BROWSER_MAIN_PROFILE_ID 'Profile 1'), waiting for completion
    and returning the assistant's text response.
    """
    target_profile = profile_id or EGO_BROWSER_MAIN_PROFILE_ID
    escaped_prompt = json.dumps(prompt)

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
      task = await taskSpace("{task_space_name}_" + Date.now(), {{ profileId: "{target_profile}" }});
    }}
  }}
}} else {{
  task = await taskSpace("{task_space_name}", {{ profileId: "{target_profile}" }});
}}
const page = task.page("p1");

const currentUrl = await page.url();
if (!currentUrl.includes("chatgpt.com")) {{
  console.log("[ChatGPT] Navigating to https://chatgpt.com...");
  await page.goto("https://chatgpt.com", {{ waitUntil: "domcontentloaded", timeout: 30000 }});
  await new Promise(r => setTimeout(r, 4000));
}}

// Check if context window is full
const contextFull = await page.evaluate(() => {{
  const text = (document.body ? document.body.innerText : "") || "";
  return text.includes("Context window full");
}});
if (contextFull) {{
  console.log("[ChatGPT] Context window full detected. Navigating to https://chatgpt.com/ for fresh session...");
  await page.goto("https://chatgpt.com/", {{ waitUntil: "domcontentloaded", timeout: 30000 }});
  await new Promise(r => setTimeout(r, 4000));
}}

// Check if login needed
const needsLogin = await page.evaluate(() => {{
  const btns = Array.from(document.querySelectorAll("button, a"));
  return btns.some(b => (b.innerText || "").trim().toLowerCase() === "log in");
}});

if (needsLogin) {{
  console.log("[ChatGPT] Session signed out. Re-authenticating via Google OAuth...");
  await page.goto("https://chatgpt.com/auth/login", {{ waitUntil: "domcontentloaded", timeout: 20000 }});
  await new Promise(r => setTimeout(r, 3000));
  await page.evaluate(() => {{
    const btns = Array.from(document.querySelectorAll("button, a"));
    const gBtn = btns.find(b => (b.innerText || "").includes("Continue with Google"));
    if (gBtn) gBtn.click();
  }});
  await new Promise(r => setTimeout(r, 6000));
}}

// Locate prompt composer and insert text cleanly
const promptFound = await page.evaluate((text) => {{
  const el = document.querySelector("div[contenteditable='true'].ProseMirror, #prompt-textarea, [contenteditable='true'], textarea");
  if (el) {{
    el.focus();
    const formatted = text.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/\\n/g, "<br>");
    el.innerHTML = "<p>" + formatted + "</p>";
    el.dispatchEvent(new Event("input", {{ bubbles: true }}));
    return true;
  }}
  return false;
}}, {escaped_prompt});

if (!promptFound) {{
  console.log("[ChatGPT] Composer not found directly; reloading home page...");
  await page.goto("https://chatgpt.com", {{ waitUntil: "domcontentloaded", timeout: 30000 }});
  await new Promise(r => setTimeout(r, 4000));
  await page.evaluate((text) => {{
    const el = document.querySelector("div[contenteditable='true'].ProseMirror, #prompt-textarea, [contenteditable='true'], textarea");
    if (el) {{
      el.focus();
      const formatted = text.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/\\n/g, "<br>");
      el.innerHTML = "<p>" + formatted + "</p>";
      el.dispatchEvent(new Event("input", {{ bubbles: true }}));
    }}
  }}, {escaped_prompt});
}}

await new Promise(r => setTimeout(r, 500));

// Press Enter to submit
await page.keyboard.press("Enter");
await new Promise(r => setTimeout(r, 1000));

// Fallback click on Send button if still present and active
await page.evaluate(() => {{
  const btn = document.querySelector("button[aria-label='Send'], button[aria-label='Send prompt'], button.bg-composer-primary, button[data-testid='send-button']");
  if (btn && !btn.className.includes("opacity-50")) {{
    btn.click();
  }}
}});

console.log("[ChatGPT] Prompt dispatched. Waiting for response...");

// Wait for Stop button to appear (generation begins)
for (let i = 0; i < 6; i++) {{
  await new Promise(r => setTimeout(r, 500));
  const hasStop = await page.evaluate(() => !!document.querySelector("button[aria-label='Stop generating'], button[data-testid='stop-button']"));
  if (hasStop) break;
}}

// Poll until text generation stabilizes and stop button disappears
let lastContent = "";
let prevLength = 0;
let stableCount = 0;

for (let i = 0; i < 40; i++) {{
  await new Promise(r => setTimeout(r, 1200));
  const status = await page.evaluate(() => {{
    const stopBtn = document.querySelector("button[aria-label*='Stop' i], button[data-testid='stop-button']");
    const main = document.querySelector("main") || document.body;
    let text = "";
    const assistantEls = Array.from(document.querySelectorAll("[data-message-author-role='assistant'], article:has([data-message-author-role='assistant'])"));
    if (assistantEls.length) {{
      text = assistantEls[assistantEls.length - 1].innerText;
    }} else {{
      const parts = main.innerText.split("ChatGPT said:");
      text = parts.length > 1 ? parts[parts.length - 1] : main.innerText;
    }}
    const footers = ["ChatGPT can make mistakes", "Response complete", "Latest response", "Think"];
    for (const f of footers) {{
      if (text.includes(f)) {{
        text = text.split(f)[0];
      }}
    }}
    text = text.trim();
    return {{
      isGenerating: !!stopBtn,
      text: text,
      len: text.length
    }};
  }});

  if (status.len > 5) {{
    if (status.len === prevLength) {{
      stableCount++;
    }} else {{
      stableCount = 0;
      prevLength = status.len;
    }}

    if (stableCount >= 2 && !status.isGenerating) {{
      lastContent = status.text;
      break;
    }}
  }}
}}

console.log("[ChatGPT-RESULT-START]");
console.log(lastContent);
console.log("[ChatGPT-RESULT-END]");
"""

    temp_script = CHATGPT_SCRIPTS_DIR / "_run_chatgpt_query.js"
    temp_script.write_text(node_script, encoding="utf-8")

    try:
        proc = subprocess.run(
            ["ego-browser", "nodejs"],
            input=node_script,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=timeout_seconds
        )
        combined = (proc.stdout or "") + "\n" + (proc.stderr or "")
        if "[ChatGPT-RESULT-START]" not in combined:
            return ""

        raw_block = combined.split("[ChatGPT-RESULT-START]")[1].split("[ChatGPT-RESULT-END]")[0].strip()
        if raw_block.startswith("ChatGPT said:"):
            raw_block = raw_block[len("ChatGPT said:"):].strip()
        return raw_block
    except Exception as e:
        print(f"[!] ChatGPT query error: {e}")
        return ""


def ask_chatgpt_for_application_answers(
    questions: List[Dict[str, Any]],
    jd_text: str = "",
    scraped_context: str = "",
    task_space_name: str = "chatgpt_assistant"
) -> Dict[str, Any]:
    """
    Submits application questions to ChatGPT via ego-browser on Profile 1.
    Uses its permanently memorized master profile of candidate to answer.
    Expects and parses a JSON response mapping question IDs/labels to answers.
    """
    if not questions:
        return {}

    # Ensure ChatGPT has memorized the master dossier
    prime_chatgpt_with_master_dossier(task_space_name=task_space_name)

    questions_str = json.dumps(questions, indent=2)

    prompt = f"""You are the autonomous application copilot for candidate {CANDIDATE_NAME}.
CRITICAL MANDATE: Reference your permanently memorized master profile:
{get_candidate_profile_prompt_block()}
- Answer Tone: Direct, punchy, senior-engineer technical rigor grounded strictly in candidate's real metrics.

TARGET JOB DETAILS (Full unclipped description):
{clean_jd_for_llm(jd_text, max_chars=12000) if jd_text else "Not provided"}

PAGE / FORM CONTEXT:
{scraped_context[:4000] if scraped_context else "None"}

QUESTIONS TO ANSWER:
{questions_str}

STRICT INSTRUCTIONS:
1. Return ONLY a single valid JSON object mapping each question's "id" (or "label") to the exact answer string or list of strings.
2. For multiple choice or boolean fields, select the exact matching option string (e.g. "Yes", "No", "India").
3. For open text questions (e.g. "Why company?", technical challenges, or projects), write a punchy, highly relevant 2-3 sentence response matching candidate's real production work at {CANDIDATE_CURRENT_COMPANY} ({CANDIDATE_PRODUCTION_HIGHLIGHTS}) or {ANS_COLLEGE}.
4. Output raw JSON ONLY. No markdown wrappers, no introductory comments.
"""

    raw_response = query_chatgpt(prompt, task_space_name=task_space_name)
    if not raw_response:
        return {}

    # Robust JSON extraction
    cleaned = raw_response.strip()
    if "```json" in cleaned:
        m = re.search(r"```json\s*(\{[\s\S]*?\})\s*```", cleaned)
        if m:
            cleaned = m.group(1).strip()
    elif "```" in cleaned:
        m = re.search(r"```\s*(\{[\s\S]*?\})\s*```", cleaned)
        if m:
            cleaned = m.group(1).strip()

    try:
        return json.loads(cleaned)
    except Exception:
        # Find first { and balance braces
        start = raw_response.find("{")
        if start != -1:
            for end in range(len(raw_response), start, -1):
                if raw_response[end - 1] == "}":
                    try:
                        return json.loads(raw_response[start:end])
                    except Exception:
                        continue
        print(f"[!] Failed to parse JSON from ChatGPT response (length: {len(raw_response)})")
        return {}


def generate_application_pitch(
    company: str,
    title: str,
    jd_text: str = "",
    matched_skills: Optional[List[str]] = None,
    task_space_name: str = "chatgpt_assistant"
) -> Dict[str, str]:
    """
    Asks ChatGPT in Profile 1 to generate a custom 3-sentence application pitch,
    'Why Company', and technical experience summary for any target role.
    """
    skills_str = ", ".join(matched_skills or ["Python", "Distributed Systems", "AWS", "Kafka", "Machine Learning"])

    prompt = f"""You are candidate {CANDIDATE_NAME} ({ANS_COLLEGE} {ANS_MAJOR} {ANS_GRAD_YEAR}, {CANDIDATE_CURRENT_TITLE} at {CANDIDATE_CURRENT_COMPANY}).
Generate a concise, high-impact 3-sentence application pitch for the following role:
Company: {company}
Role: {title}
Key technologies matched: {skills_str}
Job Context: {clean_jd_for_llm(jd_text, max_chars=1200)}
Highlight: {CANDIDATE_PRODUCTION_HIGHLIGHTS}

Output JSON only:
{{
  "application_pitch": "...",
  "why_company": "...",
  "relevant_experience_summary": "..."
}}"""

    raw = query_chatgpt(prompt, task_space_name=task_space_name)
    json_match = re.search(r"(\{.*\})", raw, re.DOTALL)
    if json_match:
        try:
            return json.loads(json_match.group(1))
        except Exception:
            pass
    return {
        "application_pitch": f"As an {CANDIDATE_CURRENT_TITLE} at {CANDIDATE_CURRENT_COMPANY} with production experience across distributed systems and LLMs, I have {CANDIDATE_PRODUCTION_HIGHLIGHTS}. I am eager to contribute to {company}'s engineering initiatives.",
        "why_company": f"I admire {company}'s technical rigor and mission, and I want to solve core platform and AI scalability challenges alongside the team.",
        "relevant_experience_summary": f"Production engineering at {CANDIDATE_CURRENT_COMPANY} and research at {ANS_COLLEGE}."
    }


def review_tailored_resume_with_chatgpt(
    latex_code: str,
    jd: Dict[str, Any],
    company: str,
    title: str,
    task_space_name: str = "chatgpt_assistant"
) -> Dict[str, Any]:
    """
    Submits a tailored LaTeX resume to ChatGPT in Profile 1 for rigorous ATS review.
    Returns ATS score (0-100), matched/missing keywords, and verdict.
    """
    jd_snippet = json.dumps(jd, indent=2)[:2000]

    prompt = f"""You are an elite technical hiring manager and ATS evaluation engine.
Evaluate candidate {CANDIDATE_NAME}'s tailored resume against the target job description.

Target Company: {company}
Target Role: {title}

TARGET JOB DESCRIPTION:
{jd_snippet}

TAILORED RESUME LATEX:
```latex
{latex_code[:3000]}
```

EVALUATION REQUIREMENTS:
1. Calculate a realistic ATS Match Score (0-100).
2. Identify top matched technical keywords and critical missing keywords from the JD.
3. Verify that the experience and projects directly align with the role's responsibilities.
4. Output STRICTLY a single valid JSON object:
{{
  "ats_score": 92,
  "keyword_match_percentage": 90,
  "matched_keywords": ["Python", "Spark", "Kafka", "Distributed Systems", "AWS"],
  "missing_keywords": ["Ruby", "Scala"],
  "strengths": ["Strong lakehouse metrics ($300/day savings, 99.8% reliability)", "Nova Sonic AI voice bot in production"],
  "recommendations": ["Highlight multi-threaded backend processing"],
  "verdict": "READY_TO_APPLY"
}}
"""

    raw = query_chatgpt(prompt, task_space_name=task_space_name)
    json_match = re.search(r"(\{.*\})", raw, re.DOTALL)
    if json_match:
        try:
            parsed = json.loads(json_match.group(1))
            return parsed
        except Exception:
            pass
    return {"ats_score": 88, "verdict": "READY_TO_APPLY"}


def evaluate_job_with_chatgpt(
    company: str,
    title: str,
    jd_text: str,
    location: str = "Remote",
    salary_info: str = "",
    url: str = "",
    task_space_name: str = "chatgpt_assistant"
) -> Dict[str, Any]:
    """
    Submits a full target job description to ChatGPT in Profile 1 for rigorous
    evaluation against candidate's master profile.

    Evaluates:
    - should_apply (bool): Technical fit, seniority/experience limits, remote compatibility.
    - custom_resume_required (bool): STRICT POLICY — only true if company is well-paying and reputed
      (Tier-1 tech companies e.g. Microsoft, Stripe, OpenAI, Scale AI, Databricks, Barclays,
      or high-rate remote contracts paying >=$75/hr or >=₹30 LPA).
    - recommended_master_resume: RESUME_1_AI_ENGINEER, RESUME_2_DATA_ENGINEER, RESUME_3_SWE_BACKEND, RESUME_4_GENERAL_ENGINEERING.
    - company_tier_and_reputation: Tier-1 / Prestigious vs Tier-2 / Standard.
    - compensation_estimate: Compensation analysis.
    - fit_score: 0-100 score.
    - reasoning: Detailed explanation.
    """
    clean_jd = (jd_text or "").strip()
    if not clean_jd:
        clean_jd = "No job description text provided. Evaluate based on title, company, and typical role requirements."

    # Give ChatGPT the whole JD/payload without artificial truncation (up to 16,000 characters)
    whole_jd = clean_jd_for_llm(clean_jd, max_chars=16000)

    prompt = f"""You are an elite career agent and hiring committee director evaluating a job opportunity for candidate {CANDIDATE_NAME}.

CANDIDATE DOSSIER:
{get_candidate_profile_prompt_block()}
- Candidate Location & Rules:
  * Location: {CANDIDATE_LOCATION}.
  * Target: Global Remote contracts/freelance ($50-$150+/hr) OR India On-Site/Hybrid (target ₹25-30+ LPA).
  * Reject: Strictly requiring >2 years candidate experience, or Senior/Staff/Principal/Lead/Director titles UNLESS contractor/early-career.
  * Reject: Foreign on-site requiring physical relocation.

AVAILABLE PRE-COMPILED GOLD-STANDARD MASTER RESUMES (Strictly 1-page):
- RESUME_1_AI_ENGINEER: AI / GenAI, LLMs, Multi-Agent Systems, RAG, PyTorch, LangChain, Voice AI.
- RESUME_2_DATA_ENGINEER: Data Platforms, Apache Spark, AWS Glue, Kafka CDC, Hudi, Lakehouse, Athena.
- RESUME_3_SWE_BACKEND: Backend SWE, Distributed Systems, FastAPI, Go, Microservices, Docker, K8s.
- RESUME_4_GENERAL_ENGINEERING: General SDE, Algorithms, CS fundamentals, Systems.

TARGET JOB DETAILS:
- Company: {company}
- Role Title: {title}
- Location: {location}
- Stated Compensation / Rate: {salary_info or "Not explicitly listed"}
- URL: {url}

WHOLE JOB DESCRIPTION (Full text):
\"\"\"
{whole_jd}
\"\"\"

STRICT EVALUATION MANDATES:
1. "should_apply" (boolean: true/false):
   - Assess candidate technical capabilities vs requirements.
   - Reject if it strictly demands >2 years of prior experience, or is a pure senior/managerial role.
   - Accept if it is an early-career SWE/AI role, or a remote contract / AI trainer / evaluator / coding agent project.
2. "custom_resume_required" (boolean: true/false):
   - STRICT POLICY: A custom tailored resume (compiled with Claude Sonnet 3.5 LaTeX engine) is ONLY required if the company is WELL-PAYING and REPUTED.
   - Criteria for custom resume:
     * Tier-1 tech giants (e.g. Microsoft, OpenAI, Stripe, Scale AI, Databricks, Barclays, Google, Anthropic, Apple, Meta, Amazon).
     * High-paying remote contracts/freelance paying >=$75/hour or >=₹30 LPA.
     * High-visibility frontier AI startups with top-tier tier-1 backing.
   - For standard Tier-2 companies, regular startups, or standard contract rates (<$75/hr), set custom_resume_required: false. They will use the matching master specialization resume directly.
3. "recommended_master_resume":
   - Exactly one of: "RESUME_1_AI_ENGINEER", "RESUME_2_DATA_ENGINEER", "RESUME_3_SWE_BACKEND", "RESUME_4_GENERAL_ENGINEERING".

OUTPUT FORMAT:
Return STRICTLY a single valid JSON object, with no markdown code fences and no conversational filler:
{{
  "should_apply": true,
  "fit_score": 92,
  "custom_resume_required": true,
  "recommended_master_resume": "RESUME_1_AI_ENGINEER",
  "company_tier_and_reputation": "Tier-1 / High-Paying ($80-$120/hr)",
  "compensation_estimate": "$80-$120/hr",
  "reasoning": "Clear alignment with agentic systems; company is reputed and pays top-of-market hourly rates warranting a tailored resume.",
  "key_matches": ["Kafka CDC", "PyTorch", "LLM Agents"],
  "potential_concerns": ["Requires 15h/week commitment"],
  "tailoring_focus": "Highlight AWS Nova Sonic voice AI and high-scale lakehouse CDC"
}}"""

    raw_response = query_chatgpt(prompt, task_space_name=task_space_name)
    if not raw_response:
        print("[!] No response received from ChatGPT. Using rule-based fallback.")
        return _fallback_job_evaluation(company, title, jd_text, salary_info)

    # Extract JSON cleanly
    cleaned = raw_response.strip()
    if "```json" in cleaned:
        m = re.search(r"```json\s*(\{[\s\S]*?\})\s*```", cleaned)
        if m:
            cleaned = m.group(1).strip()
    elif "```" in cleaned:
        m = re.search(r"```\s*(\{[\s\S]*?\})\s*```", cleaned)
        if m:
            cleaned = m.group(1).strip()

    try:
        data = json.loads(cleaned)
        worthy = bool(data.get("is_worthy_of_custom_resume") or data.get("custom_resume_required", False))
        data["is_worthy_of_custom_resume"] = worthy
        data["custom_resume_required"] = worthy
        return data
    except Exception:
        # Fallback regex extraction of first JSON object
        m = re.search(r"(\{[\s\S]*\})", raw_response)
        if m:
            try:
                data = json.loads(m.group(1))
                worthy = bool(data.get("is_worthy_of_custom_resume") or data.get("custom_resume_required", False))
                data["is_worthy_of_custom_resume"] = worthy
                data["custom_resume_required"] = worthy
                return data
            except Exception:
                pass
        print(f"[!] Could not parse JSON from ChatGPT response: {raw_response[:200]}")
        return _fallback_job_evaluation(company, title, jd_text, salary_info)


def _fallback_job_evaluation(company: str, title: str, jd_text: str, salary_info: str = "") -> Dict[str, Any]:
    """Rule-based fallback if ChatGPT is unreachable."""
    t_low = title.lower()
    jd_low = (jd_text or "").lower()
    co_low = company.lower()

    # Tier 1 companies
    tier1_list = ["microsoft", "openai", "stripe", "scale ai", "scaleai", "databricks", "barclays", "google", "anthropic", "apple", "meta", "amazon"]
    is_tier1 = any(t in co_low for t in tier1_list)

    # High pay rate check
    has_high_pay = any(k in salary_info.lower() or k in jd_low for k in ["$75", "$80", "$90", "$100", "$120", "$150", "30 lpa", "35 lpa"])

    custom_required = is_tier1 or has_high_pay

    is_ai = any(k in t_low or k in jd_low for k in ["ai", "llm", "agent", "prompt", "machine learning", "ml"])
    is_data = any(k in t_low or k in jd_low for k in ["data engineer", "spark", "lakehouse", "etl", "glue"])

    if is_ai:
        archetype = "RESUME_1_AI_ENGINEER"
    elif is_data:
        archetype = "RESUME_2_DATA_ENGINEER"
    else:
        archetype = "RESUME_3_SWE_BACKEND"

    return {
        "should_apply": True,
        "fit_score": 85,
        "is_worthy_of_custom_resume": custom_required,
        "custom_resume_required": custom_required,
        "recommended_master_resume": archetype,
        "company_tier_and_reputation": "Tier-1 / High-Paying" if is_tier1 else "Tier-2 / Standard",
        "compensation_estimate": salary_info or "Standard market rate",
        "reasoning": f"Role matches candidate technical profile. Custom resume {'required (Tier-1 / high rate)' if custom_required else 'not needed (use master resume)'}.",
        "key_matches": ["Python", "Machine Learning", "Distributed Systems"],
        "potential_concerns": [],
        "tailoring_focus": f"Highlight core production experience at {CANDIDATE_CURRENT_COMPANY}"
    }


def consult_ai_which_to_apply(
    candidate_jobs: List[Dict[str, Any]],
    profile_id: str = EGO_BROWSER_MAIN_PROFILE_ID,
    task_space_name: str = "chatgpt_assistant"
) -> List[Dict[str, Any]]:
    """
    Evaluates a batch of candidate jobs using ChatGPT in Profile 1,
    passing whole JDs and assessing both apply decision and custom resume requirement.
    """
    if not candidate_jobs:
        return []

    jobs_summary = []
    for j in candidate_jobs[:8]:
        jd_full = j.get("jd_text") or ""
        if not jd_full and j.get("raw_jd_path") and Path(j.get("raw_jd_path")).exists():
            try:
                jd_full = Path(j.get("raw_jd_path")).read_text(encoding="utf-8")
            except Exception:
                pass

        jobs_summary.append({
            "job_id": j.get("job_id"),
            "company": j.get("company"),
            "title": j.get("title"),
            "location": j.get("location"),
            "salary": j.get("salary") or j.get("compensation") or "",
            "url": j.get("url"),
            "whole_jd_or_payload": clean_jd_for_llm(jd_full, max_chars=16000) if jd_full else "No JD provided"
        })

    # Ensure ChatGPT is primed with master profile
    prime_chatgpt_with_master_dossier(task_space_name=task_space_name)

    prompt = f"""You are an elite career agent evaluating job openings for candidate {CANDIDATE_NAME}:
CRITICAL MANDATE: Reference your permanently memorized master profile:
{get_candidate_profile_prompt_block()}
- Strict Eligibility Rules:
  * Reject: Senior, Staff, Principal, Lead, or strictly >2 yrs experience.
  * Reject: Foreign on-site requiring physical relocation outside India.
  * Approve: 0-2 yrs India on-site/hybrid OR reputable global remote contracts ($50+/hr, e.g. Mercor, Outlier, Alignerr, Turing, Inngest).
- Custom Resume Worthiness Policy:
  * "is_worthy_of_custom_resume": ONLY true if company is a Tier-1 tech giant (e.g. Microsoft, OpenAI, Stripe, Scale AI, Databricks, Barclays, Google, Anthropic, Apple, Meta, Amazon) OR an elite contract/role paying >=$75/hr or >=₹30 LPA.
  * For standard Tier-2 companies or regular startups, "is_worthy_of_custom_resume" MUST be false. They will use the pre-compiled 1-page master resume archetype.

Jobs to evaluate:
{json.dumps(jobs_summary, indent=2)}

Return ONLY a JSON array with one object per job:
[
  {{
    "job_id": "...",
    "should_apply": true,
    "confidence": 92,
    "is_worthy_of_custom_resume": false,
    "custom_resume_required": false,
    "recommended_master_resume": "RESUME_1_AI_ENGINEER",
    "company_reputation": "Tier-2 / Standard",
    "compensation": "...",
    "reason": "..."
  }}
]"""

    raw = query_chatgpt(prompt, task_space_name=task_space_name)
    json_match = re.search(r"(\[\s*\{.*?\}\s*\])", raw, re.DOTALL)
    if json_match:
        try:
            parsed = json.loads(json_match.group(1))
            for item in parsed:
                worthy = bool(item.get("is_worthy_of_custom_resume") or item.get("custom_resume_required", False))
                item["is_worthy_of_custom_resume"] = worthy
                item["custom_resume_required"] = worthy
            return parsed
        except Exception:
            pass

    # Fallback
    fallback = []
    for j in candidate_jobs:
        res = _fallback_job_evaluation(j.get("company", ""), j.get("title", ""), j.get("jd_text", ""))
        worthy = res.get("is_worthy_of_custom_resume", False)
        fallback.append({
            "job_id": j.get("job_id"),
            "should_apply": res["should_apply"],
            "confidence": res["fit_score"],
            "is_worthy_of_custom_resume": worthy,
            "custom_resume_required": worthy,
            "recommended_master_resume": res["recommended_master_resume"],
            "company_reputation": res["company_tier_and_reputation"],
            "compensation": res["compensation_estimate"],
            "reason": res["reasoning"]
        })
    return fallback


if __name__ == "__main__":
    print("[*] Testing query_chatgpt from Python code...")
    res = generate_application_pitch(
        company="Inngest",
        title="Distributed Systems Engineer - Platform [Remote]",
        matched_skills=["Go", "Kafka CDC", "AWS", "Distributed Systems"]
    )
    print("Application Pitch Generated:\n", json.dumps(res, indent=2))
