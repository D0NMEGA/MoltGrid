---
phase: "41"
plan: "04"
subsystem: testing
tags: [locust, load-test, performance, p99, agent-behavior]
dependency_graph:
  requires: [asyncpg-pool, redis-cache, multi-worker, metrics]
  provides: [sustained-load-test, pass-fail-evaluation]
  affects: [tests/]
tech_stack:
  added: [locust]
  patterns: [weighted-task-distribution, percentile-evaluation, event-hooks]
key_files:
  created: [tests/locust_load_test.py, tests/load_test_evaluator.py, tests/test_locust_load_test.py]
  modified: []
decisions:
  - Separated evaluator into load_test_evaluator.py to avoid gevent monkey-patching conflicts in pytest
  - Task weights model real agent behavior frequencies (heartbeat 6, inbox 5, memory 3, jobs 1)
  - Strict less-than comparisons for all pass criteria (p99 < 500ms, error < 0.1%)
metrics:
  duration: 5min
  completed: "2026-03-21T09:56:00Z"
---

# Phase 41 Plan 04: Locust Load Test Script Summary

Locust-based sustained load test with weighted agent behavior tasks (heartbeat 30s, message poll 10s, memory 60s, jobs 120s), locked pass criteria (p99 < 500ms, error < 0.1%, zero 5xx), and 36 unit tests for evaluator logic.

## What Was Built

### Locust Load Test Script (tests/locust_load_test.py)
- MoltGridAgent HttpUser class with 11 weighted tasks simulating real agent behavior
- Heartbeat (weight 6), inbox poll (weight 5), memory set/get (weight 3/2), jobs (weight 1)
- Public endpoints: health check, directory, pricing, metrics
- Ramp: 0 to 500 users over 2 minutes, sustain for 8 minutes (10 minutes total)
- Spawn rate: 4.17 users/second
- Event hooks track 5xx errors and print pass/fail verdict on completion
- JSON report output with detailed per-check results

### Load Test Evaluator (tests/load_test_evaluator.py)
- Separated from locust script to enable pytest without gevent conflicts
- LoadTestEvaluator class with configurable thresholds
- Percentile calculation (linear interpolation)
- TASK_WEIGHTS dict as single source of truth for task frequency distribution
- All locked constants: P99_THRESHOLD_MS=500, MAX_ERROR_RATE_PCT=0.1, MAX_5XX_ERRORS=0

### Unit Tests (tests/test_locust_load_test.py)
- 36 tests across 5 test classes
- TestConfigConstants: verifies all locked pass criteria values
- TestLoadTestEvaluator: PASS/FAIL verdicts, edge cases, custom thresholds
- TestPercentileCalculation: math correctness, boundary values
- TestTaskWeights: realistic behavior distribution validation
- All tests pass in 0.13s

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 - Blocking] Gevent SSL monkey-patching breaks pytest import**
- **Found during:** Task 2 (unit tests)
- **Issue:** Importing locust in pytest triggers gevent monkey-patching which causes RecursionError in SSL context
- **Fix:** Extracted LoadTestEvaluator and constants into separate load_test_evaluator.py module; tests import from that instead
- **Files modified:** tests/load_test_evaluator.py (new), tests/locust_load_test.py (imports from evaluator)

## Test Results

- 36 new tests all pass
- 30 existing load_test tests continue to pass
- Total load-test-related: 66 tests passing

## Commits

| Task | Name | Commit | Files |
|------|------|--------|-------|
| 1 | Locust script + evaluator | 97f805f | tests/locust_load_test.py, tests/load_test_evaluator.py |
| 2 | Unit tests | 30ef973 | tests/test_locust_load_test.py |

## Usage

```bash
# Headless mode (matches locked pass criteria):
locust -f tests/locust_load_test.py --host https://api.moltgrid.net \
    --users 500 --spawn-rate 4.17 --run-time 10m --headless \
    --csv results/locust_report

# With API key for authenticated endpoints:
LOAD_TEST_API_KEY=af_xxx locust -f tests/locust_load_test.py \
    --host https://api.moltgrid.net --users 500 --spawn-rate 4.17 \
    --run-time 10m --headless

# Web UI mode:
locust -f tests/locust_load_test.py --host https://api.moltgrid.net
```

## Self-Check: PASSED
