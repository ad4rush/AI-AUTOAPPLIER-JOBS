#!/usr/bin/env python3
"""
Company Delegator Memory System.
Persistently maps companies to their dedicated AGY worker conversation IDs.
When a new job opening appears for a company, the exact existing worker session
is resumed with full portal memory, browser state, and custom question answers.
"""

import sys
import re
import json
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Dict, Any, Optional, List

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from engine.config import DATA_DIR
from engine.db import get_db_connection

BRAIN_DIR = Path.home() / ".gemini" / "antigravity-cli" / "brain"
CONVERSATIONS_DIR = Path.home() / ".gemini" / "antigravity-cli" / "conversations"
PROCEDURES_DIR = DATA_DIR / "company_apply_procedures"
DELEGATORS_CACHE_FILE = DATA_DIR / "company_delegators.json"


def init_company_delegator_table():
    """Initializes the company_delegators table in jobs.db if not exists."""
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS company_delegators (
        company_slug TEXT PRIMARY KEY,
        company_name TEXT NOT NULL,
        conversation_id TEXT NOT NULL,
        last_job_id TEXT,
        last_role_title TEXT,
        ats_platform TEXT,
        task_space_name TEXT,
        dispatches_count INTEGER DEFAULT 1,
        created_at TEXT,
        updated_at TEXT
    );
    """)
    cursor.execute("""
    CREATE INDEX IF NOT EXISTS idx_company_delegators_convo ON company_delegators(conversation_id);
    """)
    conn.commit()
    conn.close()


def normalize_company_slug(company: str) -> str:
    """
    Normalizes company names into clean canonical slugs,
    stripping location prefixes, legal suffixes, and special characters.
    Examples:
      'REMOTE (INDIA): Marrina Decisions' -> 'marrina_decisions'
      'Microsoft Corporation' -> 'microsoft'
      'DysrupIT Technologies Ltd' -> 'dysrupit'
      'Bain & Company' -> 'bain'
    """
    if not company:
        return "unknown"
    name = str(company).strip()
    # Strip job board & location prefixes
    name = re.sub(r"^(REMOTE\s*(\([^\)]*\))?[:\-]?\s*|YC Startup\s*[\-—]\s*|Remote\s*[\-—]\s*)", "", name, flags=re.IGNORECASE).strip()
    # Strip common corporate & legal suffixes
    name = re.sub(r"\b(inc\.?|llc|corp\.?|corporation|ltd\.?|limited|technologies|technology|solutions|services|gmbh|co|company|ag)\b", "", name, flags=re.IGNORECASE).strip()
    # Clean up non-alphanumeric
    slug = re.sub(r"[^a-zA-Z0-9]+", "_", name.lower()).strip("_")
    return slug or "unknown"


def is_conversation_valid(conversation_id: str) -> bool:
    """Verifies that an AGY conversation exists on disk in brain or conversations dir."""
    if not conversation_id or conversation_id.startswith("delegated-"):
        # Synthetic fallback IDs without actual brain are not valid resumable sessions
        return False
    brain_path = BRAIN_DIR / conversation_id
    convo_path = CONVERSATIONS_DIR / f"{conversation_id}.db"
    return brain_path.exists() or convo_path.exists()


def get_company_delegator(company: str) -> Optional[Dict[str, Any]]:
    """
    Looks up the dedicated AGY worker conversation ID for a company.
    Checks:
    1. SQLite company_delegators table
    2. Cached company_delegators.json
    3. Company apply procedure JSON file
    4. agent_dispatches table in jobs.db
    Validates that the conversation is still present on disk before returning.
    """
    init_company_delegator_table()
    slug = normalize_company_slug(company)
    raw_name_lower = company.strip().lower()

    # 1. Query company_delegators table
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT * FROM company_delegators 
        WHERE company_slug = ? OR LOWER(company_name) = ?
    """, (slug, raw_name_lower))
    row = cursor.fetchone()
    conn.close()

    if row:
        convo_id = row["conversation_id"]
        if is_conversation_valid(convo_id):
            return dict(row)

    # 2. Query company apply procedure file
    PROCEDURES_DIR.mkdir(parents=True, exist_ok=True)
    proc_file = PROCEDURES_DIR / f"{slug}.json"
    if proc_file.exists():
        try:
            with open(proc_file, "r", encoding="utf-8") as f:
                pdata = json.load(f)
                convo_id = pdata.get("delegator_conversation_id")
                if convo_id and is_conversation_valid(convo_id):
                    return {
                        "company_slug": slug,
                        "company_name": company,
                        "conversation_id": convo_id,
                        "last_job_id": pdata.get("last_job_id", ""),
                        "last_role_title": pdata.get("last_role_title", ""),
                        "ats_platform": pdata.get("ats_platform", ""),
                        "task_space_name": pdata.get("task_space_name", ""),
                        "dispatches_count": pdata.get("dispatches_count", 1),
                        "updated_at": pdata.get("updated_at", "")
                    }
        except Exception:
            pass

    # 3. Query agent_dispatches table for past verified AGY worker dispatches
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT * FROM agent_dispatches 
        WHERE LOWER(company) LIKE ? OR LOWER(company) LIKE ?
        ORDER BY id DESC
    """, (f"%{slug.replace('_', ' ')}%", f"%{raw_name_lower}%"))
    dispatch_rows = cursor.fetchall()
    conn.close()

    for d in dispatch_rows:
        convo_id = d["conversation_id"]
        if is_conversation_valid(convo_id):
            result = {
                "company_slug": slug,
                "company_name": company,
                "conversation_id": convo_id,
                "last_job_id": d["job_id"],
                "last_role_title": d["role_title"],
                "ats_platform": d["agent_type"],
                "task_space_name": "",
                "dispatches_count": 1,
                "updated_at": d["updated_at"]
            }
            # Auto-persist to company_delegators table for future fast lookup
            save_company_delegator(
                company=company,
                conversation_id=convo_id,
                job_id=d["job_id"] or "",
                role_title=d["role_title"] or "",
                ats_platform=d["agent_type"] or ""
            )
            return result

    return None


def save_company_delegator(
    company: str,
    conversation_id: str,
    job_id: str = "",
    role_title: str = "",
    ats_platform: str = "",
    task_space_name: str = ""
) -> Dict[str, Any]:
    """
    Saves or updates the dedicated AGY worker conversation ID for a company.
    Updates the database table, company procedure file, and delegators cache.
    """
    init_company_delegator_table()
    slug = normalize_company_slug(company)
    now = datetime.now().isoformat()

    conn = get_db_connection()
    cursor = conn.cursor()

    cursor.execute("SELECT dispatches_count FROM company_delegators WHERE company_slug = ?", (slug,))
    existing = cursor.fetchone()

    if existing:
        new_count = existing["dispatches_count"] + 1
        cursor.execute("""
            UPDATE company_delegators
            SET company_name = ?,
                conversation_id = ?,
                last_job_id = COALESCE(NULLIF(?, ''), last_job_id),
                last_role_title = COALESCE(NULLIF(?, ''), last_role_title),
                ats_platform = COALESCE(NULLIF(?, ''), ats_platform),
                task_space_name = COALESCE(NULLIF(?, ''), task_space_name),
                dispatches_count = ?,
                updated_at = ?
            WHERE company_slug = ?
        """, (company, conversation_id, job_id, role_title, ats_platform, task_space_name, new_count, now, slug))
    else:
        new_count = 1
        cursor.execute("""
            INSERT INTO company_delegators (
                company_slug, company_name, conversation_id, last_job_id,
                last_role_title, ats_platform, task_space_name, dispatches_count,
                created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (slug, company, conversation_id, job_id, role_title, ats_platform, task_space_name, 1, now, now))

    conn.commit()
    conn.close()

    record = {
        "company_slug": slug,
        "company_name": company,
        "conversation_id": conversation_id,
        "last_job_id": job_id,
        "last_role_title": role_title,
        "ats_platform": ats_platform,
        "task_space_name": task_space_name,
        "dispatches_count": new_count,
        "updated_at": now
    }

    # Update company procedure file
    PROCEDURES_DIR.mkdir(parents=True, exist_ok=True)
    proc_file = PROCEDURES_DIR / f"{slug}.json"
    pdata = {}
    if proc_file.exists():
        try:
            with open(proc_file, "r", encoding="utf-8") as f:
                pdata = json.load(f)
        except Exception:
            pdata = {}
    pdata["delegator_conversation_id"] = conversation_id
    pdata["company_slug"] = slug
    pdata["last_updated"] = now
    if job_id:
        pdata["last_job_id"] = job_id
    if role_title:
        pdata["last_role_title"] = role_title
    if task_space_name:
        pdata["task_space_name"] = task_space_name
    try:
        with open(proc_file, "w", encoding="utf-8") as f:
            json.dump(pdata, f, indent=2)
    except Exception:
        pass

    # Update JSON cache
    sync_delegators_cache_file()

    print(f"[Delegator:Memory] Saved dedicated worker for '{company}' -> Convo ID: {conversation_id} (Count: {new_count})")
    return record


def list_company_delegators() -> List[Dict[str, Any]]:
    """Returns all registered company delegators ordered by most recently updated."""
    init_company_delegator_table()
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM company_delegators ORDER BY updated_at DESC")
    rows = [dict(r) for r in cursor.fetchall()]
    conn.close()
    return rows


def sync_delegators_cache_file():
    """Syncs the entire company_delegators table to data/company_delegators.json."""
    delegators = list_company_delegators()
    try:
        with open(DELEGATORS_CACHE_FILE, "w", encoding="utf-8") as f:
            json.dump(delegators, f, indent=2)
    except Exception as e:
        print(f"[!] Warning syncing delegators cache: {e}")


def sync_delegators_from_dispatches() -> int:
    """
    Bootstrap sync: Scans agent_dispatches and registers all valid AGY worker
    conversations found in brain into company_delegators table.
    """
    init_company_delegator_table()
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT company, conversation_id, job_id, role_title, agent_type, updated_at
        FROM agent_dispatches
        ORDER BY id ASC
    """)
    rows = cursor.fetchall()
    conn.close()

    count = 0
    for r in rows:
        cid = r["conversation_id"]
        comp = r["company"]
        if is_conversation_valid(cid):
            save_company_delegator(
                company=comp,
                conversation_id=cid,
                job_id=r["job_id"] or "",
                role_title=r["role_title"] or "",
                ats_platform=r["agent_type"] or ""
            )
            count += 1

    sync_delegators_cache_file()
    return count


if __name__ == "__main__":
    print("--- Testing Company Delegator Memory System ---")
    synced = sync_delegators_from_dispatches()
    print(f"[+] Bootstrapped & synced {synced} company delegator conversations.")

    # Test lookup for Marrina Decisions and Microsoft
    for test_comp in ["Marrina Decisions", "REMOTE (INDIA): Marrina Decisions", "Microsoft", "DysrupIT", "Dropbox"]:
        delegator = get_company_delegator(test_comp)
        if delegator:
            print(f"[FOUND] {test_comp} -> Convo: {delegator['conversation_id']} (Role: {delegator['last_role_title']})")
        else:
            print(f"[NOT FOUND] {test_comp}")
