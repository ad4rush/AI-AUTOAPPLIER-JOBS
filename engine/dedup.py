#!/usr/bin/env python3
"""
Duplicate-application guard.

Guarantees that the same job is not applied to twice, whichever entry point is
used (daemon queue, pipeline cycle, CLI apply commands, MCP tool, AGY worker,
LinkedIn batch runner) and however many processes are running at once.

How it works
------------
1. Job identity. Every job is reduced to up to three keys:
     url key  - the apply URL with tracking parameters, scheme and "www." removed
     ats key  - the posting id inside the ATS (Greenhouse gh_jid, Lever/Ashby
                uuid, LinkedIn job id, Amazon id, Workday requisition, ...), so
                the same posting reached through two different URLs still matches
     ct key   - normalised company + title, only when the company name is
                trustworthy (not a placeholder, not a job title, not a city)
   Keys for rows in `jobs` are kept in the side table `job_identity`.

2. Decision. Before any engine touches a form, the guard looks for
     - a `jobs` row with one of those keys that is already applied, staged or
       dispatched, and
     - a live claim in `apply_claims` held by another process.
   URL and ATS matches block forever. Company + title matches block only inside
   DEDUP_COMPANY_TITLE_WINDOW_DAYS (default 120, 0 disables), so a role that is
   re-opened months later can still be applied to.

3. Claim. If the application may proceed, the keys are written to
   `apply_claims` inside one BEGIN IMMEDIATE transaction, so two processes
   cannot both start the same application.

4. Submit tracking. Engines print SUBMIT_MARKER immediately before they click
   the final submit control. A hook on subprocess.run sees that marker and
   turns the claim into a permanent SUBMITTED record at once. From then on no
   fallback engine and no worker may submit that job again, even if the engine
   that clicked crashed, timed out or reported failure.

Escape hatch: JOB_APPLY_ALLOW_DUPLICATE=1 disables blocking for one invocation.
"""

import functools
import inspect
import os
import re
import sqlite3
import subprocess
import threading
import uuid
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional, Set, Tuple
from urllib.parse import parse_qsl, urlparse

import engine.db as _db

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

SUBMIT_MARKER = "[[SUBMIT_CLICK_ATTEMPT]]"
SUBMIT_CANCEL_MARKER = "[[SUBMIT_CLICK_NONE]]"

# Scripts generated before the marker existed announce the click with this text.
_LEGACY_SUBMIT_RE = re.compile(r"\] Submit requested\.\.\.")

# Statuses that mean "an application has gone out (or may have)".
APPLIED_STATES = {"APPLIED", "SUBMIT_UNCONFIRMED"}
# Statuses a job moves to after it was applied; they count as applied when applied_at is set.
POST_APPLY_STATES = {"CLOSED", "REJECTED", "INTERVIEW", "INTERVIEWING", "OFFER"}
# Statuses that mean "an application is being prepared under this row".
PENDING_STATES = {"STAGED", "STAGED_FOR_REVIEW", "DISPATCHED"}

CLAIM_TTL_MINUTES = int(os.getenv("DEDUP_CLAIM_TTL_MINUTES", "30"))
DISPATCH_TTL_MINUTES = int(os.getenv("DEDUP_DISPATCH_TTL_MINUTES", "60"))


def _company_title_window_days() -> int:
    try:
        return int(os.getenv("DEDUP_COMPANY_TITLE_WINDOW_DAYS", "120"))
    except ValueError:
        return 120


def _bypass_enabled() -> bool:
    return os.getenv("JOB_APPLY_ALLOW_DUPLICATE", "").strip().lower() in ("1", "true", "yes")


OWNER = f"{os.getpid()}-{uuid.uuid4().hex[:8]}"

# ---------------------------------------------------------------------------
# Identity keys
# ---------------------------------------------------------------------------

_TRACKING_PARAMS = {
    "utm_source", "utm_medium", "utm_campaign", "utm_term", "utm_content", "utm_id",
    "ref", "refid", "source", "src", "gh_src", "t", "source_id", "cmpid", "trk",
    "trackingid", "ebp", "position", "pagenum", "embedsource", "lever-source",
    "lever-origin", "iis", "iisn", "sid", "jobboard", "mode", "board",
}

_GENERIC_COMPANIES = {
    "", "targetcompany", "techcompany", "techenterprise", "remotetech", "remote",
    "remotecontract", "himalayasemployer", "ycstartup", "linkedinjob", "unknown",
    "unknowncompany", "confidential", "company", "employer", "startup", "stealth",
    "stealthstartup", "ashbysupportedcompany", "greenhousesupportedcompany",
    "leversupportedcompany", "client", "aiclient", "fintechclient", "supplychainclient",
}

_LEGAL_SUFFIX_RE = re.compile(
    r"[\s,]+(?:inc|llc|ltd|limited|pvt|private|corp|corporation|co|gmbh|ag|kg|plc|bv|sa|sas|srl|pte|llp)\.?(?=[\s,&]|$)",
    re.I,
)

_WORK_MODE_RE = re.compile(r"\((?:on-?site|remote|hybrid)\)|\b(?:on-?site|hybrid)\b", re.I)

_LOCATION_WORDS = (
    "india", "bengaluru", "bangalore", "hyderabad", "noida", "gurugram", "gurgaon", "pune",
    "mumbai", "delhi", "chennai", "kolkata", "ncr", "remote", "hybrid", "on-site", "onsite",
    "worldwide", "global", "anywhere", "usa", "united states", "europe", "emea", "apac", "uk",
)

_ROLE_WORDS_RE = re.compile(
    r"\b(?:engineer|developer|scientist|analyst|intern|internship|manager|architect|"
    r"consultant|associate|specialist|researcher|programmer|sde|swe|technologist)\b",
    re.I,
)

# (prefix, regex). Group 1 (and 2 when present) form the key.
_ATS_PATTERNS: List[Tuple[str, "re.Pattern"]] = [
    ("gh", re.compile(r"[?&]gh_jid=(\d+)", re.I)),
    ("gh", re.compile(r"greenhouse\.io/[^/?#]+/jobs/(\d+)", re.I)),
    ("gh", re.compile(r"greenhouse\.io/embed/job_app\?.*?token=(\d+)", re.I)),
    ("lever", re.compile(r"lever\.co/[^/?#]+/([0-9a-f]{8}-[0-9a-f-]{27})", re.I)),
    ("ashby", re.compile(r"ashbyhq\.com/[^/?#]+/([0-9a-f]{8}-[0-9a-f-]{27})", re.I)),
    ("li", re.compile(r"linkedin\.com/jobs/view/(?:[^/?#]*?-)?(\d{6,})", re.I)),
    ("li", re.compile(r"linkedin\.com/.*[?&]currentJobId=(\d{6,})", re.I)),
    ("amzn", re.compile(r"amazon\.jobs/(?:[a-z_-]+/)?jobs/(\d+)", re.I)),
    ("msft", re.compile(r"careers\.microsoft\.com/.*?(?:/job/|[?&]pid=)(\d+)", re.I)),
    ("appl", re.compile(r"jobs\.apple\.com/[^/?#]+/details/([0-9A-Za-z-]+)", re.I)),
    ("goog", re.compile(r"google\.com/about/careers/applications/jobs/results/(\d+)", re.I)),
    ("sr", re.compile(r"smartrecruiters\.com/[^/?#]+/(\d{6,})", re.I)),
    ("wd", re.compile(r"//([a-z0-9-]+)\.wd\d+\.myworkdayjobs\.com/.*_([A-Za-z]{0,6}-?\d[\w-]*?)(?:[/?#]|$)", re.I)),
    ("rippling", re.compile(r"ats\.rippling\.com/[^/?#]+/jobs/([0-9a-f]{8}-[0-9a-f-]{27})", re.I)),
    ("dover", re.compile(r"jobs\.dover\.com/[^/?#]+/([0-9a-f]{8}-[0-9a-f-]{27})", re.I)),
    ("manatal", re.compile(r"careers-page\.com/jobs/([0-9a-f]{8}-[0-9a-f-]{27})", re.I)),
    ("workable", re.compile(r"apply\.workable\.com/[^/?#]+/j/([0-9A-Za-z]+)", re.I)),
    ("breezy", re.compile(r"//([a-z0-9-]+)\.breezy\.hr/p/([0-9a-f]{6,})", re.I)),
    ("yc", re.compile(r"workatastartup\.com/jobs/(\d+)", re.I)),
    ("outlier", re.compile(r"outlier\.ai/.*?/opportunities/(\d+)", re.I)),
    ("jobicy", re.compile(r"jobicy\.com/jobs/(\d+)", re.I)),
    ("naukri", re.compile(r"naukri\.com/job-listings-.*?-(\d{9,})(?:[/?#]|$)", re.I)),
    ("zoho", re.compile(r"//([a-z0-9-]+)\.zohorecruit\.[a-z.]+/jobs/[^/?#]+/(\d+)", re.I)),
]


def company_slug(company: str) -> str:
    """Normalised company name: lower case, legal suffixes and punctuation removed."""
    text = (company or "").strip().lower()
    prev = None
    while prev != text:
        prev = text
        text = _LEGAL_SUFFIX_RE.sub("", text).strip(" ,.&")
    return re.sub(r"[^a-z0-9]", "", text)


def title_slug(title: str) -> str:
    """Normalised title: scraper tags and location/work-mode suffixes removed."""
    text = (title or "").lower()
    text = re.sub(r"\[[^\]]*\]", " ", text)

    def _drop_location_parens(match: "re.Match") -> str:
        inner = match.group(1)
        return " " if any(word in inner for word in _LOCATION_WORDS) else match.group(0)

    text = re.sub(r"\(([^)]*)\)", _drop_location_parens, text)
    prev = None
    while prev != text:
        prev = text
        text = re.sub(r"\s*[-–|/]\s*(?:remote|hybrid|on-?site|india)\s*$", "", text, flags=re.I).strip()
    return re.sub(r"[^a-z0-9]", "", text)


def is_trustworthy_company(company: str, title: str = "") -> bool:
    """
    False when the stored company cannot identify an employer: a placeholder
    default, a copy of the job title, a city or work mode, or a string that
    reads like a role. Such rows are matched by URL and ATS id only.
    """
    raw = (company or "").strip()
    slug = company_slug(raw)
    if len(slug) < 2 or slug in _GENERIC_COMPANIES:
        return False
    if title and slug == title_slug(title):
        return False
    if _WORK_MODE_RE.search(raw):
        return False
    lowered = raw.lower()
    if lowered in _LOCATION_WORDS:
        return False
    if _ROLE_WORDS_RE.search(raw) and len(raw.split()) >= 2:
        return False
    return True


def url_key(url: str) -> str:
    """Canonical form of an apply URL for equality comparison."""
    raw = (url or "").strip()
    if not raw:
        return ""
    if "://" not in raw:
        raw = "https://" + raw
    try:
        parsed = urlparse(raw)
    except Exception:
        return raw.lower().rstrip("/")
    host = parsed.netloc.lower()
    if host.startswith("www."):
        host = host[4:]
    path = re.sub(r"/+$", "", parsed.path)
    path = re.sub(r"/(?:apply|application)$", "", path, flags=re.I)
    kept = sorted(
        (k.lower(), v) for k, v in parse_qsl(parsed.query, keep_blank_values=True)
        if k.lower() not in _TRACKING_PARAMS
    )
    seen: Set[Tuple[str, str]] = set()
    query_parts = []
    for item in kept:
        if item in seen:
            continue
        seen.add(item)
        query_parts.append(f"{item[0]}={item[1]}")
    query = "&".join(query_parts)
    key = f"{host}{path}"
    if query:
        key += f"?{query}"
    return key.lower()


def ats_key(url: str) -> str:
    """Posting id inside the applicant tracking system, or '' when unknown."""
    raw = (url or "").strip()
    if not raw:
        return ""
    for prefix, pattern in _ATS_PATTERNS:
        match = pattern.search(raw)
        if match:
            parts = [g.lower() for g in match.groups() if g]
            return f"{prefix}:{':'.join(parts)}"
    return ""


def ct_key(company: str, title: str) -> str:
    """Company + title key, or '' when either part cannot be trusted."""
    if not is_trustworthy_company(company, title):
        return ""
    t_slug = title_slug(title)
    if len(t_slug) < 3:
        return ""
    return f"{company_slug(company)}|{t_slug}"


def identity_keys(company: str, title: str, url: str) -> Dict[str, str]:
    return {"url": url_key(url), "ats": ats_key(url), "ct": ct_key(company, title)}


# ---------------------------------------------------------------------------
# Schema and identity table maintenance
# ---------------------------------------------------------------------------

_SCHEMA_READY: Set[str] = set()

_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS job_identity (
    job_id TEXT PRIMARY KEY,
    url_key TEXT NOT NULL DEFAULT '',
    ats_key TEXT NOT NULL DEFAULT '',
    ct_key TEXT NOT NULL DEFAULT '',
    src_company TEXT,
    src_title TEXT,
    src_url TEXT
);
CREATE INDEX IF NOT EXISTS idx_job_identity_url ON job_identity(url_key);
CREATE INDEX IF NOT EXISTS idx_job_identity_ats ON job_identity(ats_key);
CREATE INDEX IF NOT EXISTS idx_job_identity_ct ON job_identity(ct_key);

CREATE TABLE IF NOT EXISTS apply_claims (
    claim_key TEXT PRIMARY KEY,
    job_id TEXT,
    owner TEXT NOT NULL,
    state TEXT NOT NULL,
    company TEXT,
    title TEXT,
    url TEXT,
    claimed_at TEXT NOT NULL,
    expires_at TEXT
);
CREATE INDEX IF NOT EXISTS idx_apply_claims_owner ON apply_claims(owner);
CREATE INDEX IF NOT EXISTS idx_apply_claims_job ON apply_claims(job_id);
"""


def _connect() -> sqlite3.Connection:
    conn = _db.get_db_connection()
    conn.isolation_level = None  # explicit transactions only
    db_id = str(_db.DB_PATH)
    if db_id not in _SCHEMA_READY:
        conn.executescript(_SCHEMA_SQL)
        _SCHEMA_READY.add(db_id)
    return conn


def _jobs_table_exists(conn: sqlite3.Connection) -> bool:
    row = conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='jobs'").fetchone()
    return row is not None


def sync_job_identity(conn: Optional[sqlite3.Connection] = None) -> int:
    """
    Brings `job_identity` in line with `jobs`: adds missing rows, recomputes
    rows whose company, title or url changed, removes orphans.
    Returns the number of rows written.
    """
    own = conn is None
    conn = conn or _connect()
    try:
        if not _jobs_table_exists(conn):
            return 0
        stale = conn.execute(
            """
            SELECT j.job_id, j.company, j.title, j.url
            FROM jobs j LEFT JOIN job_identity i ON i.job_id = j.job_id
            WHERE i.job_id IS NULL
               OR i.src_company IS NOT j.company
               OR i.src_title IS NOT j.title
               OR i.src_url IS NOT j.url
            """
        ).fetchall()
        if stale:
            own_txn = not conn.in_transaction
            if own_txn:
                conn.execute("BEGIN IMMEDIATE")
            try:
                for row in stale:
                    keys = identity_keys(row["company"], row["title"], row["url"])
                    conn.execute(
                        "INSERT OR REPLACE INTO job_identity "
                        "(job_id, url_key, ats_key, ct_key, src_company, src_title, src_url) "
                        "VALUES (?, ?, ?, ?, ?, ?, ?)",
                        (row["job_id"], keys["url"], keys["ats"], keys["ct"],
                         row["company"], row["title"], row["url"]),
                    )
                if own_txn:
                    conn.execute("COMMIT")
            except Exception:
                if own_txn:
                    conn.execute("ROLLBACK")
                raise
        n_identity = conn.execute("SELECT COUNT(*) FROM job_identity").fetchone()[0]
        n_jobs = conn.execute("SELECT COUNT(*) FROM jobs").fetchone()[0]
        if n_identity > n_jobs:
            conn.execute("DELETE FROM job_identity WHERE job_id NOT IN (SELECT job_id FROM jobs)")
        return len(stale)
    finally:
        if own:
            conn.close()


def record_job_identity(job_id: str, company: str, title: str, url: str,
                        conn: Optional[sqlite3.Connection] = None) -> None:
    """Writes the identity row for one job (called right after insertion)."""
    own = conn is None
    conn = conn or _connect()
    try:
        keys = identity_keys(company, title, url)
        conn.execute(
            "INSERT OR REPLACE INTO job_identity "
            "(job_id, url_key, ats_key, ct_key, src_company, src_title, src_url) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (job_id, keys["url"], keys["ats"], keys["ct"], company, title, url),
        )
    finally:
        if own:
            conn.close()


def find_job_by_posting(url: str) -> Optional[Dict[str, Any]]:
    """
    Returns the `jobs` row that is the same posting as `url` (same URL key or
    same ATS id), preferring the row that is furthest along. None if unknown.
    """
    u_key, a_key = url_key(url), ats_key(url)
    if not u_key and not a_key:
        return None
    conn = _connect()
    try:
        if not _jobs_table_exists(conn):
            return None
        sync_job_identity(conn)
        rows = _matching_job_rows(conn, {u_key} if u_key else set(), {a_key} if a_key else set(), set())
        return _pick_most_advanced(rows)
    finally:
        conn.close()


def posting_already_known(url: str) -> bool:
    """True when another URL form of this same ATS posting is already in `jobs`."""
    a_key = ats_key(url)
    if not a_key:
        return False
    conn = _connect()
    try:
        if not _jobs_table_exists(conn):
            return False
        sync_job_identity(conn)
        row = conn.execute("SELECT 1 FROM job_identity WHERE ats_key = ? LIMIT 1", (a_key,)).fetchone()
        return row is not None
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Decision logic
# ---------------------------------------------------------------------------

class GuardDecision:
    """Outcome of a duplicate check."""

    def __init__(self, allowed: bool, reason: str = "", detail: str = "",
                 duplicate_of: Optional[str] = None, job_id: Optional[str] = None):
        self.allowed = allowed
        self.reason = reason          # "", "DUPLICATE", "IN_PROGRESS"
        self.detail = detail
        self.duplicate_of = duplicate_of
        self.job_id = job_id          # the jobs row this application belongs to, if any

    def __repr__(self) -> str:
        return (f"GuardDecision(allowed={self.allowed}, reason={self.reason!r}, "
                f"duplicate_of={self.duplicate_of!r}, job_id={self.job_id!r}, detail={self.detail!r})")


_STATUS_RANK = {"APPLIED": 0, "SUBMIT_UNCONFIRMED": 1, "STAGED": 2, "STAGED_FOR_REVIEW": 2,
                "DISPATCHED": 3, "TAILORED": 4, "EVALUATED": 5, "DISCOVERED": 6}


def _pick_most_advanced(rows: List[sqlite3.Row]) -> Optional[Dict[str, Any]]:
    if not rows:
        return None
    ordered = sorted(rows, key=lambda r: (_STATUS_RANK.get(r["status"], 9), r["job_id"]))
    return dict(ordered[0])


def _matching_job_rows(conn: sqlite3.Connection, url_keys: Set[str], ats_keys: Set[str],
                       ct_keys: Set[str]) -> List[sqlite3.Row]:
    clauses: List[str] = []
    params: List[str] = []
    for column, values in (("url_key", url_keys), ("ats_key", ats_keys), ("ct_key", ct_keys)):
        values = {v for v in values if v}
        if values:
            clauses.append(f"i.{column} IN ({','.join('?' * len(values))})")
            params.extend(sorted(values))
    if not clauses:
        return []
    return conn.execute(
        "SELECT j.job_id, j.company, j.title, j.url, j.status, j.applied_at, j.updated_at, "
        "       i.url_key, i.ats_key, i.ct_key "
        "FROM job_identity i JOIN jobs j ON j.job_id = i.job_id "
        f"WHERE {' OR '.join(clauses)}",
        params,
    ).fetchall()


def _parse_ts(value: Optional[str]) -> Optional[datetime]:
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value))
    except ValueError:
        return None


def _within_ct_window(timestamp: Optional[str], now: datetime) -> bool:
    days = _company_title_window_days()
    if days <= 0:
        return False
    ts = _parse_ts(timestamp)
    if ts is None:
        return True  # unknown age: be conservative
    return (now - ts) <= timedelta(days=days)


def _is_applied_like(status: str, applied_at: Optional[str]) -> bool:
    return status in APPLIED_STATES or (status in POST_APPLY_STATES and bool(applied_at))


def _pid_alive(owner: str) -> bool:
    try:
        pid = int(str(owner).split("-", 1)[0])
    except ValueError:
        return True
    if pid <= 0:
        return True
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except OSError:
        return True
    return True


def _claim_keys(url_keys: Set[str], ats_keys: Set[str], ct_keys: Set[str]) -> List[str]:
    keys = [f"url:{k}" for k in sorted(url_keys) if k]
    keys += [f"ats:{k}" for k in sorted(ats_keys) if k]
    keys += [f"ct:{k}" for k in sorted(ct_keys) if k]
    return keys


def _resolve(conn: sqlite3.Connection, company: str, title: str, url: str,
             job_id: str) -> Tuple[Optional[Dict[str, Any]], Set[str], Set[str], Set[str]]:
    """Finds the jobs row this application belongs to and the full key sets to check."""
    url_keys = {url_key(url)} - {""}
    ats_keys = {ats_key(url)} - {""}
    ct_keys: Set[str] = set()

    self_row: Optional[Dict[str, Any]] = None
    if job_id:
        row = conn.execute(
            "SELECT job_id, company, title, url, status, applied_at, updated_at FROM jobs WHERE job_id = ?",
            (job_id,),
        ).fetchone()
        if row:
            self_row = dict(row)
    if self_row is None and (url_keys or ats_keys):
        self_row = _pick_most_advanced(_matching_job_rows(conn, url_keys, ats_keys, set()))

    if self_row:
        # The database copy of company/title is more reliable than caller defaults.
        stored = identity_keys(self_row["company"], self_row["title"], self_row["url"])
        url_keys |= {stored["url"]} - {""}
        ats_keys |= {stored["ats"]} - {""}
        ct_keys |= {stored["ct"]} - {""}
    else:
        ct_keys |= {ct_key(company, title)} - {""}
    return self_row, url_keys, ats_keys, ct_keys


def _evaluate(conn: sqlite3.Connection, self_row: Optional[Dict[str, Any]], url_keys: Set[str],
              ats_keys: Set[str], ct_keys: Set[str], owner: str, now: datetime) -> GuardDecision:
    self_id = self_row["job_id"] if self_row else None

    if self_row and _is_applied_like(self_row["status"], self_row.get("applied_at")):
        return GuardDecision(
            False, "DUPLICATE",
            f"job {self_id} is already {self_row['status']}"
            + (f" (applied_at {self_row['applied_at']})" if self_row.get("applied_at") else ""),
            duplicate_of=self_id, job_id=self_id,
        )

    for row in _matching_job_rows(conn, url_keys, ats_keys, ct_keys):
        if row["job_id"] == self_id:
            continue
        strong = (row["url_key"] in url_keys) or (bool(row["ats_key"]) and row["ats_key"] in ats_keys)
        weak = bool(row["ct_key"]) and row["ct_key"] in ct_keys
        applied_like = _is_applied_like(row["status"], row["applied_at"])
        pending_like = row["status"] in PENDING_STATES
        if not (applied_like or pending_like):
            continue
        if not strong:
            if not weak or not _within_ct_window(row["applied_at"] or row["updated_at"], now):
                continue
        how = "same posting" if strong else "same company and title"
        return GuardDecision(
            False, "DUPLICATE",
            f"{how} as job {row['job_id']} ({row['company']} - {row['title']}), which is {row['status']}",
            duplicate_of=row["job_id"], job_id=self_id,
        )

    claim_keys = _claim_keys(url_keys, ats_keys, ct_keys)
    if claim_keys:
        placeholders = ",".join("?" * len(claim_keys))
        claims = conn.execute(
            f"SELECT * FROM apply_claims WHERE claim_key IN ({placeholders})", claim_keys
        ).fetchall()
        for claim in claims:
            weak_only = claim["claim_key"].startswith("ct:")
            if claim["state"] == "SUBMITTED":
                if weak_only and not _within_ct_window(claim["claimed_at"], now):
                    continue
                label = claim["job_id"] or claim["url"] or claim["claim_key"]
                return GuardDecision(
                    False, "DUPLICATE",
                    f"submit was already clicked for {label} on {claim['claimed_at']}",
                    duplicate_of=claim["job_id"] or None, job_id=self_id,
                )
            if claim["owner"] == owner:
                continue
            expires = _parse_ts(claim["expires_at"])
            expired = expires is not None and expires < now
            if expired or not _pid_alive(claim["owner"]):
                conn.execute("DELETE FROM apply_claims WHERE claim_key = ? AND state = 'APPLYING'",
                             (claim["claim_key"],))
                continue
            return GuardDecision(
                False, "IN_PROGRESS",
                f"another process ({claim['owner']}) started this application at {claim['claimed_at']}",
                duplicate_of=claim["job_id"] or None, job_id=self_id,
            )

    return GuardDecision(True, job_id=self_id)


def check_application(company: str = "", title: str = "", url: str = "",
                      job_id: str = "", delegating: bool = False) -> GuardDecision:
    """
    Read-only duplicate check. Does not claim anything.
    With delegating=True it also refuses a job that was handed to a worker
    less than DISPATCH_TTL_MINUTES ago, so two workers are never spawned for it.
    """
    if _bypass_enabled():
        return GuardDecision(True, job_id=job_id or None)
    conn = _connect()
    try:
        if not _jobs_table_exists(conn):
            return GuardDecision(True, job_id=job_id or None)
        sync_job_identity(conn)
        now = datetime.now()
        self_row, url_keys, ats_keys, ct_keys = _resolve(conn, company, title, url, job_id)
        decision = _evaluate(conn, self_row, url_keys, ats_keys, ct_keys, OWNER, now)
        if decision.allowed and delegating and self_row and self_row["status"] == "DISPATCHED":
            updated = _parse_ts(self_row.get("updated_at"))
            if updated and (now - updated) < timedelta(minutes=DISPATCH_TTL_MINUTES):
                return GuardDecision(
                    False, "IN_PROGRESS",
                    f"job {self_row['job_id']} was already dispatched to a worker at {self_row['updated_at']}",
                    duplicate_of=self_row["job_id"], job_id=self_row["job_id"],
                )
        return decision
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# The guard (claim + submit tracking)
# ---------------------------------------------------------------------------

_local = threading.local()


def _stack() -> List["ApplicationGuard"]:
    if not hasattr(_local, "stack"):
        _local.stack = []
    return _local.stack


def current_guard() -> Optional["ApplicationGuard"]:
    """The outermost guard active on this thread, or None."""
    stack = _stack()
    return stack[0] if stack else None


def submit_already_attempted() -> bool:
    """True once a submit click has been observed inside the active guard."""
    guard = current_guard()
    return bool(guard and guard.submit_attempted)


def _blocked_result(reason: str, detail: str, duplicate_of: Optional[str], job_id: Optional[str]) -> Dict[str, Any]:
    return {
        "success": False,
        "skipped": True,
        "duplicate": reason == "DUPLICATE",
        "in_progress": reason == "IN_PROGRESS",
        "blocked_reason": reason,
        "duplicate_of": duplicate_of,
        "job_id": job_id,
        "submit_attempted": False,
        "final_status": reason,
        "error": f"{reason}: {detail}",
    }


class ApplicationGuard:
    """
    Context manager wrapped around one application attempt.

        with ApplicationGuard(url=url, company=co, title=title, job_id=jid, submit=True) as guard:
            if not guard.allowed:
                return guard.blocked_result()
            res = run_engine(...)
            return guard.annotate(res)

    Guards nest: an engine called from inside dispatch_application joins the
    outer guard instead of claiming again. Once a submit click has been seen,
    any further nested attempt for that job is refused.
    """

    def __init__(self, url: str = "", company: str = "", title: str = "", job_id: str = "",
                 submit: bool = False, source: str = ""):
        self.url = url or ""
        self.company = company or ""
        self.title = title or ""
        self.job_id = job_id or ""
        self.submit = bool(submit)
        self.source = source
        self.allowed = False
        self.reason = ""
        self.detail = ""
        self.duplicate_of: Optional[str] = None
        self._parent: Optional["ApplicationGuard"] = None
        self._claim_keys: List[str] = []
        self._submit_attempted = False
        self._submit_confirmed = False
        self._entered = False

    # -- state shared with the outermost guard ------------------------------

    @property
    def root(self) -> "ApplicationGuard":
        return self._parent.root if self._parent else self

    @property
    def submit_attempted(self) -> bool:
        return self.root._submit_attempted

    @property
    def submit_confirmed(self) -> bool:
        return self.root._submit_confirmed

    # -- context manager ----------------------------------------------------

    def __enter__(self) -> "ApplicationGuard":
        stack = _stack()
        self._entered = True
        if stack:
            # Applications never interleave on one thread, so a guard opened while
            # another is active is a step of that same application (an engine
            # called by the dispatcher, or a fallback engine).
            self._parent = stack[0]
            root = self._parent.root
            if root.submit_attempted:
                self.allowed = False
                self.reason = "DUPLICATE"
                self.detail = "submit was already clicked earlier in this run; refusing a second attempt"
                self.duplicate_of = root.job_id or None
            elif not root.allowed:
                self.allowed = False
                self.reason = root.reason
                self.detail = root.detail
                self.duplicate_of = root.duplicate_of
            else:
                self.allowed = True
                if not _bypass_enabled():
                    try:
                        self._extend_root_claim(root)
                    except sqlite3.Error as exc:
                        self.allowed = False
                        self.reason = "IN_PROGRESS"
                        self.detail = f"duplicate check unavailable ({exc})"
            stack.append(self)
            return self

        if _bypass_enabled():
            self.allowed = True
            stack.append(self)
            return self

        try:
            self._acquire()
        except sqlite3.Error as exc:
            # Fail closed: if the claim cannot be checked, do not apply.
            self.allowed = False
            self.reason = "IN_PROGRESS"
            self.detail = f"duplicate check unavailable ({exc})"
        stack.append(self)
        return self

    def __exit__(self, exc_type, exc, tb) -> bool:
        stack = _stack()
        if self in stack:
            stack.remove(self)
        if self._parent is not None:
            return False
        try:
            self._release()
        except sqlite3.Error as err:
            print(f"[Dedup] Warning: could not finalise claim: {err}")
        return False

    def _extend_root_claim(self, root: "ApplicationGuard") -> None:
        """
        A nested step may be working on a different URL for the same job, for
        example an aggregator link that resolved to the employer's ATS posting.
        That URL is checked too, and claimed under the outer guard.
        """
        new_url = {url_key(self.url)} - {""}
        new_ats = {ats_key(self.url)} - {""}
        new_keys = [k for k in _claim_keys(new_url, new_ats, set()) if k not in root._claim_keys]
        if not new_keys:
            return
        conn = _connect()
        try:
            if not _jobs_table_exists(conn):
                return
            conn.execute("BEGIN IMMEDIATE")
            try:
                now = datetime.now()
                self_row = None
                if root.job_id:
                    row = conn.execute(
                        "SELECT job_id, company, title, url, status, applied_at, updated_at "
                        "FROM jobs WHERE job_id = ?", (root.job_id,)).fetchone()
                    self_row = dict(row) if row else None
                decision = _evaluate(conn, self_row, new_url, new_ats, set(), OWNER, now)
                if not decision.allowed:
                    self.allowed = False
                    self.reason = decision.reason
                    self.detail = decision.detail
                    self.duplicate_of = decision.duplicate_of
                else:
                    expires = (now + timedelta(minutes=CLAIM_TTL_MINUTES)).isoformat()
                    for key in new_keys:
                        conn.execute(
                            "INSERT OR REPLACE INTO apply_claims "
                            "(claim_key, job_id, owner, state, company, title, url, claimed_at, expires_at) "
                            "VALUES (?, ?, ?, 'APPLYING', ?, ?, ?, ?, ?)",
                            (key, root.job_id or None, OWNER, root.company, root.title, self.url,
                             now.isoformat(), expires),
                        )
                    root._claim_keys.extend(new_keys)
                conn.execute("COMMIT")
            except Exception:
                conn.execute("ROLLBACK")
                raise
        finally:
            conn.close()

    def _acquire(self) -> None:
        conn = _connect()
        try:
            if _jobs_table_exists(conn):
                sync_job_identity(conn)
            conn.execute("BEGIN IMMEDIATE")
            try:
                now = datetime.now()
                if _jobs_table_exists(conn):
                    self_row, url_keys, ats_keys, ct_keys = _resolve(
                        conn, self.company, self.title, self.url, self.job_id)
                else:
                    self_row = None
                    url_keys = {url_key(self.url)} - {""}
                    ats_keys = {ats_key(self.url)} - {""}
                    ct_keys = {ct_key(self.company, self.title)} - {""}
                decision = _evaluate(conn, self_row, url_keys, ats_keys, ct_keys, OWNER, now)
                if self_row:
                    self.job_id = self_row["job_id"]
                    self.company = self.company or self_row["company"]
                    self.title = self.title or self_row["title"]
                self.allowed = decision.allowed
                self.reason = decision.reason
                self.detail = decision.detail
                self.duplicate_of = decision.duplicate_of
                if decision.allowed:
                    self._claim_keys = _claim_keys(url_keys, ats_keys, ct_keys)
                    expires = (now + timedelta(minutes=CLAIM_TTL_MINUTES)).isoformat()
                    for key in self._claim_keys:
                        conn.execute(
                            "INSERT OR REPLACE INTO apply_claims "
                            "(claim_key, job_id, owner, state, company, title, url, claimed_at, expires_at) "
                            "VALUES (?, ?, ?, 'APPLYING', ?, ?, ?, ?, ?)",
                            (key, self.job_id or None, OWNER, self.company, self.title, self.url,
                             now.isoformat(), expires),
                        )
                conn.execute("COMMIT")
            except Exception:
                conn.execute("ROLLBACK")
                raise
        finally:
            conn.close()

    def _release(self) -> None:
        if not self._claim_keys and not (self._submit_attempted or self._submit_confirmed):
            return
        conn = _connect()
        try:
            if self._claim_keys and not (self._submit_attempted or self._submit_confirmed):
                placeholders = ",".join("?" * len(self._claim_keys))
                conn.execute(
                    f"DELETE FROM apply_claims WHERE owner = ? AND state = 'APPLYING' "
                    f"AND claim_key IN ({placeholders})",
                    [OWNER] + self._claim_keys,
                )
        finally:
            conn.close()
        if self._submit_attempted or self._submit_confirmed:
            self._persist_submitted()
            self._finalize_job_row()

    # -- submit tracking ----------------------------------------------------

    def heartbeat(self) -> None:
        """Extends the claim while the application is still running."""
        root = self.root
        if not root._claim_keys or root._submit_attempted:
            return
        try:
            conn = _connect()
            try:
                expires = (datetime.now() + timedelta(minutes=CLAIM_TTL_MINUTES)).isoformat()
                placeholders = ",".join("?" * len(root._claim_keys))
                conn.execute(
                    f"UPDATE apply_claims SET expires_at = ? WHERE owner = ? AND state = 'APPLYING' "
                    f"AND claim_key IN ({placeholders})",
                    [expires, OWNER] + root._claim_keys,
                )
            finally:
                conn.close()
        except sqlite3.Error:
            pass

    def mark_submit_attempted(self) -> None:
        """Records, durably and immediately, that the final submit control was clicked."""
        root = self.root
        if root._submit_attempted:
            return
        root._submit_attempted = True
        try:
            root._persist_submitted()
        except sqlite3.Error as err:
            print(f"[Dedup] Warning: could not persist submit record: {err}")

    def _persist_submitted(self) -> None:
        if not self._claim_keys:
            # Bypass mode or no keys were claimed: still leave a record for this posting.
            self._claim_keys = _claim_keys({url_key(self.url)} - {""}, {ats_key(self.url)} - {""},
                                           {ct_key(self.company, self.title)} - {""})
        if not self._claim_keys:
            return
        conn = _connect()
        try:
            now = datetime.now().isoformat()
            for key in self._claim_keys:
                conn.execute(
                    "INSERT OR REPLACE INTO apply_claims "
                    "(claim_key, job_id, owner, state, company, title, url, claimed_at, expires_at) "
                    "VALUES (?, ?, ?, 'SUBMITTED', ?, ?, ?, ?, NULL)",
                    (key, self.job_id or None, OWNER, self.company, self.title, self.url, now),
                )
        finally:
            conn.close()

    def _finalize_job_row(self) -> None:
        """Makes sure the jobs row reflects that a submit happened, whoever the caller was."""
        if not self.job_id:
            return
        try:
            row = _db.get_job_by_id(self.job_id)
        except sqlite3.Error:
            return
        if not row:
            return
        current = row["status"]
        target = "APPLIED" if self._submit_confirmed else "SUBMIT_UNCONFIRMED"
        if current == "APPLIED" or current == target:
            return
        note = ("Submit confirmed by the apply engine."
                if self._submit_confirmed
                else "Submit was clicked but no confirmation was detected. Check the portal or inbox; "
                     "the job will not be applied to again.")
        _db.update_job_status(self.job_id, target, {
            "applied_at": datetime.now().isoformat(),
            "notes": f"[Dedup] {note}",
        })

    def observe_output(self, *streams: Any) -> None:
        """Scans engine output for the submit marker."""
        for stream in streams:
            if stream is None:
                continue
            if isinstance(stream, (bytes, bytearray)):
                try:
                    stream = stream.decode("utf-8", errors="ignore")
                except Exception:
                    continue
            if not isinstance(stream, str) or not stream:
                continue
            attempt_at = stream.rfind(SUBMIT_MARKER)
            if attempt_at == -1:
                legacy = None
                for legacy in _LEGACY_SUBMIT_RE.finditer(stream):
                    pass
                attempt_at = legacy.start() if legacy else -1
            if attempt_at == -1:
                continue
            if stream.rfind(SUBMIT_CANCEL_MARKER) > attempt_at:
                continue  # the script reported that nothing was clicked
            self.mark_submit_attempted()
            return

    def observe_result(self, res: Any) -> None:
        """Reads an engine result dict for output text and for a confirmed submission."""
        if not isinstance(res, dict):
            return
        for key in ("output", "raw_output", "stdout", "log"):
            value = res.get(key)
            if isinstance(value, str):
                self.observe_output(value)
        if res.get("submitted") is True or res.get("alreadyApplied") is True:
            self.root._submit_confirmed = True

    # -- results ------------------------------------------------------------

    def blocked_result(self) -> Dict[str, Any]:
        return _blocked_result(self.reason or "DUPLICATE", self.detail, self.duplicate_of, self.job_id or None)

    def annotate(self, res: Any) -> Any:
        """Adds submit_attempted / submit_confirmed / final_status to an engine result."""
        if not isinstance(res, dict):
            return res
        self.observe_result(res)
        if res.get("duplicate") or res.get("in_progress"):
            return res
        res["submit_attempted"] = self.submit_attempted
        res["submit_confirmed"] = self.submit_confirmed
        res["final_status"] = final_status(res, self.submit)
        return res


def final_status(res: Any, submit_requested: bool) -> str:
    """
    Maps an engine result to the status the job should get.

      DUPLICATE / IN_PROGRESS  - the guard refused; nothing was done
      APPLIED                  - submit was clicked and the engine reports success,
                                 or the engine confirmed the submission
      SUBMIT_UNCONFIRMED       - submit was clicked but success was not reported
      STAGED_FOR_REVIEW        - the form was filled, submit was not clicked
      FAILED                   - nothing useful happened; safe to retry or delegate
    """
    if not isinstance(res, dict):
        return "FAILED"
    if res.get("duplicate"):
        return "DUPLICATE"
    if res.get("in_progress"):
        return "IN_PROGRESS"
    ok = bool(res.get("success"))
    confirmed = bool(res.get("submit_confirmed")) or res.get("submitted") is True or res.get("alreadyApplied") is True
    if "submit_attempted" in res:
        clicked = bool(res.get("submit_attempted"))
    else:
        # Result did not pass through a guard: fall back to what the caller asked for.
        clicked = bool(submit_requested) and ok
    if confirmed:
        return "APPLIED"
    if clicked:
        return "APPLIED" if ok else "SUBMIT_UNCONFIRMED"
    return "STAGED_FOR_REVIEW" if ok else "FAILED"


# ---------------------------------------------------------------------------
# Engine decorator
# ---------------------------------------------------------------------------

_URL_ARG_NAMES = ("url", "url_or_id", "job_url", "target_url", "apply_url")
_COMPANY_ARG_NAMES = ("company_name", "company")
_JOB_ID_ARG_NAMES = ("job_id_db", "job_id")


def guarded_apply(fn):
    """
    Decorator for apply-engine entry points. Reads url / company / title /
    job id / submit from whatever signature the engine has, runs the duplicate
    guard around the call, and annotates the result.
    """
    signature = inspect.signature(fn)

    @functools.wraps(fn)
    def wrapper(*args, **kwargs):
        try:
            bound = signature.bind_partial(*args, **kwargs)
            bound.apply_defaults()
            given = dict(bound.arguments)
        except TypeError:
            given = dict(kwargs)

        def first(names: Tuple[str, ...]) -> str:
            for name in names:
                value = given.get(name)
                if isinstance(value, str) and value.strip():
                    return value.strip()
            return ""

        url = first(_URL_ARG_NAMES)
        if not url and args and isinstance(args[0], str):
            url = args[0].strip()
        if url.isdigit() and "linkedin" in (fn.__module__ or ""):
            url = f"https://www.linkedin.com/jobs/view/{url}/"

        with ApplicationGuard(
            url=url,
            company=first(_COMPANY_ARG_NAMES),
            title=first(("title",)),
            job_id=first(_JOB_ID_ARG_NAMES),
            submit=bool(given.get("submit", False)),
            source=fn.__name__,
        ) as guard:
            if not guard.allowed:
                print(f"[Dedup] {fn.__name__} skipped - {guard.reason}: {guard.detail}")
                return guard.blocked_result()
            return guard.annotate(fn(*args, **kwargs))

    wrapper.__wrapped_apply__ = fn
    return wrapper


# ---------------------------------------------------------------------------
# subprocess hook: watch engine output for the submit marker
# ---------------------------------------------------------------------------

_ORIGINAL_RUN = subprocess.run


def _watched_run(*args, **kwargs):
    guard = current_guard()
    if guard is None:
        return _ORIGINAL_RUN(*args, **kwargs)
    guard.heartbeat()
    try:
        proc = _ORIGINAL_RUN(*args, **kwargs)
    except subprocess.TimeoutExpired as exc:
        guard.observe_output(getattr(exc, "stdout", None), getattr(exc, "stderr", None))
        raise
    guard.observe_output(getattr(proc, "stdout", None), getattr(proc, "stderr", None))
    return proc


if getattr(subprocess.run, "__name__", "") != "_watched_run":
    subprocess.run = _watched_run


# ---------------------------------------------------------------------------
# Maintenance helpers
# ---------------------------------------------------------------------------

def find_duplicate_groups() -> List[Dict[str, Any]]:
    """
    Groups rows in `jobs` that are the same job (same ATS id, same URL key, or
    same trustworthy company + title). Each group lists its rows, most advanced first.
    """
    conn = _connect()
    try:
        if not _jobs_table_exists(conn):
            return []
        sync_job_identity(conn)
        rows = conn.execute(
            "SELECT j.job_id, j.company, j.title, j.location, j.url, j.status, j.match_score, "
            "       j.applied_at, j.created_at, i.url_key, i.ats_key, i.ct_key "
            "FROM jobs j JOIN job_identity i ON i.job_id = j.job_id"
        ).fetchall()
    finally:
        conn.close()

    parent: Dict[str, str] = {}

    def find(x: str) -> str:
        while parent.setdefault(x, x) != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def union(a: str, b: str) -> None:
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[rb] = ra

    first_seen: Dict[str, str] = {}
    for row in rows:
        find(row["job_id"])
        for kind in ("url_key", "ats_key", "ct_key"):
            value = row[kind]
            if not value:
                continue
            token = f"{kind}:{value}"
            if token in first_seen:
                union(first_seen[token], row["job_id"])
            else:
                first_seen[token] = row["job_id"]

    groups: Dict[str, List[Dict[str, Any]]] = {}
    for row in rows:
        groups.setdefault(find(row["job_id"]), []).append(dict(row))

    result = []
    for members in groups.values():
        if len(members) < 2:
            continue
        members.sort(key=lambda r: (_STATUS_RANK.get(r["status"], 9), -(r["match_score"] or 0), r["created_at"] or ""))
        result.append({"keeper": members[0], "duplicates": members[1:]})
    return result


def purge_expired_claims() -> int:
    """Removes in-flight claims whose owner process is gone or whose time ran out."""
    conn = _connect()
    try:
        now = datetime.now()
        removed = 0
        for claim in conn.execute("SELECT claim_key, owner, expires_at FROM apply_claims WHERE state = 'APPLYING'").fetchall():
            expires = _parse_ts(claim["expires_at"])
            if (expires is not None and expires < now) or not _pid_alive(claim["owner"]):
                conn.execute("DELETE FROM apply_claims WHERE claim_key = ? AND state = 'APPLYING'", (claim["claim_key"],))
                removed += 1
        return removed
    finally:
        conn.close()
