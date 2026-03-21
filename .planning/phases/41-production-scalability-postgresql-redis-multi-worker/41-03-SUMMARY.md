---
phase: "41"
plan: "03"
subsystem: infrastructure
tags: [multi-worker, leader-election, metrics, prometheus, redis, uvicorn]
dependency_graph:
  requires: [redis, asyncpg-pool, cache]
  provides: [leader-election, prometheus-metrics, multi-worker-deploy]
  affects: [main.py, deploy.sh, systemd]
tech_stack:
  added: [redis-leader-election, prometheus-text-format]
  patterns: [SET-NX-with-TTL, Lua-atomic-delete, graceful-fallback]
key_files:
  created: [leader.py, metrics.py, tests/test_leader_metrics.py]
  modified: [main.py, routers/system.py, deploy.sh]
decisions:
  - Redis SET NX with 30s TTL and 15s renewal for leader election
  - Lua script for atomic release (check-and-delete) to prevent race conditions
  - Graceful fallback to assume-leadership when Redis unavailable
  - 4 Uvicorn workers (up from 2) with redis-server dependency in systemd
  - Prometheus text format (not JSON) for industry-standard monitoring compatibility
metrics:
  duration: 7min
  completed: "2026-03-21T09:47:00Z"
---

# Phase 41 Plan 03: Multi-Worker Uvicorn + Leader Election + /metrics Summary

Redis-based leader election with SET NX/TTL ensuring only one Uvicorn worker runs background threads, Prometheus-format /metrics endpoint with 15+ platform metrics, deploy.sh updated to auto-install Redis and run 4 workers.

## What Was Built

### Leader Election (leader.py)
- Redis SET NX with 30-second TTL elects a single leader worker
- 15-second renewal thread maintains leadership
- Lua script atomic release prevents race conditions on shutdown
- Graceful fallback: if Redis is unavailable, worker assumes leadership (single-worker compatibility)
- Worker ID based on PID (each forked Uvicorn worker gets unique PID)

### Lifespan Integration (main.py)
- `acquire_leadership()` called during startup before background threads
- Only the leader worker starts scheduler, uptime, liveness, usage reset, email, and webhook delivery threads
- Follower workers serve HTTP requests only (no duplicate background work)
- `release_leadership()` called on shutdown

### Prometheus Metrics Endpoint (metrics.py + routers/system.py)
- GET /metrics and GET /v1/metrics return Prometheus text exposition format
- 15+ metrics: agents_total, agents_online, memory_keys_total, queue_jobs_total, messages_total, webhooks_active, schedules_active, http_requests_total, websocket_connections_active, uptime_ratio_30d, marketplace_tasks_total, users_total, worker_is_leader, process_uptime_seconds, process_start_time_seconds
- moltgrid_info gauge with version label
- Cached for 15 seconds via response_cache
- Each metric query is individually try/excepted so one failure does not break all metrics

### Deploy Configuration (deploy.sh)
- Auto-installs redis-server via apt if not present
- Enables and starts redis-server systemd service
- Health checks Redis with fallback warning
- Updates moltgrid.service to 4 workers with redis-server.service dependency
- systemctl daemon-reload after service file update

## Deviations from Plan

None. Plan executed exactly as written.

## Test Results

- 14 new tests (8 leader election, 7 metrics endpoint) all pass
- 337 existing tests pass with 4 skipped (unchanged)
- Total: 351 tests passing

## Commits

| Task | Name | Commit | Files |
|------|------|--------|-------|
| 1 | Leader election module | a71f3c1 | leader.py |
| 2 | Wire leader into lifespan | abbe839 | main.py |
| 3 | /metrics endpoint | fefa40d | metrics.py, routers/system.py |
| 4 | Deploy configuration | b63ec83 | deploy.sh |
| 5 | Tests | 94f6b91 | tests/test_leader_metrics.py |

## VPS Prerequisites

Redis must be installed on the VPS for leader election to work across workers. The updated deploy.sh handles this automatically. If deploying manually:

```bash
apt-get install -y redis-server
systemctl enable redis-server
systemctl start redis-server
```

Without Redis, the system falls back to single-worker behavior (all workers assume leadership and run background threads, which is the pre-existing behavior).
