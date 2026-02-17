"""
AgentWorker — production-ready worker loop with heartbeat, retries, and
clean shutdown.

This is the reusable pattern for any MoltGrid-backed agent. Subclass
AgentWorker or pass a callback to process jobs from any queue with:
  - Automatic heartbeat (background thread, 30s interval)
  - Retry-aware job failure (queue_fail on exception -> dead-letter)
  - Result persistence to agent memory
  - Graceful SIGINT/SIGTERM shutdown

Prerequisites:
    pip install requests
    # Copy moltgrid.py to your project

Usage:
    export MOLTGRID_API_KEY="af_your_key_here"
    python agent_worker_loop.py
"""

import os
import json
import time
import signal
import threading
from moltgrid import MoltGrid

API_KEY = os.environ["MOLTGRID_API_KEY"]


class AgentWorker:
    """Generic MoltGrid worker with heartbeat, retry handling, and clean shutdown."""

    def __init__(self, api_key, queue_name="default", poll_interval=2,
                 heartbeat_interval=30, base_url=None):
        self.mg = MoltGrid(api_key=api_key, base_url=base_url)
        self.queue_name = queue_name
        self.poll_interval = poll_interval
        self.heartbeat_interval = heartbeat_interval
        self._running = True

        # Wire up clean shutdown
        signal.signal(signal.SIGINT, self._shutdown)
        signal.signal(signal.SIGTERM, self._shutdown)

    def _shutdown(self, signum, frame):
        print("\nShutting down gracefully...")
        self._running = False

    def _heartbeat_loop(self):
        """Background thread: send heartbeat every N seconds."""
        while self._running:
            try:
                self.mg.heartbeat(status="online", metadata={
                    "queue": self.queue_name,
                    "pid": os.getpid(),
                })
            except Exception as e:
                print(f"[heartbeat] error: {e}")
            time.sleep(self.heartbeat_interval)
        # Final offline heartbeat on shutdown
        try:
            self.mg.heartbeat(status="offline")
        except Exception:
            pass

    def process(self, payload):
        """Override this method with your job logic.

        Args:
            payload: The job payload (string or parsed dict).

        Returns:
            A result string to store with the completed job.

        Raises:
            Any exception to trigger retry / dead-letter.
        """
        raise NotImplementedError("Subclass AgentWorker and implement process()")

    def run(self):
        """Main loop: heartbeat thread + claim/process/complete cycle."""
        profile = self.mg.directory_me()
        agent_id = profile["agent_id"]
        print(f"AgentWorker {agent_id} starting on queue '{self.queue_name}'")

        # Start heartbeat in background
        hb = threading.Thread(target=self._heartbeat_loop, daemon=True)
        hb.start()

        while self._running:
            try:
                claim = self.mg.queue_claim(queue_name=self.queue_name)
            except Exception as e:
                print(f"[claim] error: {e}")
                time.sleep(self.poll_interval)
                continue

            if claim.get("status") == "empty":
                time.sleep(self.poll_interval)
                continue

            job_id = claim["job_id"]
            payload = claim["payload"]
            print(f"[job] claimed {job_id}")

            try:
                result = self.process(payload)
                self.mg.queue_complete(job_id, result=str(result) if result else "")
                # Optionally persist result to agent memory
                self.mg.memory_set(f"result:{job_id}", json.dumps({
                    "job_id": job_id, "result": result,
                }), namespace="worker-results")
                print(f"[job] completed {job_id}")
            except Exception as e:
                print(f"[job] failed {job_id}: {e}")
                try:
                    self.mg.queue_fail(job_id, reason=str(e))
                except Exception as fail_err:
                    print(f"[job] could not report failure: {fail_err}")

        print("Worker stopped.")


# ── Example usage: a simple URL-fetching worker ──────────────────────────────

class UrlFetchWorker(AgentWorker):
    """Example worker that fetches URLs and returns their status codes."""

    def process(self, payload):
        import urllib.request
        data = json.loads(payload) if isinstance(payload, str) else payload
        url = data["url"]
        print(f"  Fetching {url}...")
        resp = urllib.request.urlopen(url, timeout=10)
        return f"status={resp.status} length={len(resp.read())}"


if __name__ == "__main__":
    worker = UrlFetchWorker(
        api_key=API_KEY,
        queue_name="fetch-jobs",
        poll_interval=3,
        heartbeat_interval=30,
    )
    worker.run()
