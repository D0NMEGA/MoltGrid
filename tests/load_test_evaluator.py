"""
MoltGrid Load Test Evaluator
==============================
Pass/fail evaluation logic for load test results.
Separated from locust_load_test.py to allow unit testing
without gevent monkey-patching conflicts.

Pass criteria (LOCKED by user):
    - Ramp: 0 to 500 users over 2 min, sustain 8 min (10 min total)
    - p99 < 500ms
    - Error rate < 0.1%
    - NO 5xx errors
"""

import math
from typing import Any, Dict


# ---------------------------------------------------------------------------
# Configuration Constants (LOCKED by user)
# ---------------------------------------------------------------------------

P99_THRESHOLD_MS = 500        # p99 latency must be < 500ms
MAX_ERROR_RATE_PCT = 0.1      # error rate must be < 0.1%
MAX_5XX_ERRORS = 0            # zero tolerance for server errors
RAMP_USERS = 500              # target user count
RAMP_DURATION_S = 120         # 2 minutes to reach target
SUSTAIN_DURATION_S = 480      # 8 minutes sustained
TOTAL_DURATION_S = 600        # 10 minutes total

# Spawn rate: 500 users / 120 seconds = ~4.17 users/second
SPAWN_RATE = round(RAMP_USERS / RAMP_DURATION_S, 2)

# Task weight definitions (used by both locust file and tests)
TASK_WEIGHTS = {
    "heartbeat": 6,
    "poll_inbox": 5,
    "send_message": 1,
    "memory_set": 3,
    "memory_get": 2,
    "submit_job": 1,
    "poll_jobs": 1,
    "directory_list": 2,
    "health_check": 3,
    "pricing_check": 1,
    "metrics_check": 1,
}


# ---------------------------------------------------------------------------
# Pass/Fail Evaluation
# ---------------------------------------------------------------------------

class LoadTestEvaluator:
    """
    Evaluates load test results against locked pass criteria.

    Criteria:
        - p99 latency < 500ms
        - Error rate < 0.1%
        - Zero 5xx errors
    """

    def __init__(
        self,
        p99_threshold_ms: float = P99_THRESHOLD_MS,
        max_error_rate_pct: float = MAX_ERROR_RATE_PCT,
        max_5xx: int = MAX_5XX_ERRORS,
    ):
        self.p99_threshold_ms = p99_threshold_ms
        self.max_error_rate_pct = max_error_rate_pct
        self.max_5xx = max_5xx

    def evaluate(self, stats: Dict[str, Any]) -> Dict[str, Any]:
        """
        Evaluate stats dict and return verdict.

        Args:
            stats: Dict with keys:
                - total_requests (int)
                - total_failures (int)
                - response_times (list of ms values)
                - status_5xx_count (int)

        Returns:
            Dict with verdict, checks, and details.
        """
        total = stats.get("total_requests", 0)
        failures = stats.get("total_failures", 0)
        response_times = sorted(stats.get("response_times", []))
        status_5xx = stats.get("status_5xx_count", 0)

        # Calculate metrics
        error_rate = (failures / total * 100) if total > 0 else 0.0
        p99 = self._percentile(response_times, 99) if response_times else 0.0
        p95 = self._percentile(response_times, 95) if response_times else 0.0
        p50 = self._percentile(response_times, 50) if response_times else 0.0

        # Check criteria
        p99_pass = p99 < self.p99_threshold_ms
        error_pass = error_rate < self.max_error_rate_pct
        no_5xx = status_5xx <= self.max_5xx

        verdict = "PASS" if (p99_pass and error_pass and no_5xx) else "FAIL"

        checks = {
            "p99_under_500ms": {
                "passed": p99_pass,
                "actual": round(p99, 2),
                "threshold": self.p99_threshold_ms,
            },
            "error_rate_under_0.1pct": {
                "passed": error_pass,
                "actual": round(error_rate, 4),
                "threshold": self.max_error_rate_pct,
            },
            "zero_5xx_errors": {
                "passed": no_5xx,
                "actual": status_5xx,
                "threshold": self.max_5xx,
            },
        }

        return {
            "verdict": verdict,
            "checks": checks,
            "metrics": {
                "total_requests": total,
                "total_failures": failures,
                "error_rate_pct": round(error_rate, 4),
                "p50_ms": round(p50, 2),
                "p95_ms": round(p95, 2),
                "p99_ms": round(p99, 2),
                "status_5xx_count": status_5xx,
            },
            "thresholds": {
                "p99_threshold_ms": self.p99_threshold_ms,
                "max_error_rate_pct": self.max_error_rate_pct,
                "max_5xx_errors": self.max_5xx,
            },
        }

    @staticmethod
    def _percentile(sorted_values: list, p: float) -> float:
        """Calculate the p-th percentile from sorted values."""
        if not sorted_values:
            return 0.0
        k = (len(sorted_values) - 1) * (p / 100.0)
        f = math.floor(k)
        c = math.ceil(k)
        if f == c:
            return sorted_values[int(k)]
        return sorted_values[f] * (c - k) + sorted_values[c] * (k - f)
