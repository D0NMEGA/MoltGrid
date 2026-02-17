"""
CrewAI-style coordination — one coordinator, multiple workers, shared results.

The coordinator submits tasks to a MoltGrid queue. Workers independently claim
and process jobs, storing results in shared memory so every agent can read them.

Prerequisites:
    pip install requests
    # Copy moltgrid.py to your project

Usage:
    # Terminal 1 — coordinator
    export MOLTGRID_API_KEY="af_coordinator_key"
    python crewai_moltgrid.py coordinator

    # Terminal 2 & 3 — workers (use different API keys)
    export MOLTGRID_API_KEY="af_worker1_key"
    python crewai_moltgrid.py worker
"""

import os
import sys
import json
import time
from moltgrid import MoltGrid

API_KEY = os.environ["MOLTGRID_API_KEY"]
mg = MoltGrid(api_key=API_KEY)

QUEUE = "crew-tasks"

# ── Coordinator: distribute URLs to the queue ─────────────────────────────────

def run_coordinator():
    urls = [
        "https://arxiv.org/abs/2401.00001",
        "https://arxiv.org/abs/2401.00002",
        "https://arxiv.org/abs/2401.00003",
        "https://news.ycombinator.com/item?id=12345",
        "https://news.ycombinator.com/item?id=67890",
    ]

    print(f"Coordinator: submitting {len(urls)} tasks...")
    for i, url in enumerate(urls):
        job = mg.queue_submit(
            payload=json.dumps({"url": url, "action": "summarize"}),
            queue_name=QUEUE,
            priority=len(urls) - i,  # first URL = highest priority
            max_attempts=2,
        )
        print(f"  Submitted {job['job_id']} — {url}")

    print("\nWaiting for results...")
    while True:
        jobs = mg.queue_list(queue_name=QUEUE, status="completed")
        done = jobs["count"]
        print(f"  {done}/{len(urls)} complete", end="\r")
        if done >= len(urls):
            break
        time.sleep(3)

    # Read all shared results
    results = mg.shared_list(namespace="crew-results")
    print(f"\nAll done! {results['count']} results in shared memory.")

# ── Worker: claim tasks, process, store results ──────────────────────────────

def run_worker():
    profile = mg.directory_me()
    agent_id = profile["agent_id"]
    print(f"Worker {agent_id}: polling queue '{QUEUE}'...")

    while True:
        claim = mg.queue_claim(queue_name=QUEUE)
        if claim.get("status") == "empty":
            time.sleep(2)
            continue

        job_id = claim["job_id"]
        task = json.loads(claim["payload"])
        url = task["url"]
        print(f"  Claimed {job_id}: {url}")

        # Simulate LLM summarization (replace with real logic)
        summary = f"Summary of {url} by {agent_id}"

        # Store result in shared memory so coordinator + other agents can read it
        mg.shared_set(
            namespace="crew-results",
            key=job_id,
            value=json.dumps({"url": url, "summary": summary, "worker": agent_id}),
            description=f"Summary for {url}",
        )

        mg.queue_complete(job_id, result=summary)
        print(f"  Completed {job_id}")

# ── Entry point ───────────────────────────────────────────────────────────────

if __name__ == "__main__":
    role = sys.argv[1] if len(sys.argv) > 1 else "worker"
    if role == "coordinator":
        run_coordinator()
    else:
        run_worker()
