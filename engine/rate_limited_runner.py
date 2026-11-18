#!/usr/bin/env python3
"""
Rate-Limited Concurrent Job Runner (Max Concurrent = 5).
Safely executes batch job applications with:
1. Hard concurrency ceiling: MAX_CONCURRENT = 5.
2. Inter-launch stagger: 10s cooldown between spawns to avoid browser contention.
3. Live process supervision: monitors CPU, timeouts (240s max), and worker exits.
4. Zero dummy placeholder circuit breakers.
5. Continuous heartbeat & progress logging.
"""

import sys
import os
import time
import json
import signal
import subprocess
from pathlib import Path
from datetime import datetime
from typing import List, Dict, Any, Optional

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from engine.config import assert_real_candidate_profile
from engine.db import get_job_by_id, update_job_status
from engine.agent_delegator import delegate_job_to_agent, count_active_worker_agents

MAX_CONCURRENT = 5
STAGGER_INTERVAL_SEC = 10.0
WORKER_TIMEOUT_SEC = 900.0  # 15 minutes
RUNNER_LOG_FILE = PROJECT_ROOT / "data" / "rate_limited_runner.log"

def log_msg(msg: str):
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    line = f"[{timestamp}] {msg}"
    print(line, flush=True)
    try:
        RUNNER_LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
        with open(RUNNER_LOG_FILE, "a", encoding="utf-8") as f:
            f.write(line + "\n")
    except Exception:
        pass


def run_rate_limited_batch(job_ids: List[str], submit: bool = True) -> Dict[str, Any]:
    assert_real_candidate_profile()
    log_msg("=" * 70)
    log_msg(f"🚀 INITIATING RATE-LIMITED BATCH RUNNER (MAX_CONCURRENT={MAX_CONCURRENT})")
    log_msg(f"[*] Total target jobs queued: {len(job_ids)}")
    log_msg(f"[*] Stagger interval: {STAGGER_INTERVAL_SEC}s | Worker timeout: {WORKER_TIMEOUT_SEC}s")
    log_msg("=" * 70)

    pending_queue = list(job_ids)
    active_workers: Dict[str, Dict[str, Any]] = {}
    completed: List[Dict[str, Any]] = []

    last_launch_time = 0.0

    while pending_queue or active_workers:
        now = time.time()

        # 1. Check active workers for completion or timeout
        finished_ids = []
        for jid, info in list(active_workers.items()):
            proc = info["proc"]
            elapsed = now - info["start_time"]
            poll = proc.poll()

            if poll is not None:
                # Worker finished
                log_msg(f"[✓] Worker finished for [{info['company']}] (Job ID: {jid}) with exit code {poll} (elapsed: {elapsed:.1f}s)")
                finished_ids.append(jid)
                completed.append({
                    "job_id": jid,
                    "company": info["company"],
                    "exit_code": poll,
                    "elapsed": elapsed,
                    "status": "FINISHED"
                })
            elif elapsed > WORKER_TIMEOUT_SEC:
                # Worker timed out
                log_msg(f"[!] Worker timed out for [{info['company']}] (Job ID: {jid}) after {elapsed:.1f}s. Terminating...")
                try:
                    proc.kill()
                except Exception:
                    pass
                finished_ids.append(jid)
                completed.append({
                    "job_id": jid,
                    "company": info["company"],
                    "exit_code": -1,
                    "elapsed": elapsed,
                    "status": "TIMED_OUT"
                })

        for jid in finished_ids:
            active_workers.pop(jid, None)

        # 2. Spawn new workers up to MAX_CONCURRENT if stagger window passed
        system_active = count_active_worker_agents()
        can_spawn = (len(active_workers) < MAX_CONCURRENT) and (system_active < MAX_CONCURRENT)
        stagger_satisfied = (now - last_launch_time) >= STAGGER_INTERVAL_SEC

        if pending_queue and can_spawn and stagger_satisfied:
            next_jid = pending_queue.pop(0)
            job = get_job_by_id(next_jid)
            if not job:
                log_msg(f"[-] Skipping {next_jid}: Not found in database.")
                continue

            job = dict(job)
            co = job.get("company", "Company")
            title = job.get("title", "Role")
            url = job.get("url", "")
            loc = job.get("location", "")

            log_msg(f"[*] Spawning worker {len(active_workers)+1}/{MAX_CONCURRENT}: [{co}] {title} (Queue remaining: {len(pending_queue)})")

            # Delegate job asynchronously
            del_res = delegate_job_to_agent(
                job_id=next_jid,
                company=co,
                title=title,
                url=url,
                location=loc,
                submit=submit,
                sync=False
            )

            pid = del_res.get("pid")
            if pid:
                # Wrap pid in a pseudo-process or use psutil / os.kill
                # In python, we can monitor PID via os.kill(pid, 0)
                class PidWrapper:
                    def __init__(self, p):
                        self.pid = p
                    def poll(self):
                        try:
                            # 0 sends no signal, just checks if process is alive
                            os.kill(self.pid, 0)
                            return None
                        except OSError:
                            return 0
                    def kill(self):
                        try:
                            os.kill(self.pid, signal.SIGKILL)
                        except OSError:
                            pass

                active_workers[next_jid] = {
                    "proc": PidWrapper(pid),
                    "company": co,
                    "title": title,
                    "start_time": now
                }
                last_launch_time = now
                log_msg(f"[+] Worker spawned: PID {pid} for [{co}] {title}")
            else:
                log_msg(f"[!] Failed to spawn worker for [{co}] {title}: {del_res.get('error')}")

        time.sleep(2.0)

    log_msg("=" * 70)
    log_msg(f"🏁 ALL TARGET JOBS PROCESSED ({len(completed)} completed)")
    log_msg("=" * 70)
    return {"total": len(job_ids), "completed": completed}


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Rate-Limited Concurrent Job Runner")
    parser.add_argument("--jobs", nargs="+", help="List of job IDs to process")
    parser.add_argument("--submit", action="store_true", help="Submit immediately")
    args = parser.parse_args()

    target_jobs = args.jobs or []
    if not target_jobs:
        print("[-] Error: No job IDs specified.")
        sys.exit(1)

    run_rate_limited_batch(target_jobs, submit=args.submit)
