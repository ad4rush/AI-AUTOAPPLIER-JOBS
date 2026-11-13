import sqlite3
import json
import hashlib
import time
from datetime import datetime
from pathlib import Path
from typing import Dict, Any, List, Optional
from engine.config import DB_PATH, TEXT_SUMMARY_PATH

_LAST_SUMMARY_TIME = 0.0

def get_db_connection(timeout: float = 30.0) -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(DB_PATH), timeout=timeout)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL;")
    conn.execute("PRAGMA synchronous=NORMAL;")
    conn.execute("PRAGMA busy_timeout=30000;")
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

    CREATE TABLE IF NOT EXISTS agent_dispatches (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        company TEXT NOT NULL,
        job_id TEXT,
        agent_type TEXT NOT NULL,
        conversation_id TEXT NOT NULL,
        status TEXT DEFAULT 'ACTIVE',
        role_title TEXT,
        notes TEXT,
        created_at TEXT,
        updated_at TEXT
    );

    CREATE INDEX IF NOT EXISTS idx_jobs_status ON jobs(status);
    CREATE INDEX IF NOT EXISTS idx_jobs_company_tier ON jobs(company_tier);
    CREATE INDEX IF NOT EXISTS idx_jobs_canonical_hash ON jobs(canonical_hash);
    CREATE INDEX IF NOT EXISTS idx_dispatches_company ON agent_dispatches(company);
    CREATE INDEX IF NOT EXISTS idx_dispatches_convo ON agent_dispatches(conversation_id);
    """)

    conn.commit()
    conn.close()

def generate_canonical_hash(company: str, title: str, url: str, job_id: str = "") -> str:
    """
    CRITICAL DEDUPLICATION POLICY:
    Never deduplicate on company + title alone!
    Enterprises (especially Microsoft, Google, Amazon, Meta) post 10+ distinct openings
    all with the exact same title ('Software Engineer', 'AI Engineer').
    Deduplication MUST strictly incorporate the unique job requisition URL and job ID.
    """
    clean_url = url.strip().lower()
    clean_id = job_id.strip().lower() if job_id else ""
    norm = f"{company.strip().lower()}:{title.strip().lower()}:{clean_url}:{clean_id}"
    return hashlib.sha256(norm.encode("utf-8")).hexdigest()

def is_job_seen(canonical_hash: str) -> bool:
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT 1 FROM jobs WHERE canonical_hash = ?", (canonical_hash,))
    row = cursor.fetchone()
    conn.close()
    return row is not None

ALLOWED_JOB_COLUMNS = {
    "job_id", "canonical_hash", "company", "title", "location", "url",
    "source", "company_tier", "match_score", "fit_verdict", "priority_level",
    "status", "raw_jd_path", "tailored_resume_dir", "referral_invite_text",
    "referral_pitch_text", "applied_at", "notes"
}

def maybe_update_text_summary(force: bool = False, min_interval_sec: float = 30.0):
    """Debounces update_text_summary to avoid disk thrashing on every row update."""
    global _LAST_SUMMARY_TIME
    now = time.time()
    if force or (now - _LAST_SUMMARY_TIME >= min_interval_sec):
        _LAST_SUMMARY_TIME = now
        update_text_summary()

def insert_job(job: Dict[str, Any], refresh_summary: bool = False) -> bool:
    """Inserts a newly discovered job atomically if not already present. Returns True if inserted."""
    canonical_hash = job.get("canonical_hash") or generate_canonical_hash(
        job["company"], job["title"], job["url"], job.get("job_id", "")
    )

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

    inserted = cursor.rowcount > 0
    if inserted:
        cursor.execute("""
        INSERT INTO application_logs (job_id, action, details, timestamp)
        VALUES (?, 'DISCOVERED', ?, ?)
        """, (job["job_id"], f"Job found from {job.get('source')}", now))
        conn.commit()

    conn.close()
    if inserted and refresh_summary:
        maybe_update_text_summary(force=False)
    return inserted

def update_job_status(job_id: str, status: str, details: Optional[Dict[str, Any]] = None, refresh_summary: bool = False):
    """
    Safely updates job status and details.
    Guards against schema crashes by whitelisting columns and safely routing extra metadata into notes.
    """
    now = datetime.now().isoformat()
    conn = get_db_connection()
    cursor = conn.cursor()

    fields = ["status = ?", "updated_at = ?"]
    values = [status, now]

    extra_metadata = {}
    if details:
        for k, v in details.items():
            if k in ALLOWED_JOB_COLUMNS and k not in ("job_id", "status"):
                fields.append(f"{k} = ?")
                values.append(v)
            elif k not in ("job_id", "status"):
                extra_metadata[k] = v

    # If extra metadata was passed without an explicit notes update, append or store in notes
    if extra_metadata and "notes" not in (details or {}):
        cursor.execute("SELECT notes FROM jobs WHERE job_id = ?", (job_id,))
        existing_notes_row = cursor.fetchone()
        existing_notes = existing_notes_row["notes"] if existing_notes_row else ""
        merged_notes = f"{existing_notes} | Meta: {json.dumps(extra_metadata)}".strip(" |")
        fields.append("notes = ?")
        values.append(merged_notes)

    values.append(job_id)
    sql = f"UPDATE jobs SET {', '.join(fields)} WHERE job_id = ?"
    cursor.execute(sql, values)

    cursor.execute("""
    INSERT INTO application_logs (job_id, action, details, timestamp)
    VALUES (?, ?, ?, ?)
    """, (job_id, status, json.dumps(details or {}), now))

    conn.commit()
    conn.close()
    if refresh_summary:
        maybe_update_text_summary(force=False)

def get_jobs_by_status(status: str) -> List[sqlite3.Row]:
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM jobs WHERE status = ? ORDER BY created_at DESC", (status,))
    rows = cursor.fetchall()
    conn.close()
    return rows

def get_pending_priority_jobs(limit: int = 30) -> List[sqlite3.Row]:
    """Retrieves top-priority unapplied jobs waiting in EVALUATED status, prioritizing Big Tech, India FTE, and global roles."""
    conn = get_db_connection()
    c = conn.cursor()
    c.execute("""
        SELECT * FROM jobs
        WHERE status = 'EVALUATED'
          AND priority_level IN ('CRITICAL_PRIORITY', 'HIGH_PRIORITY')
          AND match_score >= 70
          AND LOWER(company) NOT IN ('openai')
          AND NOT (LOWER(company) = 'mercor' AND (LOWER(title) LIKE '%grant%' OR LOWER(title) LIKE '%benchmark%'))
        ORDER BY 
          CASE 
            WHEN company_tier = 'TIER_1' OR LOWER(company) IN ('microsoft', 'google', 'apple', 'amazon', 'meta', 'stripe', 'oracle', 'salesforce', 'uber', 'atlassian', 'adobe', 'nvidia', 'netflix', 'linkedin', 'databricks', 'snowflake', 'palantir') THEN 1
            ELSE 2
          END ASC,
          CASE 
            WHEN LOWER(location) LIKE '%india%' OR LOWER(location) LIKE '%bengaluru%' OR LOWER(location) LIKE '%bangalore%' OR LOWER(location) LIKE '%delhi%' OR LOWER(location) LIKE '%gurgaon%' OR LOWER(location) LIKE '%hyderabad%' OR LOWER(location) LIKE '%pune%' OR LOWER(location) LIKE '%mumbai%' OR LOWER(location) LIKE '%noida%' THEN 1
            WHEN LOWER(location) LIKE '%remote%' OR LOWER(title) LIKE '%remote%' THEN 2
            WHEN LOWER(company) IN ('alignerr', 'outlier', 'turing', 'dataannotation', 'askable', 'remotive', 'invisible technologies') THEN 3
            ELSE 4
          END ASC,
          CASE
            WHEN LOWER(location) LIKE '%united states%' OR LOWER(location) LIKE '%san francisco%' OR LOWER(location) LIKE '%new york%' OR LOWER(location) LIKE '%canada%' OR LOWER(location) LIKE '%germany%' OR LOWER(location) LIKE '%tokyo%' OR LOWER(location) LIKE '%singapore%' THEN 2
            ELSE 1
          END ASC,
          CASE priority_level WHEN 'CRITICAL_PRIORITY' THEN 1 ELSE 2 END,
          match_score DESC
        LIMIT ?
    """, (limit,))
    rows = c.fetchall()
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

def record_agent_dispatch(
    company: str,
    job_id: Optional[str],
    agent_type: str,
    conversation_id: str,
    status: str = "ACTIVE",
    role_title: str = "",
    notes: str = ""
) -> int:
    """
    Records an agent dispatch for a company / role.
    Allows linking and reopening the exact conversation ID when any future role for that company appears.
    """
    now = datetime.now().isoformat()
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("""
        INSERT INTO agent_dispatches (
            company, job_id, agent_type, conversation_id, status, role_title, notes, created_at, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (company, job_id or "", agent_type, conversation_id, status, role_title, notes, now, now))
    dispatch_id = cursor.lastrowid
    conn.commit()
    conn.close()
    return dispatch_id

def get_dispatches_by_company(company: str) -> List[sqlite3.Row]:
    """Retrieves all previous agent dispatches/conversations for a specific company."""
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT * FROM agent_dispatches
        WHERE LOWER(company) = LOWER(?)
        ORDER BY created_at DESC
    """, (company,))
    rows = cursor.fetchall()
    conn.close()
    return rows

def get_dispatch_by_convo(conversation_id: str) -> Optional[sqlite3.Row]:
    """Finds a dispatch record by its conversation ID."""
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM agent_dispatches WHERE conversation_id = ?", (conversation_id,))
    row = cursor.fetchone()
    conn.close()
    return row

def list_all_dispatches(limit: int = 50) -> List[sqlite3.Row]:
    """Lists recent agent dispatches across all companies."""
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM agent_dispatches ORDER BY created_at DESC LIMIT ?", (limit,))
    rows = cursor.fetchall()
    conn.close()
    return rows

def update_dispatch_status(dispatch_id: int, status: str, notes: Optional[str] = None):
    now = datetime.now().isoformat()
    conn = get_db_connection()
    cursor = conn.cursor()
    if notes:
        cursor.execute("UPDATE agent_dispatches SET status = ?, notes = ?, updated_at = ? WHERE id = ?", (status, notes, now, dispatch_id))
    else:
        cursor.execute("UPDATE agent_dispatches SET status = ?, updated_at = ? WHERE id = ?", (status, now, dispatch_id))
    conn.commit()
    conn.close()
