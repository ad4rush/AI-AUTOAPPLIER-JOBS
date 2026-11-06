from typing import Dict, Any
from engine.config import (
    CANDIDATE_NAME,
    CANDIDATE_EMAIL,
    CANDIDATE_PHONE,
    CANDIDATE_LINKEDIN,
    CANDIDATE_GITHUB,
    CANDIDATE_CURRENT_COMPANY,
    CANDIDATE_CURRENT_TITLE
)
from engine.db import update_job_status

def generate_linkedin_connection_invite(company: str, role: str, job_id: str) -> str:
    """
    Generates a personalized LinkedIn connection invitation note.
    Strictly kept under 300 characters (LinkedIn maximum limit).
    """
    text = (
        f"Hi [Name], saw your work at {company}. I'm an AI Engineer at {CANDIDATE_CURRENT_COMPANY} "
        f"(Spark/Glue/Kafka lakehouse, AIR 252 GATE CS). I'm applying for the {role} opening "
        f"and would love to connect and learn about the team!"
    )
    if len(text) > 300:
        text = (
            f"Hi [Name], admire your work at {company}. I'm an AI Engineer at TBO.com "
            f"(Lakehouse, Nova Sonic, AIR 252 GATE). Applying for the {role} opening and "
            f"would love to connect!"
        )
    return text

def generate_referral_pitch(company: str, role: str, job_id: str, job_url: str, resume_path: str) -> str:
    """
    Generates a high-converting, professional referral request draft.
    Frictionless and ready for the contact to forward directly to the recruiter/hiring manager.
    """
    return f"""Subject: Referral Request — {role} at {company} (Adarsh Kumar Jha)

Hi [Name],

I hope you're having a great week!

I noticed that {company} is hiring for the {role} position ({job_url}), and given your experience with the team, I wanted to reach out and see if you would be open to submitting a referral for me.

A quick summary of my background that aligns directly with the team's requirements:
• Currently AI Engineer (Production Engineering) at TBO.com (Travel Boutique Online), architecting near-real-time data lakehouse pipelines handling billions of records using Apache Spark, AWS Glue, Kafka CDC (Debezium), and Apache Hudi.
• Production Reliability & Cost Engineering: Increased Glue ETL success rate from 94% to 99.8% ($300/day savings) and eliminated cross-AZ Kafka networking overhead ($5,000+/mo savings).
• GenAI in Production: Deployed low-latency conversational AI agents (AWS Nova Sonic, 600ms p95 latency) and enterprise text-to-SQL agents grounded in domain ontologies.
• Technical & Algorithmic Foundation: All India Rank 252 in GATE 2026 (CS/IT), 99.5 percentile in JEE Mains (AIR 4778), and Codeforces Specialist.

I have attached my tailored resume for this role:
Resume Path: {resume_path}

To make this completely frictionless for you, here are the details often needed for referral portals:
- Candidate Name: {CANDIDATE_NAME}
- Email: {CANDIDATE_EMAIL}
- Phone: {CANDIDATE_PHONE}
- Role: {role}
- Job ID / Link: {job_url}
- LinkedIn: {CANDIDATE_LINKEDIN}
- GitHub: {CANDIDATE_GITHUB}

Would you be comfortable referring me or sharing my profile with the hiring team? Either way, I appreciate your time and consideration!

Best regards,
{CANDIDATE_NAME}
"""

def generate_and_save_referral_drafts(job: Dict[str, Any], resume_path: str = "") -> Dict[str, str]:
    """Generates both drafts and persists them in the database."""
    job_id = job["job_id"]
    company = job["company"]
    role = job["title"]
    url = job["url"]

    invite_note = generate_linkedin_connection_invite(company, role, job_id)
    pitch_note = generate_referral_pitch(company, role, job_id, url, resume_path)

    update_job_status(job_id, "REFERRAL_DRAFTED", {
        "referral_invite_text": invite_note,
        "referral_pitch_text": pitch_note
    })

    return {
        "invite_note": invite_note,
        "pitch_note": pitch_note
    }
