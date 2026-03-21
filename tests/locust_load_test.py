"""
MoltGrid Locust Load Test -- Sustained Production Load
========================================================
Realistic agent behavior simulation for sustained load testing.

Usage:
    locust -f tests/locust_load_test.py --host https://api.moltgrid.net

    # Headless mode (matches pass criteria):
    locust -f tests/locust_load_test.py --host https://api.moltgrid.net \
        --users 500 --spawn-rate 4.17 --run-time 10m --headless \
        --csv results/locust_report

Pass criteria (LOCKED by user):
    - Ramp: 0 to 500 users over 2 min, sustain 8 min (10 min total)
    - p99 < 500ms
    - Error rate < 0.1%
    - NO 5xx errors
    - Realistic agent behavior intervals

Environment variables:
    LOAD_TEST_API_KEY       Agent API key for authenticated endpoints
    LOAD_TEST_TARGET_AGENT  Target agent_id for relay tests (default: self)
"""

import json
import os
import random
import string
from typing import Any, Dict

from locust import HttpUser, between, events, task, tag
from locust.runners import MasterRunner, WorkerRunner

from tests.load_test_evaluator import (
    LoadTestEvaluator,
    P99_THRESHOLD_MS,
    MAX_ERROR_RATE_PCT,
    MAX_5XX_ERRORS,
    RAMP_USERS,
    RAMP_DURATION_S,
    SUSTAIN_DURATION_S,
    TOTAL_DURATION_S,
    SPAWN_RATE,
    TASK_WEIGHTS,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _random_string(length: int = 8) -> str:
    """Generate a random alphanumeric string."""
    return "".join(random.choices(string.ascii_lowercase + string.digits, k=length))


def _get_api_key() -> str:
    """Retrieve the agent API key from environment."""
    return os.getenv("LOAD_TEST_API_KEY", "")


def _get_target_agent() -> str:
    """Retrieve the target agent ID for relay tests."""
    return os.getenv("LOAD_TEST_TARGET_AGENT", "self")


# ---------------------------------------------------------------------------
# Realistic Agent User
# ---------------------------------------------------------------------------

class MoltGridAgent(HttpUser):
    """
    Simulates a realistic autonomous agent on MoltGrid.

    Task weights model real-world agent behavior frequencies:
    - Heartbeat:     every ~30s  (highest frequency)
    - Message poll:  every ~10s  (high frequency, but lightweight)
    - Memory ops:    every ~60s  (moderate)
    - Job submit:    every ~120s (infrequent, heavy)
    - Directory:     every ~60s  (moderate, read-only)
    - Health check:  every ~30s  (background monitoring)

    The wait_time between tasks uses 1-5 seconds to simulate
    realistic inter-request spacing. Locust's task weighting
    controls the relative frequency of each operation type.
    """

    wait_time = between(1, 5)

    def on_start(self):
        """Set up agent headers and state for the session."""
        self.api_key = _get_api_key()
        self.target_agent = _get_target_agent()
        self.agent_headers = {"X-API-Key": self.api_key} if self.api_key else {}
        self._memory_keys = []  # Track keys we've written for read-back

    # -- Heartbeat: highest frequency (weight 6, ~30s effective) ----------

    @task(6)
    @tag("heartbeat", "authenticated")
    def heartbeat(self):
        """
        POST /v1/heartbeat -- Agent liveness signal.
        Real agents call this every 30 seconds.
        """
        if not self.api_key:
            return
        self.client.post(
            "/v1/heartbeat",
            headers=self.agent_headers,
            name="/v1/heartbeat",
        )

    # -- Message poll: high frequency (weight 5, ~10s effective) ----------

    @task(5)
    @tag("messaging", "authenticated")
    def poll_inbox(self):
        """
        GET /v1/relay/inbox -- Check for incoming messages.
        Real agents poll every 10 seconds.
        """
        if not self.api_key:
            return
        self.client.get(
            "/v1/relay/inbox",
            headers=self.agent_headers,
            name="/v1/relay/inbox",
        )

    @task(1)
    @tag("messaging", "authenticated")
    def send_message(self):
        """
        POST /v1/relay/send -- Send a message to another agent.
        Less frequent than polling.
        """
        if not self.api_key:
            return
        self.client.post(
            "/v1/relay/send",
            headers=self.agent_headers,
            json={
                "to": self.target_agent,
                "message": f"load_test_msg_{_random_string(12)}",
            },
            name="/v1/relay/send",
        )

    # -- Memory operations: moderate frequency (weight 3, ~60s) -----------

    @task(3)
    @tag("memory", "authenticated")
    def memory_set(self):
        """
        POST /v1/memory -- Write a key-value pair.
        Real agents write memory every ~60 seconds.
        """
        if not self.api_key:
            return
        key = f"lt_{_random_string(8)}"
        resp = self.client.post(
            "/v1/memory",
            headers=self.agent_headers,
            json={
                "key": key,
                "value": f"test_value_{_random_string(16)}",
            },
            name="/v1/memory [SET]",
        )
        if resp.status_code < 400:
            self._memory_keys.append(key)
            # Keep list bounded
            if len(self._memory_keys) > 20:
                self._memory_keys = self._memory_keys[-10:]

    @task(2)
    @tag("memory", "authenticated")
    def memory_get(self):
        """
        GET /v1/memory/{key} -- Read back a previously written key.
        Slightly less frequent than writes (agents read their own state).
        """
        if not self.api_key or not self._memory_keys:
            return
        key = random.choice(self._memory_keys)
        self.client.get(
            f"/v1/memory/{key}",
            headers=self.agent_headers,
            name="/v1/memory/{key} [GET]",
        )

    # -- Job operations: infrequent (weight 1, ~120s) --------------------

    @task(1)
    @tag("jobs", "authenticated")
    def submit_job(self):
        """
        POST /v1/queue/submit -- Submit a task to the job queue.
        Real agents submit jobs every ~120 seconds.
        """
        if not self.api_key:
            return
        self.client.post(
            "/v1/queue/submit",
            headers=self.agent_headers,
            json={
                "task_type": "load_test",
                "payload": {"data": _random_string(32)},
            },
            name="/v1/queue/submit",
        )

    @task(1)
    @tag("jobs", "authenticated")
    def poll_jobs(self):
        """
        GET /v1/queue/next -- Poll for available jobs.
        Paired with job submission.
        """
        if not self.api_key:
            return
        self.client.get(
            "/v1/queue/next",
            headers=self.agent_headers,
            name="/v1/queue/next",
        )

    # -- Public/read-only endpoints: moderate frequency -------------------

    @task(2)
    @tag("directory", "public")
    def directory_list(self):
        """
        GET /v1/directory -- Browse agent directory.
        Moderate frequency, read-only, cacheable.
        """
        self.client.get(
            "/v1/directory",
            name="/v1/directory",
        )

    @task(3)
    @tag("health", "public")
    def health_check(self):
        """
        GET /v1/health -- Platform health check.
        High frequency, lightweight.
        """
        self.client.get(
            "/v1/health",
            name="/v1/health",
        )

    @task(1)
    @tag("pricing", "public")
    def pricing_check(self):
        """
        GET /v1/pricing -- Pricing info (cached).
        Low frequency, read-only.
        """
        self.client.get(
            "/v1/pricing",
            name="/v1/pricing",
        )

    @task(1)
    @tag("metrics", "public")
    def metrics_check(self):
        """
        GET /v1/metrics -- Prometheus metrics endpoint.
        Simulates monitoring scrape.
        """
        self.client.get(
            "/v1/metrics",
            name="/v1/metrics",
        )


# ---------------------------------------------------------------------------
# Locust Event Hooks (for automated pass/fail reporting)
# ---------------------------------------------------------------------------

_5xx_counter = {"count": 0}


@events.request.add_listener
def on_request(response=None, exception=None, **kwargs):
    """Track 5xx errors globally for pass/fail evaluation."""
    if exception:
        _5xx_counter["count"] += 1
    elif response is not None and response.status_code >= 500:
        _5xx_counter["count"] += 1


@events.quitting.add_listener
def on_quitting(environment, **kwargs):
    """
    Print pass/fail verdict when the test finishes.
    Only runs on the master (or standalone) runner.
    """
    if isinstance(environment.runner, WorkerRunner):
        return

    stats = environment.runner.stats
    total_requests = stats.total.num_requests
    total_failures = stats.total.num_failures

    # Collect all response times from stats
    response_times = []
    for entry in stats.entries.values():
        if hasattr(entry, "response_times") and entry.response_times:
            for ms_bucket, count in entry.response_times.items():
                response_times.extend([ms_bucket] * count)

    evaluator = LoadTestEvaluator()
    result = evaluator.evaluate({
        "total_requests": total_requests,
        "total_failures": total_failures,
        "response_times": response_times,
        "status_5xx_count": _5xx_counter["count"],
    })

    print("\n" + "=" * 60)
    print("MOLTGRID LOAD TEST RESULTS")
    print("=" * 60)
    print(f"Verdict: {result['verdict']}")
    print(f"Total Requests: {result['metrics']['total_requests']}")
    print(f"Error Rate: {result['metrics']['error_rate_pct']}%")
    print(f"p50: {result['metrics']['p50_ms']}ms")
    print(f"p95: {result['metrics']['p95_ms']}ms")
    print(f"p99: {result['metrics']['p99_ms']}ms")
    print(f"5xx Errors: {result['metrics']['status_5xx_count']}")
    print("-" * 60)
    for name, check in result["checks"].items():
        status = "PASS" if check["passed"] else "FAIL"
        print(f"  [{status}] {name}: {check['actual']} (threshold: {check['threshold']})")
    print("=" * 60)

    # Write JSON report
    report_path = os.getenv("LOCUST_REPORT_PATH", "tests/locust_report.json")
    try:
        with open(report_path, "w") as f:
            json.dump(result, f, indent=2)
        print(f"\nReport written to {report_path}")
    except OSError as e:
        print(f"\nFailed to write report: {e}")

    # Exit with non-zero if FAIL
    if result["verdict"] == "FAIL":
        environment.process_exit_code = 1
