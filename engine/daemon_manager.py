#!/usr/bin/env python3
"""
Autonomous 24/7 Daemon Manager for Job Finder & Applier Platform.
Coordinates:
1. Periodic Sourcing & Staging (every ~4.5 hours with jitter to prevent anti-bot detection).
2. Continuous ego-browser Submission Watcher (checks every 10 seconds for user 1-click submits).
3. Automated Hardware & Memory Maintenance Flush (after every cycle & every 6 hours).
"""

import sys
import time
import random
import signal
from datetime import datetime, timedelta
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from engine.config import CYCLE_INTERVAL_HOURS, CYCLE_JITTER_HOURS
from engine.scheduler import run_single_scrape_and_eval_cycle
from engine.submission_watcher import check_and_process_submissions
from engine.maintenance import flush_system_and_memory
from engine.db import update_text_summary

RUNNING = True

def signal_handler(sig, frame):
    global RUNNING
    print("\n[*] Received shutdown signal. Gracefully stopping daemon...")
    RUNNING = False

def calculate_next_cycle_seconds(base_hours: float, jitter_hours: float) -> int:
    base_sec = base_hours * 3600
    jitter_sec = random.uniform(-jitter_hours * 3600, jitter_hours * 3600)
    return max(1800, int(base_sec + jitter_sec))

def run_247_autonomous_daemon(
    interval_hours: float = CYCLE_INTERVAL_HOURS,
    jitter_hours: float = CYCLE_JITTER_HOURS,
    watcher_interval_sec: float = 10.0,
    run_immediate_cycle: bool = True
):
    """
    Main 24/7 autonomous loop designed for zero CPU waste and hardware preservation.
    Features:
    - Zero CPU idle: short-circuits in <1ms when no jobs are staged.
    - Automatic sleep/wake detection: runs catch-up cycle only when wake gap exceeds missed interval.
    - Rate-paced background watcher polling every 30 seconds.
    - Periodic memory and hardware maintenance flushes.
    """
    global RUNNING
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)

    print("\n" + "=" * 75)
    print("🚀 STARTING 24/7 AUTONOMOUS JOB FINDER & APPLIER DAEMON")
    print(f"[*] Base scrape interval: {interval_hours:.1f} hours (+/- {jitter_hours:.1f}h jitter)")
    print(f"[*] Submission watcher check interval: {watcher_interval_sec} seconds")
    print(f"[*] Immediate startup run: {'ENABLED' if run_immediate_cycle else 'DISABLED'}")
    print("=" * 75)

    # Initial hardware & memory flush
    flush_system_and_memory(verbose=True)

    if run_immediate_cycle:
        print("[*] Running initial immediate monitoring cycle upon daemon start...")
        try:
            run_single_scrape_and_eval_cycle()
        except Exception as e:
            print(f"[!] Warning: Initial cycle error: {e}")

    next_cycle_sec = calculate_next_cycle_seconds(interval_hours, jitter_hours)
    next_cycle_dt = datetime.now() + timedelta(seconds=next_cycle_sec)
    print(f"[*] Next full scraping & staging cycle at: {next_cycle_dt.strftime('%Y-%m-%d %H:%M:%S')}")

    last_cycle_time = time.time()
    last_flush_time = time.time()
    last_watch_time = 0
    last_queue_time = 0
    last_wall_clock = datetime.now()

    try:
        while RUNNING:
            now = time.time()
            wall_now = datetime.now()

            # 0. System Wake / Sleep Detection (detects elapsed time during Mac sleep / lid closed)
            gap = (wall_now - last_wall_clock).total_seconds()
            if gap > 1800.0:
                print(f"\n[!] System Wake / Mac Resume Detected ({gap:.1f}s elapsed during sleep).")
                print("[*] Auto-running search & evaluation upon system wake...")
                try:
                    run_single_scrape_and_eval_cycle()
                except Exception as e:
                    print(f"[!] Error during wake cycle: {e}")
                last_cycle_time = time.time()
                next_cycle_sec = calculate_next_cycle_seconds(interval_hours, jitter_hours)
                next_cycle_dt = datetime.now() + timedelta(seconds=next_cycle_sec)
                last_wall_clock = datetime.now()
                print(f"[*] Wake cycle complete. Next cycle scheduled at: {next_cycle_dt.strftime('%Y-%m-%d %H:%M:%S')}\n")
            else:
                last_wall_clock = wall_now

            # 1. Submission Watcher Check (every watcher_interval_sec)
            if now - last_watch_time >= watcher_interval_sec:
                try:
                    applied = check_and_process_submissions()
                    if applied:
                        print(f"[{datetime.now().strftime('%H:%M:%S')}] Archived and updated {len(applied)} submissions.")
                except Exception as e:
                    # Non-fatal error during watcher check
                    pass
                last_watch_time = now

            # 1b. Reactive Pipeline Queue Worker (Auto-evaluates DISCOVERED & auto-applies priority EVALUATED every 30s)
            if now - last_queue_time >= 30.0:
                try:
                    from engine.pipeline import process_pending_jobs_queue
                    dispatched_items = process_pending_jobs_queue(limit=5, auto_submit=True)
                    if dispatched_items:
                        print(f"[{datetime.now().strftime('%H:%M:%S')}] ⚡ Auto-Pipeline Queue: processed {len(dispatched_items)} priority jobs.")
                except Exception as e:
                    pass
                last_queue_time = now

            # 2. Periodic Scrape & Staging Cycle Check
            if now - last_cycle_time >= next_cycle_sec or wall_now >= next_cycle_dt:
                print(f"\n[*] Triggering scheduled monitoring cycle at {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}...")
                try:
                    run_single_scrape_and_eval_cycle()
                except Exception as e:
                    print(f"[!] Error during monitoring cycle: {e}")

                last_cycle_time = time.time()
                next_cycle_sec = calculate_next_cycle_seconds(interval_hours, jitter_hours)
                next_cycle_dt = datetime.now() + timedelta(seconds=next_cycle_sec)
                last_wall_clock = datetime.now()
                print(f"[*] Cycle complete. Next cycle scheduled at: {next_cycle_dt.strftime('%Y-%m-%d %H:%M:%S')}\n")

            # 3. Hardware Flush Check (Every 6 hours)
            if now - last_flush_time >= 21600:
                flush_system_and_memory(verbose=False)
                last_flush_time = now

            # Sleep to yield CPU completely to OS (zero spin-lock overhead)
            time.sleep(min(watcher_interval_sec, 5.0))

    except KeyboardInterrupt:
        pass
    finally:
        print("\n[*] Running final hardware flush before exit...")
        flush_system_and_memory(verbose=True)
        print("[✓] Autonomous daemon stopped cleanly.")

if __name__ == "__main__":
    run_247_autonomous_daemon()
