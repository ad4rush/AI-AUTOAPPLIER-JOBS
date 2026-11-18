#!/usr/bin/env python3
"""
Autonomous Multi-Account Vault & Quota Manager for Antigravity (AGY) CLI.
Parses `/usage` output, tracks five-hour and weekly Gemini/Claude limits,
manages vaulted OAuth tokens across multiple accounts,
and enables zero-downtime intelligent account rotation and refill-scheduled wakeups.
"""

import sys
import os
import re
import json
import base64
import shutil
import subprocess
import tempfile
from contextlib import contextmanager
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, Any, List, Optional, Tuple

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

GEMINI_DIR = Path.home() / ".gemini" / "antigravity-cli"
ACTIVE_TOKEN_FILE = GEMINI_DIR / "antigravity-oauth-token"
VAULT_DIR = GEMINI_DIR / "accounts_vault"
VAULT_DIR.mkdir(parents=True, exist_ok=True)
AGY_BIN = shutil.which("agy") or str(Path.home() / ".local/bin/agy")
from engine.config import CANDIDATE_PERSONAL_EMAIL

PRIMARY_REMOTE_CONTROL_ACCOUNT = os.getenv("AGY_PRIMARY_ACCOUNT", CANDIDATE_PERSONAL_EMAIL)


def get_keychain_token_data() -> Optional[Dict[str, Any]]:
    """Reads the AGY OAuth credentials currently stored in macOS Keychain."""
    try:
        out = subprocess.check_output(
            ["security", "find-generic-password", "-s", "gemini", "-a", "antigravity", "-w"],
            stderr=subprocess.DEVNULL
        ).decode().strip()
        if out.startswith("go-keyring-base64:"):
            raw_b64 = out[len("go-keyring-base64:"):]
            decoded = base64.b64decode(raw_b64).decode()
            return json.loads(decoded)
    except Exception:
        pass
    return None


def set_keychain_token_data(token_dict: Dict[str, Any]) -> bool:
    """Updates the AGY OAuth credentials in macOS Keychain."""
    try:
        raw_json = json.dumps(token_dict)
        b64_val = base64.b64encode(raw_json.encode()).decode()
        payload = f"go-keyring-base64:{b64_val}"
        subprocess.run(
            ["security", "add-generic-password", "-U", "-s", "gemini", "-a", "antigravity", "-w", payload],
            check=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL
        )
        return True
    except (OSError, subprocess.SubprocessError):
        print("[QuotaManager] Warning: failed to update macOS Keychain.")
        return False


def get_active_account_email() -> str:
    """Returns the email address of the currently active AGY OAuth session (from Keychain or token file)."""
    kc = get_keychain_token_data()
    if kc and kc.get("id_token_email"):
        return kc.get("id_token_email")

    if not ACTIVE_TOKEN_FILE.exists():
        return "UNKNOWN (no token file)"
    try:
        with open(ACTIVE_TOKEN_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
            return data.get("id_token_email", "UNKNOWN")
    except Exception as e:
        return f"ERROR: {e}"


def check_quota(timeout_sec: int = 25) -> Dict[str, Any]:
    """
    Executes `agy -p '/usage'` non-interactively and extracts exact quotas and reset timestamps.
    Returns structured dict with credit percentages and parsed refill datetimes.
    """
    email = get_active_account_email()
    try:
        proc = subprocess.run(
            [AGY_BIN, "-p", "/usage"],
            capture_output=True,
            text=True,
            timeout=timeout_sec
        )
        output = (proc.stdout or "") + "\n" + (proc.stderr or "")
        if proc.returncode != 0:
            raise RuntimeError(f"AGY /usage exited with code {proc.returncode}")
    except Exception as e:
        return {
            "success": False,
            "error": str(e),
            "account": email,
            "gemini_5h_pct": 0,
            "can_deploy": False
        }

    res = {
        "success": True,
        "account": email,
        "raw_output": output.strip(),
        "gemini_5h_pct": 0,
        "gemini_5h_reset_str": "",
        "gemini_5h_reset_dt": None,
        "gemini_5h_seconds_to_refill": 0,
        "gemini_weekly_pct": 0,
        "gemini_weekly_reset_str": "",
        "claude_5h_pct": 0,
        "claude_5h_reset_str": "",
        "claude_weekly_pct": 0,
        "can_deploy": False
    }

    # Example outputs:
    # TSV mode: 'Gemini Models\tFive Hour Limit Remaining\t25%\t2026-11-18T00:15:14Z'
    # Human mode: 'Gemini Models  Five Hour Limit Remaining  25%   2026-11-18 05:45 IST'

    found_gemini_5h = False
    found_gemini_weekly = False
    for line in output.splitlines():
        line_clean = line.strip()
        if not line_clean:
            continue

        pct_m = re.search(r"(\d+(?:\.\d+)?)\s*%", line_clean)
        if not pct_m:
            continue
        pct = float(pct_m.group(1))

        # Extract timestamp (either ISO or human date)
        ts_m = re.search(r"(\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z|\d{4}-\d{2}-\d{2}\s+\d{2}:\d{2}\s+[A-Z]+)", line_clean)
        ts_str = ts_m.group(1) if ts_m else ""

        if "Gemini Models" in line_clean and "Five Hour Limit Remaining" in line_clean:
            found_gemini_5h = True
            res["gemini_5h_pct"] = pct
            res["gemini_5h_reset_str"] = ts_str
        elif "Gemini Models" in line_clean and "Weekly Limit Remaining" in line_clean:
            found_gemini_weekly = True
            res["gemini_weekly_pct"] = pct
            res["gemini_weekly_reset_str"] = ts_str
        elif "Claude and GPT" in line_clean and "Five Hour Limit Remaining" in line_clean:
            res["claude_5h_pct"] = pct
            res["claude_5h_reset_str"] = ts_str
        elif "Claude and GPT" in line_clean and "Weekly Limit Remaining" in line_clean:
            res["claude_weekly_pct"] = pct
            res["claude_weekly_reset_str"] = ts_str

    # Compute seconds to refill and convert to local IST
    if res["gemini_5h_reset_str"]:
        try:
            raw_ts = res["gemini_5h_reset_str"]
            if "T" in raw_ts and raw_ts.endswith("Z"):
                # UTC ISO format: 2026-11-18T00:15:14Z
                dt_utc = datetime.strptime(raw_ts, "%Y-%m-%dT%H:%M:%SZ")
                # Local IST is UTC + 5:30
                dt_local = dt_utc + timedelta(hours=5, minutes=30)
                res["gemini_5h_local_refill_str"] = dt_local.strftime("%Y-%m-%d %H:%M:%S IST")

                # Compare in UTC
                now_utc = datetime.utcnow()
                diff_sec = max(0, int((dt_utc - now_utc).total_seconds()))
                res["gemini_5h_seconds_to_refill"] = diff_sec
                res["gemini_5h_reset_dt"] = dt_local.isoformat()
            else:
                dt_part = raw_ts.replace(" IST", "")
                dt_local = datetime.strptime(dt_part, "%Y-%m-%d %H:%M")
                res["gemini_5h_local_refill_str"] = raw_ts
                diff_sec = max(0, int((dt_local - datetime.now()).total_seconds()))
                res["gemini_5h_seconds_to_refill"] = diff_sec
                res["gemini_5h_reset_dt"] = dt_local.isoformat()
        except Exception as ex:
            res["parse_error"] = str(ex)

    res["success"] = found_gemini_5h
    if not found_gemini_5h:
        res["error"] = "Gemini five-hour quota row missing from AGY /usage output"
    res["can_deploy"] = (
        found_gemini_5h
        and res["gemini_5h_pct"] >= 15
        and (not found_gemini_weekly or res["gemini_weekly_pct"] > 0)
    )
    return res


def vault_current_account(custom_label: Optional[str] = None) -> Dict[str, Any]:
    """
    Saves the currently active AGY CLI OAuth session token (from Keychain or token file) into the persistent vault.
    Saves both by email and optional custom label (e.g. 'main', 'college').
    """
    data = get_keychain_token_data()
    if not data and ACTIVE_TOKEN_FILE.exists():
        try:
            with open(ACTIVE_TOKEN_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
        except Exception:
            pass

    if not data:
        return {"success": False, "error": "No active AGY OAuth session token found on disk or in macOS Keychain"}

    try:
        email = data.get("id_token_email")
        if not email or not data.get("token"):
            return {"success": False, "error": "Active session is missing its identity or OAuth credentials"}
        email_clean = re.sub(r"[^a-zA-Z0-9_.@-]", "_", email.lower())
        dest = VAULT_DIR / f"{email_clean}.json"
        label_path = None
        if custom_label:
            lbl_clean = re.sub(r"[^a-zA-Z0-9_-]", "_", custom_label.lower())
            label_path = VAULT_DIR / f"{lbl_clean}.json"
        for path in (dest, label_path):
            if path is None:
                continue
            with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=VAULT_DIR, delete=False) as staged:
                staged_path = Path(staged.name)
                try:
                    json.dump(data, staged, indent=2)
                    staged.close()
                    staged_path.replace(path)
                finally:
                    staged_path.unlink(missing_ok=True)

        return {
            "success": True,
            "email": email,
            "vault_path": str(dest),
            "label_path": str(label_path) if label_path else None
        }
    except Exception as e:
        return {"success": False, "error": str(e)}


def list_vaulted_accounts() -> List[Dict[str, Any]]:
    """Lists all accounts stored in the accounts vault."""
    accounts = []
    active_email = get_active_account_email().lower()

    for item in sorted(VAULT_DIR.glob("*.json")):
        try:
            with open(item, "r", encoding="utf-8") as f:
                data = json.load(f)
            email = data.get("id_token_email", item.stem)
            tok = data.get("token", {})
            expiry = tok.get("expiry", "Unknown") if isinstance(tok, dict) else "Unknown"
            accounts.append({
                "file_name": item.name,
                "email": email,
                "is_active": (email.lower() == active_email),
                "expiry": expiry,
                "path": str(item)
            })
        except Exception:
            continue
    return accounts


def switch_to_account(identifier: str) -> Dict[str, Any]:
    """
    Switches active AGY authentication to a vaulted account by email or filename.
    Atomically writes to both `~/.gemini/antigravity-cli/antigravity-oauth-token`
    and the macOS Keychain so `agy` picks it up immediately.
    """
    id_lower = identifier.lower().strip()
    if not id_lower or Path(id_lower).name != id_lower or id_lower in {".", ".."}:
        return {"success": False, "error": "A valid account email or vault label is required"}
    target_file = None

    # Exact filename match
    candidate1 = VAULT_DIR / id_lower
    candidate2 = VAULT_DIR / f"{id_lower}.json"
    if candidate1.exists():
        target_file = candidate1
    elif candidate2.exists():
        target_file = candidate2
    else:
        # Match by email inside json
        for item in VAULT_DIR.glob("*.json"):
            try:
                with open(item, "r", encoding="utf-8") as f:
                    data = json.load(f)
                email = data.get("id_token_email", "").lower()
                if id_lower in email or id_lower in item.stem.lower():
                    target_file = item
                    break
            except Exception:
                continue

    if not target_file or not target_file.exists():
        available = [f.stem for f in VAULT_DIR.glob("*.json")]
        return {
            "success": False,
            "error": f"Account '{identifier}' not found in vault. Available: {available}"
        }

    try:
        with open(target_file, "r", encoding="utf-8") as f:
            target_data = json.load(f)

        new_email = target_data.get("id_token_email")
        if not new_email or not target_data.get("token"):
            return {"success": False, "error": "Vault entry is missing its identity or OAuth credentials"}

        previous_keychain = get_keychain_token_data()
        staged_path = None
        try:
            with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=ACTIVE_TOKEN_FILE.parent, delete=False) as staged:
                staged_path = Path(staged.name)
                json.dump(target_data, staged)
            if not set_keychain_token_data(target_data):
                return {"success": False, "error": "Could not update macOS Keychain"}
            try:
                staged_path.replace(ACTIVE_TOKEN_FILE)
            except OSError:
                if previous_keychain is None or not set_keychain_token_data(previous_keychain):
                    return {"success": False, "error": "Token file update failed and Keychain could not be restored"}
                raise
        finally:
            if staged_path is not None:
                staged_path.unlink(missing_ok=True)

        return {
            "success": True,
            "switched_to": new_email,
            "source_vault": target_file.name
        }
    except Exception as e:
        return {"success": False, "error": str(e)}


def ensure_remote_control_account() -> Dict[str, Any]:
    """
    Locks and restores the primary account in both
    the active token file and macOS Keychain to guarantee Remote Control never fails.
    """
    return switch_to_account(PRIMARY_REMOTE_CONTROL_ACCOUNT)


@contextmanager
def temporary_account(identifier: str):
    """
    Context manager that temporarily switches to a secondary account
    for batch operations or quota checks,
    and ALWAYS restores the primary Remote Control account upon exit.
    """
    try:
        result = switch_to_account(identifier)
        if not result.get("success"):
            raise RuntimeError(result["error"])
        yield
    finally:
        ensure_remote_control_account()


def check_all_accounts_quota() -> List[Dict[str, Any]]:
    """
    Checks the quota for every vaulted account in turn,
    and ALWAYS ensures the primary Remote Control account
    is restored as active at the conclusion.
    """
    vaulted = list_vaulted_accounts()
    seen_emails = set()
    results = []

    for acc in vaulted:
        email = acc["email"].lower()
        if email in seen_emails:
            continue
        seen_emails.add(email)

        print(f"[QuotaManager] Inspecting quota for vaulted account: {acc['file_name']} ({acc['email']})...")
        switch_res = switch_to_account(acc["file_name"])
        if not switch_res.get("success"):
            results.append({
                "account": acc["email"],
                "file_name": acc["file_name"],
                "success": False,
                "error": switch_res.get("error")
            })
            continue

        q = check_quota()
        results.append({
            "account": q.get("account", acc["email"]),
            "file_name": acc["file_name"],
            "success": q.get("success", False),
            "gemini_5h_pct": q.get("gemini_5h_pct", 0),
            "gemini_5h_refill": q.get("gemini_5h_local_refill_str", q.get("gemini_5h_reset_str", "")),
            "gemini_5h_seconds_to_refill": q.get("gemini_5h_seconds_to_refill", 0),
            "gemini_weekly_pct": q.get("gemini_weekly_pct", 0),
            "gemini_weekly_reset": q.get("gemini_weekly_reset_str", ""),
            "claude_5h_pct": q.get("claude_5h_pct", 0),
            "claude_weekly_pct": q.get("claude_weekly_pct", 0),
            "can_deploy": q.get("can_deploy", False)
        })

    # MANDATORY: Always restore the primary account for Remote Control
    restored = ensure_remote_control_account()
    if restored.get("success"):
        print(f"[QuotaManager] Restored primary account ({PRIMARY_REMOTE_CONTROL_ACCOUNT}) for continuous Remote Control.")
    else:
        print(f"[QuotaManager] Could not restore primary account: {restored.get('error')}")
    return results


def ensure_quota_or_rotate(min_pct: int = 15) -> Dict[str, Any]:
    """
    Intelligently checks current active account quota.
    If >= min_pct, proceeds immediately.
    If < min_pct, attempts to rotate through other vaulted accounts to find one with quota.
    If all accounts are depleted, returns the earliest refill time across all accounts.
    """
    cur_quota = check_quota()
    if cur_quota.get("can_deploy") and cur_quota.get("gemini_5h_pct", 0) >= min_pct:
        return {
            "can_deploy": True,
            "account": cur_quota["account"],
            "gemini_5h_pct": cur_quota["gemini_5h_pct"],
            "switched": False,
            "message": f"Active account {cur_quota['account']} has {cur_quota['gemini_5h_pct']}% credits remaining (>= {min_pct}%)."
        }

    print(f"\n[QuotaManager] Active account {cur_quota.get('account')} has only {cur_quota.get('gemini_5h_pct', 0)}% credits (Threshold: {min_pct}%).")
    print("[QuotaManager] Checking other vaulted accounts for available quota...")

    vaulted = list_vaulted_accounts()
    tested_accounts = []
    current_acc_email = cur_quota.get("account", "").lower()
    seen_emails = {current_acc_email}

    for acc in vaulted:
        email = acc["email"].lower()
        if email in seen_emails:
            continue

        print(f"[QuotaManager] Attempting switch to vaulted account: {acc['email']}...")
        switch_res = switch_to_account(acc["file_name"])
        if not switch_res.get("success"):
            continue
        seen_emails.add(email)

        quota_test = check_quota()
        if (quota_test.get("account") or "").lower() != email:
            print(f"[QuotaManager] Active identity did not match vaulted account {acc['email']}.")
            continue
        tested_accounts.append({
            "email": quota_test.get("account"),
            "pct": quota_test.get("gemini_5h_pct", 0),
            "reset_str": quota_test.get("gemini_5h_reset_str", ""),
            "local_refill_str": quota_test.get("gemini_5h_local_refill_str", quota_test.get("gemini_5h_reset_str", "")),
            "seconds_to_refill": quota_test.get("gemini_5h_seconds_to_refill", 0)
        })

        if quota_test.get("can_deploy") and quota_test.get("gemini_5h_pct", 0) >= min_pct:
            print(f"[+] Found account with sufficient credits: {quota_test['account']} ({quota_test['gemini_5h_pct']}%)")
            return {
                "can_deploy": True,
                "account": quota_test["account"],
                "gemini_5h_pct": quota_test["gemini_5h_pct"],
                "switched": True,
                "message": f"Switched to {quota_test['account']} with {quota_test['gemini_5h_pct']}% credits."
            }

    # All accounts depleted: find minimum positive refill time among tested accounts
    candidate_refills = []
    if cur_quota.get("gemini_5h_seconds_to_refill", 0) > 0:
        candidate_refills.append((
            cur_quota["gemini_5h_seconds_to_refill"],
            cur_quota.get("gemini_5h_local_refill_str") or cur_quota.get("gemini_5h_reset_str", "")
        ))

    for acc_res in tested_accounts:
        sec = acc_res.get("seconds_to_refill", 0)
        if sec > 0:
            candidate_refills.append((
                sec,
                acc_res.get("local_refill_str") or acc_res.get("reset_str", "")
            ))

    if candidate_refills:
        candidate_refills.sort(key=lambda x: x[0])
        earliest_refill_sec, earliest_reset_str = candidate_refills[0]
    else:
        earliest_refill_sec = 3600
        earliest_reset_str = "in ~60 minutes"

    # Always ensure Remote Control account is restored
    ensure_remote_control_account()

    return {
        "can_deploy": False,
        "account": cur_quota.get("account"),
        "gemini_5h_pct": cur_quota.get("gemini_5h_pct", 0),
        "switched": False,
        "earliest_refill_seconds": earliest_refill_sec,
        "earliest_refill_time_str": earliest_reset_str,
        "tested_accounts": tested_accounts,
        "message": f"All accounts are currently low on credits. Earliest refill at {earliest_reset_str} (in {earliest_refill_sec // 60} minutes)."
    }


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="AGY Quota & Multi-Account Rotation Manager")
    parser.add_argument("--usage", action="store_true", help="Print current account quota")
    parser.add_argument("--vault", action="store_true", help="Save current active token into vault")
    parser.add_argument("--label", help="Custom label when vaulting")
    parser.add_argument("--list", action="store_true", help="List all vaulted accounts")
    parser.add_argument("--switch", help="Switch to account by email or filename")
    parser.add_argument("--check-deploy", action="store_true", help="Check if ready to deploy or rotate")

    args = parser.parse_args()

    if args.vault:
        res = vault_current_account(args.label)
        print(json.dumps(res, indent=2))
    elif args.list:
        accs = list_vaulted_accounts()
        print(f"\n=======================================================")
        print(f"  VAULTED ANTIGRAVITY ACCOUNTS ({len(accs)} total)")
        print(f"=======================================================")
        for a in accs:
            mark = "👉 [ACTIVE]" if a["is_active"] else "   [SAVED] "
            print(f"{mark} {a['email']} (File: {a['file_name']})")
        print("=======================================================\n")
    elif args.switch:
        res = switch_to_account(args.switch)
        print(json.dumps(res, indent=2))
    elif args.check_deploy:
        res = ensure_quota_or_rotate()
        print(json.dumps(res, indent=2, default=str))
    else:
        q = check_quota()
        print(f"\n=======================================================")
        print(f"  ACTIVE ACCOUNT QUOTA: {q.get('account')}")
        print(f"=======================================================")
        print(f"- Gemini 5-Hour Limit Remaining:  {q.get('gemini_5h_pct')}%")
        print(f"- Gemini 5-Hour Refill Time:      {q.get('gemini_5h_local_refill_str', q.get('gemini_5h_reset_str'))} (in {q.get('gemini_5h_seconds_to_refill', 0)//60}m {q.get('gemini_5h_seconds_to_refill', 0)%60}s)")
        print(f"- Gemini Weekly Limit Remaining:  {q.get('gemini_weekly_pct')}%")
        print(f"- Claude & GPT 5-Hour Limit:      {q.get('claude_5h_pct')}%")
        print(f"- Ready to Deploy Workers:        {'✅ YES' if q.get('can_deploy') else '❌ NO (Credits Low)'}")
        print(f"=======================================================\n")
