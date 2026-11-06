import sqlite3
import json
import hashlib
from datetime import datetime
from pathlib import Path
from typing import Dict, Any, List, Optional
from engine.config import DB_PATH, TEXT_SUMMARY_PATH

def get_db_connection() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    conn = get_db_connection()
    cursor = conn.cursor()

    cursor.executescript("""
    CREATE TABLE IF NOT EXISTS jobs (
        job_id TEXT PRIMARY KEY,
        canonical_hash TEXT UNIQUE,
        company TEXT NOT NULL,
        title TEXT NOT NULL,
        location TEXT,
        url TEXT NOT NULL,
        source TEXT NOT NULL,
        company_tier TEXT DEFAULT 'TIER_2',
        match_score INTEGER DEFAULT 0,
        fit_verdict TEXT DEFAULT 'PENDING',
        priority_level TEXT DEFAULT 'NORMAL',
        status TEXT DEFAULT 'DISCOVERED',
        raw_jd_path TEXT,
        tailored_resume_dir TEXT,
        referral_invite_text TEXT,
        referral_pitch_text TEXT,
        applied_at TEXT,
        notes TEXT,
        created_at TEXT,
        updated_at TEXT
    );

    CREATE TABLE IF NOT EXISTS application_logs (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        job_id TEXT NOT NULL,
        action TEXT NOT NULL,
        details TEXT,
        timestamp TEXT,
        FOREIGN KEY(job_id) REFERENCES jobs(job_id)
    );

    CREATE INDEX IF NOT EXISTS idx_jobs_status ON jobs(status);
    CREATE INDEX IF NOT EXISTS idx_jobs_company_tier ON jobs(company_tier);
    CREATE INDEX IF NOT EXISTS idx_jobs_canonical_hash ON jobs(canonical_hash);
    """)

    conn.commit()
    conn.close()

def generate_canonical_hash(company: str, title: str, url: str) -> str:
    norm = f"{company.strip().lower()}:{title.strip().lower()}:{url.strip().lower()}"
    return hashlib.sha256(norm.encode("utf-8")).hexdigest()

def is_job_seen(canonical_hash: str) -> bool:
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT 1 FROM jobs WHERE canonical_hash = ?", (canonical_hash,))
    row = cursor.fetchone()
    conn.close()
    return row is not None

def insert_job(job: Dict[str, Any]) -> bool:
    """Inserts a newly discovered job if not already present. Returns True if inserted."""
    canonical_hash = job.get("canonical_hash") or generate_canonical_hash(
        job["company"], job["title"], job["url"]
    )
    if is_job_seen(canonical_hash):
        return False

    now = datetime.now().isoformat()
    conn = get_db_connection()
    cursor = conn.cursor()

    cursor.execute("""
    INSERT OR IGNORE INTO jobs (
        job_id, canonical_hash, company, title, location, url, source,
        company_tier, match_score, fit_verdict, priority_level, status,
        raw_jd_path, tailored_resume_dir, referral_invite_text, referral_pitch_text,
        applied_at, notes, created_at, updated_at
    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        job["job_id"],
        canonical_hash,
        job["company"],
        job["title"],
        job.get("location", ""),
        job["url"],
        job.get("source", "unknown"),
        job.get("company_tier", "TIER_2"),
        job.get("match_score", 0),
        job.get("fit_verdict", "PENDING"),
        job.get("priority_level", "NORMAL"),
        job.get("status", "DISCOVERED"),
        job.get("raw_jd_path", ""),
        job.get("tailored_resume_dir", ""),
        job.get("referral_invite_text", ""),
        job.get("referral_pitch_text", ""),
        None,
        job.get("notes", ""),
        now,
        now,
    ))

    cursor.execute("""
    INSERT INTO application_logs (job_id, action, details, timestamp)
    VALUES (?, 'DISCOVERED', ?, ?)
    """, (job["job_id"], f"Job found from {job.get('source')}", now))

    conn.commit()
    conn.close()
    update_text_summary()
    return True

def update_job_status(job_id: str, status: str, details: Optional[Dict[str, Any]] = None):
    now = datetime.now().isoformat()
    conn = get_db_connection()
    cursor = conn.cursor()

    fields = ["status = ?", "updated_at = ?"]
    values = [status, now]

    if details:
        for k, v in details.items():
            fields.append(f"{k} = ?")
            values.append(v)

    values.append(job_id)
    sql = f"UPDATE jobs SET {', '.join(fields)} WHERE job_id = ?"
    cursor.execute(sql, values)

    cursor.execute("""
    INSERT INTO application_logs (job_id, action, details, timestamp)
    VALUES (?, ?, ?, ?)
    """, (job_id, status, json.dumps(details or {}), now))

    conn.commit()
    conn.close()
    update_text_summary()

def get_jobs_by_status(status: str) -> List[sqlite3.Row]:
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM jobs WHERE status = ? ORDER BY created_at DESC", (status,))
    rows = cursor.fetchall()
    conn.close()
    return rows

def get_job_by_id(job_id: str) -> Optional[sqlite3.Row]:
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM jobs WHERE job_id = ?", (job_id,))
    row = cursor.fetchone()
    conn.close()
    return row

def get_all_jobs() -> List[sqlite3.Row]:
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM jobs ORDER BY created_at DESC")
    rows = cursor.fetchall()
    conn.close()
    return rows

def update_text_summary():
    """Maintains data/jobs_found_and_applied.txt for instant human inspection."""
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT * FROM jobs
        ORDER BY CASE status
            WHEN 'APPLIED' THEN 1
            WHEN 'STAGED_FOR_REVIEW' THEN 2
            WHEN 'TAILORED' THEN 3
            WHEN 'EVALUATED' THEN 4
            ELSE 5
        END, company_tier, created_at DESC
    """)
    rows = cursor.fetchall()
    conn.close()

    lines = []
    lines.append("=" * 80)
    lines.append(f"JOB FINDER & APPLIER TRACKER SUMMARY — {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    lines.append("=" * 80)
    lines.append("")

    statuses = {}
    for r in rows:
        st = r["status"]
        statuses.setdefault(st, []).append(r)

    for st, jobs in statuses.items():
        lines.append(f"### STATUS: {st} (Count: {len(jobs)})")
        lines.append("-" * 80)
        for j in jobs:
            t = f"[{j['company_tier']}] {j['company']} — {j['title']}"
            lines.append(f"• ID: {j['job_id']}")
            lines.append(f"  Company & Role: {t}")
            lines.append(f"  URL: {j['url']}")
            lines.append(f"  Match Score: {j['match_score']}% | Priority: {j['priority_level']}")
            if j['tailored_resume_dir']:
                lines.append(f"  Tailored Resume: {j['tailored_resume_dir']}")
            if j['referral_invite_text']:
                lines.append(f"  Referral Draft: Ready (Invite & Pitch available)")
            if j['applied_at']:
                lines.append(f"  Applied At: {j['applied_at']}")
            lines.append("")
        lines.append("")

    TEXT_SUMMARY_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(TEXT_SUMMARY_PATH, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))
