"""
Unit Tests for MoltGrid Locust Load Test
==========================================
Tests configuration constants, LoadTestEvaluator logic, task weights,
and pass/fail criteria without importing locust (avoids gevent conflicts).
"""

import json

import pytest

from tests.load_test_evaluator import (
    RAMP_USERS,
    RAMP_DURATION_S,
    SUSTAIN_DURATION_S,
    TOTAL_DURATION_S,
    SPAWN_RATE,
    P99_THRESHOLD_MS,
    MAX_ERROR_RATE_PCT,
    MAX_5XX_ERRORS,
    TASK_WEIGHTS,
    LoadTestEvaluator,
)


# ---------------------------------------------------------------------------
# Configuration Constants
# ---------------------------------------------------------------------------

class TestConfigConstants:
    """Verify locked pass criteria and ramp configuration."""

    def test_ramp_users_is_500(self):
        assert RAMP_USERS == 500

    def test_ramp_duration_is_120s(self):
        """2 minutes to ramp up."""
        assert RAMP_DURATION_S == 120

    def test_sustain_duration_is_480s(self):
        """8 minutes sustained load."""
        assert SUSTAIN_DURATION_S == 480

    def test_total_duration_is_600s(self):
        """10 minutes total."""
        assert TOTAL_DURATION_S == 600

    def test_total_duration_equals_ramp_plus_sustain(self):
        assert TOTAL_DURATION_S == RAMP_DURATION_S + SUSTAIN_DURATION_S

    def test_spawn_rate_calculation(self):
        """500 users / 120 seconds = ~4.17 users/second."""
        expected = round(500 / 120, 2)
        assert SPAWN_RATE == expected

    def test_p99_threshold_is_500ms(self):
        assert P99_THRESHOLD_MS == 500

    def test_max_error_rate_is_0_1_percent(self):
        assert MAX_ERROR_RATE_PCT == 0.1

    def test_max_5xx_errors_is_zero(self):
        assert MAX_5XX_ERRORS == 0


# ---------------------------------------------------------------------------
# LoadTestEvaluator
# ---------------------------------------------------------------------------

class TestLoadTestEvaluator:
    """Tests for the pass/fail evaluation logic."""

    def setup_method(self):
        self.evaluator = LoadTestEvaluator()

    def test_pass_all_criteria(self):
        """All metrics within thresholds should PASS."""
        stats = {
            "total_requests": 10000,
            "total_failures": 5,  # 0.05% < 0.1%
            "response_times": [10.0] * 9900 + [400.0] * 100,  # p99 well under 500ms
            "status_5xx_count": 0,
        }
        result = self.evaluator.evaluate(stats)
        assert result["verdict"] == "PASS"
        assert result["checks"]["p99_under_500ms"]["passed"] is True
        assert result["checks"]["error_rate_under_0.1pct"]["passed"] is True
        assert result["checks"]["zero_5xx_errors"]["passed"] is True

    def test_fail_p99_too_high(self):
        """p99 over 500ms should FAIL."""
        # 95 values at 10ms, 5 values at 600ms -> p99 well above 500ms
        times = [10.0] * 95 + [600.0] * 5
        stats = {
            "total_requests": 100,
            "total_failures": 0,
            "response_times": times,
            "status_5xx_count": 0,
        }
        result = self.evaluator.evaluate(stats)
        assert result["verdict"] == "FAIL"
        assert result["checks"]["p99_under_500ms"]["passed"] is False

    def test_fail_error_rate_too_high(self):
        """Error rate >= 0.1% should FAIL."""
        stats = {
            "total_requests": 1000,
            "total_failures": 2,  # 0.2% >= 0.1%
            "response_times": [10.0] * 1000,
            "status_5xx_count": 0,
        }
        result = self.evaluator.evaluate(stats)
        assert result["verdict"] == "FAIL"
        assert result["checks"]["error_rate_under_0.1pct"]["passed"] is False

    def test_fail_5xx_errors(self):
        """Any 5xx error should FAIL."""
        stats = {
            "total_requests": 10000,
            "total_failures": 0,
            "response_times": [10.0] * 10000,
            "status_5xx_count": 1,
        }
        result = self.evaluator.evaluate(stats)
        assert result["verdict"] == "FAIL"
        assert result["checks"]["zero_5xx_errors"]["passed"] is False

    def test_fail_multiple_criteria(self):
        """Multiple failures should all be reported."""
        stats = {
            "total_requests": 100,
            "total_failures": 5,
            "response_times": [600.0] * 100,
            "status_5xx_count": 3,
        }
        result = self.evaluator.evaluate(stats)
        assert result["verdict"] == "FAIL"
        assert result["checks"]["p99_under_500ms"]["passed"] is False
        assert result["checks"]["error_rate_under_0.1pct"]["passed"] is False
        assert result["checks"]["zero_5xx_errors"]["passed"] is False

    def test_pass_edge_case_just_under_thresholds(self):
        """Values just below thresholds should PASS."""
        stats = {
            "total_requests": 10000,
            "total_failures": 9,  # 0.09% < 0.1%
            "response_times": [10.0] * 9999 + [499.0],
            "status_5xx_count": 0,
        }
        result = self.evaluator.evaluate(stats)
        assert result["verdict"] == "PASS"

    def test_fail_edge_case_exactly_at_error_threshold(self):
        """Error rate exactly 0.1% should FAIL (strict less-than)."""
        stats = {
            "total_requests": 1000,
            "total_failures": 1,  # exactly 0.1%
            "response_times": [10.0] * 1000,
            "status_5xx_count": 0,
        }
        result = self.evaluator.evaluate(stats)
        assert result["verdict"] == "FAIL"
        assert result["checks"]["error_rate_under_0.1pct"]["passed"] is False

    def test_fail_p99_exactly_500ms(self):
        """p99 exactly 500ms should FAIL (strict less-than)."""
        times = [500.0] * 100
        stats = {
            "total_requests": 100,
            "total_failures": 0,
            "response_times": times,
            "status_5xx_count": 0,
        }
        result = self.evaluator.evaluate(stats)
        assert result["verdict"] == "FAIL"
        assert result["checks"]["p99_under_500ms"]["passed"] is False

    def test_empty_stats(self):
        """Empty stats should not crash."""
        stats = {
            "total_requests": 0,
            "total_failures": 0,
            "response_times": [],
            "status_5xx_count": 0,
        }
        result = self.evaluator.evaluate(stats)
        assert result["verdict"] == "PASS"
        assert result["metrics"]["total_requests"] == 0

    def test_result_contains_all_fields(self):
        """Result dict should have verdict, checks, metrics, thresholds."""
        stats = {
            "total_requests": 1,
            "total_failures": 0,
            "response_times": [10.0],
            "status_5xx_count": 0,
        }
        result = self.evaluator.evaluate(stats)
        assert "verdict" in result
        assert "checks" in result
        assert "metrics" in result
        assert "thresholds" in result
        assert result["thresholds"]["p99_threshold_ms"] == 500
        assert result["thresholds"]["max_error_rate_pct"] == 0.1
        assert result["thresholds"]["max_5xx_errors"] == 0

    def test_metrics_calculation(self):
        """Verify metric values are correctly computed."""
        times = [float(t) for t in range(1, 101)]
        stats = {
            "total_requests": 100,
            "total_failures": 0,
            "response_times": times,
            "status_5xx_count": 0,
        }
        result = self.evaluator.evaluate(stats)
        assert result["metrics"]["total_requests"] == 100
        assert result["metrics"]["total_failures"] == 0
        assert result["metrics"]["error_rate_pct"] == 0.0
        assert result["metrics"]["p50_ms"] == pytest.approx(50.5, abs=1.0)
        assert result["metrics"]["p95_ms"] == pytest.approx(95.05, abs=1.0)
        assert result["metrics"]["p99_ms"] == pytest.approx(99.01, abs=1.0)

    def test_custom_thresholds(self):
        """Evaluator should accept custom thresholds."""
        evaluator = LoadTestEvaluator(
            p99_threshold_ms=200,
            max_error_rate_pct=1.0,
            max_5xx=5,
        )
        stats = {
            "total_requests": 1000,
            "total_failures": 5,  # 0.5% < 1.0%
            "response_times": [150.0] * 1000,
            "status_5xx_count": 3,  # 3 <= 5
        }
        result = evaluator.evaluate(stats)
        assert result["verdict"] == "PASS"
        assert result["thresholds"]["p99_threshold_ms"] == 200
        assert result["thresholds"]["max_error_rate_pct"] == 1.0
        assert result["thresholds"]["max_5xx_errors"] == 5

    def test_report_is_json_serializable(self):
        stats = {
            "total_requests": 100,
            "total_failures": 0,
            "response_times": [10.0] * 100,
            "status_5xx_count": 0,
        }
        result = self.evaluator.evaluate(stats)
        json_str = json.dumps(result)
        parsed = json.loads(json_str)
        assert parsed["verdict"] == "PASS"

    def test_checks_have_consistent_structure(self):
        stats = {
            "total_requests": 100,
            "total_failures": 0,
            "response_times": [10.0] * 100,
            "status_5xx_count": 0,
        }
        result = self.evaluator.evaluate(stats)
        for check_name, check_data in result["checks"].items():
            assert "passed" in check_data, f"{check_name} missing 'passed'"
            assert "actual" in check_data, f"{check_name} missing 'actual'"
            assert "threshold" in check_data, f"{check_name} missing 'threshold'"
            assert isinstance(check_data["passed"], bool)


# ---------------------------------------------------------------------------
# Percentile Calculation
# ---------------------------------------------------------------------------

class TestPercentileCalculation:
    """Tests for the percentile math in LoadTestEvaluator."""

    def test_single_value(self):
        assert LoadTestEvaluator._percentile([42.0], 50) == 42.0
        assert LoadTestEvaluator._percentile([42.0], 99) == 42.0

    def test_empty_list(self):
        assert LoadTestEvaluator._percentile([], 50) == 0.0

    def test_two_values(self):
        result = LoadTestEvaluator._percentile([10.0, 20.0], 50)
        assert result == pytest.approx(15.0, abs=0.1)

    def test_hundred_values(self):
        values = [float(i) for i in range(1, 101)]
        p50 = LoadTestEvaluator._percentile(values, 50)
        p95 = LoadTestEvaluator._percentile(values, 95)
        p99 = LoadTestEvaluator._percentile(values, 99)
        assert p50 == pytest.approx(50.5, abs=1.0)
        assert p95 == pytest.approx(95.05, abs=1.0)
        assert p99 == pytest.approx(99.01, abs=1.0)

    def test_p0_returns_minimum(self):
        values = [5.0, 10.0, 15.0, 20.0]
        assert LoadTestEvaluator._percentile(values, 0) == 5.0

    def test_p100_returns_maximum(self):
        values = [5.0, 10.0, 15.0, 20.0]
        assert LoadTestEvaluator._percentile(values, 100) == 20.0


# ---------------------------------------------------------------------------
# Task Weight Configuration
# ---------------------------------------------------------------------------

class TestTaskWeights:
    """Verify task weights model realistic agent behavior."""

    def test_heartbeat_is_highest_weight(self):
        """Heartbeat (30s interval) should be the most frequent task."""
        heartbeat_weight = TASK_WEIGHTS["heartbeat"]
        for name, w in TASK_WEIGHTS.items():
            if name != "heartbeat":
                assert heartbeat_weight >= w, (
                    f"heartbeat ({heartbeat_weight}) should be >= {name} ({w})"
                )

    def test_inbox_poll_is_high_weight(self):
        """Message polling (10s interval) should have high weight."""
        assert TASK_WEIGHTS["poll_inbox"] >= 4

    def test_memory_ops_moderate_weight(self):
        """Memory operations (60s interval) should be moderate."""
        assert TASK_WEIGHTS["memory_set"] >= 2

    def test_job_submit_low_weight(self):
        """Job submission (120s interval) should be the lowest weight."""
        assert TASK_WEIGHTS["submit_job"] <= 2

    def test_all_expected_tasks_present(self):
        """All required agent behavior tasks should be defined."""
        expected = {
            "heartbeat",
            "poll_inbox",
            "send_message",
            "memory_set",
            "memory_get",
            "submit_job",
            "poll_jobs",
            "directory_list",
            "health_check",
            "pricing_check",
            "metrics_check",
        }
        assert expected.issubset(set(TASK_WEIGHTS.keys())), (
            f"Missing tasks: {expected - set(TASK_WEIGHTS.keys())}"
        )

    def test_total_weight_is_reasonable(self):
        """Total weight should be reasonable for distribution."""
        total = sum(TASK_WEIGHTS.values())
        assert 15 <= total <= 40, f"Total weight {total} outside expected range"

    def test_authenticated_tasks_outnumber_public(self):
        """Most load should be authenticated agent operations."""
        auth_tasks = {"heartbeat", "poll_inbox", "send_message",
                      "memory_set", "memory_get", "submit_job", "poll_jobs"}
        public_tasks = {"directory_list", "health_check", "pricing_check",
                        "metrics_check"}
        auth_weight = sum(TASK_WEIGHTS[t] for t in auth_tasks)
        public_weight = sum(TASK_WEIGHTS[t] for t in public_tasks)
        assert auth_weight > public_weight
