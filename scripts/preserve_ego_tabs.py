#!/usr/bin/env python3
"""
Ego Lite Tab & Session Memory Preservation Helper.
Inspects active ego-browser task spaces, ensures tabs remain pinned in memory,
and configures Chromium session restore and memory saver exclusions.
"""

import sys
import json
import subprocess
from pathlib import Path

PROFILE_DIR = Path.home() / "Library/Application Support/Citro Labs/ego lite/Profile 1"
PREF_FILE = PROFILE_DIR / "Preferences"

EXCLUDED_DOMAINS = [
    "careers.microsoft.com",
    "apply.careers.microsoft.com",
    "jobs.ashbyhq.com",
    "job-boards.greenhouse.io",
    "jobs.lever.co",
    "work.mercor.com",
    "aiprise.com",
    "rippling.com",
    "stripe.com",
    "chatgpt.com"
]

def audit_ego_tabs():
    """Lists all active task spaces and tabs in ego-browser."""
    print("[*] Querying live task spaces in ego-browser...")
    cmd = ["ego-browser", "nodejs", "-e", "const s = await listTaskSpaces(); console.log(JSON.stringify(s));"]
    proc = subprocess.run(cmd, capture_output=True, text=True)
    
    output = proc.stdout + "\n" + proc.stderr
    spaces = []
    text = proc.stdout + "\n" + proc.stderr
    idx_start = text.find("[{")
    idx_end = text.rfind("}]")
    if idx_start != -1 and idx_end != -1 and idx_end > idx_start:
        try:
            spaces = json.loads(text[idx_start:idx_end+2])
        except Exception as e:
            print("Parse error:", e)

    print(f"\n[+] Found {len(spaces)} active task spaces in ego lite:")
    for s in spaces:
        print(f"  • Space #{s.get('id')} [{s.get('name') or 'Default'}] | Profile: {s.get('profileName')} | Owner: {s.get('ownership')}")
        for t in s.get("recentTabTitles", []):
            print(f"      - Tab: {t}")
    print()

def configure_session_preservation():
    """Configures session restore on startup for ego lite Profile 1."""
    if not PREF_FILE.exists():
        print(f"[!] Preferences file not found at {PREF_FILE}")
        return

    try:
        with open(PREF_FILE, "r", encoding="utf-8") as f:
            prefs = json.load(f)

        # 1. Restore on startup = 4 (Restore previous session)
        if "session" not in prefs:
            prefs["session"] = {}
        prefs["session"]["restore_on_startup"] = 4

        # 2. Add performance tuning exclusions so job portals are never discarded
        if "performance_tuning" not in prefs:
            prefs["performance_tuning"] = {}
        
        prefs["performance_tuning"]["tab_discarding"] = {
            "exceptions": EXCLUDED_DOMAINS
        }

        with open(PREF_FILE, "w", encoding="utf-8") as f:
            json.dump(prefs, f, indent=2)

        print("[✓] Configured ego lite Profile 1:")
        print("    - restore_on_startup: 4 (Always restore open tabs on relaunch)")
        print(f"    - tab_discarding exceptions added for {len(EXCLUDED_DOMAINS)} job portals")
    except Exception as e:
        print(f"[!] Warning updating preferences: {e}")

if __name__ == "__main__":
    audit_ego_tabs()
    configure_session_preservation()
