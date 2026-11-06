import time
import json
import random
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, Any

from engine.config import DATA_DIR, CYCLE_INTERVAL_HOURS, CYCLE_JITTER_HOURS
from engine.scraper import run_parallel_scraper
from engine.evaluator import run_evaluation_pipeline
from engine.db import init_db, update_text_summary

TARGET_WEBSITES_FILE = DATA_DIR / "target_websites.json"

def load_target_websites() -> Dict[str, Any]:
    if TARGET_WEBSITES_FILE.exists():
        with open(TARGET_WEBSITES_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return {}

def run_single_scrape_and_eval_cycle():
    """Executes one complete cycle: Scrape -> Light Evaluate -> AI Consultation -> Dispatch/Stage -> Watch Submissions."""
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    print("\n" + "=" * 70)
    print(f"[*] STARTING SCHEDULED MONITORING CYCLE AT {now_str}")
    print("=" * 70)

    from cli import cmd_pipeline
    from engine.maintenance import flush_system_and_memory
    class Args:
        workers = 8
        limit = 3
    cmd_pipeline(Args())

    # Flush RAM, WAL, and re-arm hardware state
    flush_system_and_memory()

    print(f"[*] Cycle finished at {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}.\n")

def run_periodic_daemon(interval_hours: float = CYCLE_INTERVAL_HOURS, max_cycles: int = 5):
    """
    Runs the scraper periodically 5 times per day (every ~4.8 hours).
    Applies +/- 1.0 hour random jitter between cycles to prevent anti-bot rate limits and detection.
    """
    print(f"[*] Starting Job Finder 5x/day daemon (base interval: {interval_hours} hours with +/- {CYCLE_JITTER_HOURS}h jitter)...")
    cycle = 1
    while cycle <= max_cycles:
        print(f"\n---> Cycle {cycle} of {max_cycles}")
        run_single_scrape_and_eval_cycle()
        if cycle < max_cycles:
            base_seconds = interval_hours * 3600
            jitter_seconds = random.uniform(-CYCLE_JITTER_HOURS * 3600, CYCLE_JITTER_HOURS * 3600)
            actual_sleep = max(3600, int(base_seconds + jitter_seconds))
            next_run_dt = datetime.now() + timedelta(seconds=actual_sleep)
            print(f"[*] Sleeping for {actual_sleep/3600:.2f} hours ({actual_sleep}s) with jitter.")
            print(f"[*] Next monitoring cycle scheduled at: {next_run_dt.strftime('%Y-%m-%d %H:%M:%S')}")
            time.sleep(actual_sleep)
        cycle += 1
    print("[*] Completed scheduled monitoring runs for the day.")

if __name__ == "__main__":
    run_single_scrape_and_eval_cycle()
