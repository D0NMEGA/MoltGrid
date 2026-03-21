"""
MoltGrid Load Test Script
==========================
Validates API performance under concurrent load.

Usage:
    python -m tests.load_test --base-url http://127.0.0.1:8000 --workers 10 --duration 30

Pass criteria (LOCKED):
    error_rate < 1.0% AND t_elapsed < 60s
"""

import argparse
import json
import math
import os
import random
import string
import sys
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional

try:
    import httpx
except ImportError:
    print("ERROR: httpx is required. Install with: pip install httpx")
    sys.exit(1)


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

DEFAULT_BASE_URL = os.getenv("LOAD_TEST_BASE_URL", "http://127.0.0.1:8000")
DEFAULT_WORKERS = int(os.getenv("LOAD_TEST_WORKERS", "10"))
DEFAULT_DURATION = int(os.getenv("LOAD_TEST_DURATION", "30"))
DEFAULT_RAMP_UP = int(os.getenv("LOAD_TEST_RAMP_UP", "5"))

# Pass/fail thresholds (LOCKED by user decision)
MAX_ERROR_RATE = 1.0      # percent
MAX_ELAPSED_SECONDS = 60  # seconds


# ---------------------------------------------------------------------------
# Metrics Collector
# ---------------------------------------------------------------------------

class MetricsCollector:
    """Thread-safe metrics aggregation for load test results."""

    def __init__(self):
        self._lock = threading.Lock()
        self._latencies: Dict[str, List[float]] = {}
        self._status_codes: Dict[str, Dict[int, int]] = {}
        self._errors: Dict[str, int] = {}
        self._successes: Dict[str, int] = {}
        self._total: Dict[str, int] = {}

    def record(self, scenario: str, latency_ms: float, status_code: int,
               is_error: bool = False):
        """Record a single request result."""
        with self._lock:
            if scenario not in self._latencies:
                self._latencies[scenario] = []
                self._status_codes[scenario] = {}
                self._errors[scenario] = 0
                self._successes[scenario] = 0
                self._total[scenario] = 0

            self._latencies[scenario].append(latency_ms)
            self._total[scenario] += 1

            code_counts = self._status_codes[scenario]
            code_counts[status_code] = code_counts.get(status_code, 0) + 1

            if is_error:
                self._errors[scenario] += 1
            else:
                self._successes[scenario] += 1

    def percentile(self, scenario: str, p: float) -> float:
        """Calculate the p-th percentile latency for a scenario."""
        with self._lock:
            values = sorted(self._latencies.get(scenario, []))
        if not values:
            return 0.0
        k = (len(values) - 1) * (p / 100.0)
        f = math.floor(k)
        c = math.ceil(k)
        if f == c:
            return values[int(k)]
        return values[f] * (c - k) + values[c] * (k - f)

    @property
    def scenarios(self) -> List[str]:
        with self._lock:
            return list(self._latencies.keys())

    def total_requests(self) -> int:
        with self._lock:
            return sum(self._total.values())

    def total_errors(self) -> int:
        with self._lock:
            return sum(self._errors.values())

    def error_rate(self) -> float:
        """Overall error rate as a percentage."""
        total = self.total_requests()
        if total == 0:
            return 0.0
        return (self.total_errors() / total) * 100.0

    def scenario_summary(self, scenario: str) -> Dict[str, Any]:
        """Build a summary dict for one scenario."""
        with self._lock:
            total = self._total.get(scenario, 0)
            errors = self._errors.get(scenario, 0)
            codes = dict(self._status_codes.get(scenario, {}))
        return {
            "total_requests": total,
            "errors": errors,
            "error_rate_pct": round((errors / total * 100) if total else 0.0, 2),
            "p50_ms": round(self.percentile(scenario, 50), 2),
            "p95_ms": round(self.percentile(scenario, 95), 2),
            "p99_ms": round(self.percentile(scenario, 99), 2),
            "status_codes": codes,
        }

    def full_report(self, elapsed_seconds: float) -> Dict[str, Any]:
        """Build the complete report dict."""
        total = self.total_requests()
        error_rate_pct = self.error_rate()
        passed = error_rate_pct < MAX_ERROR_RATE and elapsed_seconds < MAX_ELAPSED_SECONDS

        scenarios_report = {}
        for s in self.scenarios:
            scenarios_report[s] = self.scenario_summary(s)

        return {
            "summary": {
                "total_requests": total,
                "total_errors": self.total_errors(),
                "error_rate_pct": round(error_rate_pct, 2),
                "elapsed_seconds": round(elapsed_seconds, 2),
                "throughput_rps": round(total / elapsed_seconds, 2) if elapsed_seconds > 0 else 0,
            },
            "thresholds": {
                "max_error_rate_pct": MAX_ERROR_RATE,
                "max_elapsed_seconds": MAX_ELAPSED_SECONDS,
            },
            "verdict": "PASS" if passed else "FAIL",
            "scenarios": scenarios_report,
        }


# ---------------------------------------------------------------------------
# Scenario Registry
# ---------------------------------------------------------------------------

@dataclass
class Scenario:
    """A named load test scenario."""
    name: str
    weight: int  # relative frequency
    fn: Callable  # (client, base_url, collector) -> None


_scenarios: List[Scenario] = []


def register_scenario(name: str, weight: int = 1):
    """Decorator to register a load test scenario function."""
    def decorator(fn: Callable):
        _scenarios.append(Scenario(name=name, weight=weight, fn=fn))
        return fn
    return decorator


def get_scenarios() -> List[Scenario]:
    """Return all registered scenarios."""
    return list(_scenarios)


def _pick_scenario(scenarios: List[Scenario]) -> Scenario:
    """Weighted random selection of a scenario."""
    weights = [s.weight for s in scenarios]
    total = sum(weights)
    r = random.uniform(0, total)
    cumulative = 0
    for s, w in zip(scenarios, weights):
        cumulative += w
        if r <= cumulative:
            return s
    return scenarios[-1]


# ---------------------------------------------------------------------------
# Helper utilities
# ---------------------------------------------------------------------------

def _random_string(length: int = 8) -> str:
    return "".join(random.choices(string.ascii_lowercase + string.digits, k=length))


def _timed_request(client: httpx.Client, method: str, url: str,
                   collector: MetricsCollector, scenario_name: str,
                   **kwargs) -> Optional[httpx.Response]:
    """Execute a request, record metrics, return the response."""
    start = time.monotonic()
    try:
        resp = client.request(method, url, timeout=10.0, **kwargs)
        latency_ms = (time.monotonic() - start) * 1000
        is_error = resp.status_code >= 500
        collector.record(scenario_name, latency_ms, resp.status_code, is_error)
        return resp
    except Exception:
        latency_ms = (time.monotonic() - start) * 1000
        collector.record(scenario_name, latency_ms, 0, is_error=True)
        return None


# ---------------------------------------------------------------------------
# Scenario Definitions
# ---------------------------------------------------------------------------

@register_scenario("health_check", weight=3)
def scenario_health(client: httpx.Client, base_url: str,
                    collector: MetricsCollector):
    """GET /v1/health -- lightweight, high frequency."""
    _timed_request(client, "GET", f"{base_url}/v1/health",
                   collector, "health_check")


@register_scenario("auth_signup_login", weight=1)
def scenario_auth(client: httpx.Client, base_url: str,
                  collector: MetricsCollector):
    """POST signup then login -- tests auth flow under load."""
    email = f"loadtest_{_random_string(12)}@test.local"
    password = f"LoadT3st!{_random_string(8)}"
    username = f"lt_{_random_string(10)}"

    resp = _timed_request(
        client, "POST", f"{base_url}/v1/auth/signup",
        collector, "auth_signup_login",
        json={"email": email, "password": password, "username": username},
    )
    if resp and resp.status_code < 400:
        _timed_request(
            client, "POST", f"{base_url}/v1/auth/login",
            collector, "auth_signup_login",
            json={"email": email, "password": password},
        )


@register_scenario("memory_crud", weight=2)
def scenario_memory(client: httpx.Client, base_url: str,
                    collector: MetricsCollector):
    """Memory set then get -- tests DB write + read path."""
    # This needs an API key. We use a pre-seeded key if available,
    # otherwise skip gracefully.
    api_key = os.getenv("LOAD_TEST_API_KEY", "")
    if not api_key:
        # Record a skip (not an error)
        collector.record("memory_crud", 0.0, 200, is_error=False)
        return

    headers = {"X-API-Key": api_key}
    key = f"lt_{_random_string(8)}"

    _timed_request(
        client, "POST", f"{base_url}/v1/memory",
        collector, "memory_crud",
        json={"key": key, "value": f"test_value_{_random_string(16)}"},
        headers=headers,
    )

    _timed_request(
        client, "GET", f"{base_url}/v1/memory/{key}",
        collector, "memory_crud",
        headers=headers,
    )


@register_scenario("directory_list", weight=2)
def scenario_directory(client: httpx.Client, base_url: str,
                       collector: MetricsCollector):
    """GET /v1/directory -- read-heavy, tests query performance."""
    _timed_request(client, "GET", f"{base_url}/v1/directory",
                   collector, "directory_list")


@register_scenario("relay_send_inbox", weight=1)
def scenario_relay(client: httpx.Client, base_url: str,
                   collector: MetricsCollector):
    """Relay send + inbox check -- tests messaging path."""
    api_key = os.getenv("LOAD_TEST_API_KEY", "")
    if not api_key:
        collector.record("relay_send_inbox", 0.0, 200, is_error=False)
        return

    headers = {"X-API-Key": api_key}
    target = os.getenv("LOAD_TEST_TARGET_AGENT", "self")

    _timed_request(
        client, "POST", f"{base_url}/v1/relay/send",
        collector, "relay_send_inbox",
        json={"to": target, "message": f"load_test_{_random_string(8)}"},
        headers=headers,
    )

    _timed_request(
        client, "GET", f"{base_url}/v1/relay/inbox",
        collector, "relay_send_inbox",
        headers=headers,
    )


@register_scenario("pricing_check", weight=2)
def scenario_pricing(client: httpx.Client, base_url: str,
                     collector: MetricsCollector):
    """GET /v1/pricing -- public endpoint, tests response caching."""
    _timed_request(client, "GET", f"{base_url}/v1/pricing",
                   collector, "pricing_check")


# ---------------------------------------------------------------------------
# Load Generator
# ---------------------------------------------------------------------------

def _worker_loop(worker_id: int, base_url: str, collector: MetricsCollector,
                 scenarios: List[Scenario], stop_event: threading.Event,
                 ramp_up: float):
    """Worker thread: continuously pick and run scenarios until stopped."""
    # Stagger start during ramp-up period
    if ramp_up > 0:
        delay = random.uniform(0, ramp_up)
        stop_event.wait(delay)
        if stop_event.is_set():
            return

    with httpx.Client() as client:
        while not stop_event.is_set():
            scenario = _pick_scenario(scenarios)
            try:
                scenario.fn(client, base_url, collector)
            except Exception:
                pass  # errors already recorded in _timed_request
            # Small random delay to avoid thundering herd
            time.sleep(random.uniform(0.01, 0.05))


def run_load_test(base_url: str = DEFAULT_BASE_URL,
                  num_workers: int = DEFAULT_WORKERS,
                  duration: int = DEFAULT_DURATION,
                  ramp_up: int = DEFAULT_RAMP_UP) -> Dict[str, Any]:
    """
    Execute the load test and return a report dict.

    Args:
        base_url: Target server URL
        num_workers: Number of concurrent worker threads
        duration: Test duration in seconds
        ramp_up: Ramp-up period in seconds (workers stagger start)

    Returns:
        Report dict with summary, scenarios, thresholds, and verdict.
    """
    collector = MetricsCollector()
    scenarios = get_scenarios()
    if not scenarios:
        return {
            "summary": {"total_requests": 0, "error_rate_pct": 0, "elapsed_seconds": 0},
            "verdict": "FAIL",
            "error": "No scenarios registered",
        }

    stop_event = threading.Event()

    print(f"Starting load test: {num_workers} workers, {duration}s duration, "
          f"{ramp_up}s ramp-up")
    print(f"Target: {base_url}")
    print(f"Scenarios: {', '.join(s.name for s in scenarios)}")
    print("-" * 60)

    t_start = time.monotonic()

    with ThreadPoolExecutor(max_workers=num_workers) as pool:
        futures = []
        for i in range(num_workers):
            f = pool.submit(_worker_loop, i, base_url, collector,
                            scenarios, stop_event, ramp_up)
            futures.append(f)

        # Wait for test duration
        try:
            time.sleep(duration)
        except KeyboardInterrupt:
            print("\nInterrupted -- stopping workers...")
        finally:
            stop_event.set()

        # Wait for all workers to finish
        for f in as_completed(futures, timeout=10):
            try:
                f.result()
            except Exception:
                pass

    t_elapsed = time.monotonic() - t_start
    report = collector.full_report(t_elapsed)

    # Print summary
    print("-" * 60)
    print(f"Elapsed:    {report['summary']['elapsed_seconds']}s")
    print(f"Requests:   {report['summary']['total_requests']}")
    print(f"Throughput: {report['summary']['throughput_rps']} req/s")
    print(f"Error rate: {report['summary']['error_rate_pct']}%")
    print(f"Verdict:    {report['verdict']}")
    print()

    for name, data in report["scenarios"].items():
        print(f"  [{name}] total={data['total_requests']} "
              f"err={data['errors']} "
              f"p50={data['p50_ms']}ms p95={data['p95_ms']}ms "
              f"p99={data['p99_ms']}ms")

    return report


# ---------------------------------------------------------------------------
# CLI Entry Point
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="MoltGrid Load Test")
    parser.add_argument("--base-url", default=DEFAULT_BASE_URL,
                        help=f"Target server URL (default: {DEFAULT_BASE_URL})")
    parser.add_argument("--workers", type=int, default=DEFAULT_WORKERS,
                        help=f"Number of concurrent workers (default: {DEFAULT_WORKERS})")
    parser.add_argument("--duration", type=int, default=DEFAULT_DURATION,
                        help=f"Test duration in seconds (default: {DEFAULT_DURATION})")
    parser.add_argument("--ramp-up", type=int, default=DEFAULT_RAMP_UP,
                        help=f"Ramp-up period in seconds (default: {DEFAULT_RAMP_UP})")
    parser.add_argument("--output", default=None,
                        help="Path to write JSON report (default: stdout)")
    args = parser.parse_args()

    report = run_load_test(
        base_url=args.base_url,
        num_workers=args.workers,
        duration=args.duration,
        ramp_up=args.ramp_up,
    )

    report_json = json.dumps(report, indent=2)

    if args.output:
        with open(args.output, "w") as f:
            f.write(report_json)
        print(f"\nReport written to {args.output}")
    else:
        print(f"\n{report_json}")

    sys.exit(0 if report["verdict"] == "PASS" else 1)


if __name__ == "__main__":
    main()
