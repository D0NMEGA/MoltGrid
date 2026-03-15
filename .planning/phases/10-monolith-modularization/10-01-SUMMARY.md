---
phase: 10-monolith-modularization
plan: 01
subsystem: infrastructure
tags: [modularization, extraction, config, models, helpers]
dependency_graph:
  requires: []
  provides: [config.py, state.py, models.py, helpers.py, routers/__init__.py]
  affects: [main.py]
tech_stack:
  added: []
  patterns: [module-extraction, shared-state-isolation]
key_files:
  created:
    - config.py
    - state.py
    - models.py
    - helpers.py
    - routers/__init__.py
  modified: []
decisions:
  - "config.py duplicates JWT_SECRET ephemeral key generation (same logic as main.py)"
  - "_get_embed_model in helpers.py writes to state._embed_model via import to avoid stale closure"
  - "helpers.py includes _should_send_notification and _get_user_notification_prefs (needed by _check_usage_quota)"
  - "All new files are additive — main.py unchanged, zero test modifications"
metrics:
  duration: 8min
  completed: "2026-03-15T04:28:00Z"
---

# Phase 10 Plan 01: Foundation Module Extraction Summary

Extracted shared infrastructure from main.py (6752 lines) into four foundation modules plus a routers/ package directory, all additive with zero changes to main.py or test_main.py.

## One-liner

config.py + state.py + models.py + helpers.py extracted from main.py as importable foundation modules for future router extraction

## Tasks Completed

| Task | Name | Commit | Key Files |
|------|------|--------|-----------|
| 1 | Create config.py, state.py, models.py, routers/__init__.py | 322cba5 | config.py, state.py, models.py, routers/__init__.py |
| 2 | Create helpers.py with shared helper functions | f86181e | helpers.py |

## What Was Built

### config.py (91 lines)
All configuration constants and environment variable loading:
- Size limits (MAX_MEMORY_VALUE_SIZE, MAX_QUEUE_PAYLOAD_SIZE)
- Rate limiting (TIER_RATE_LIMITS, RATE_LIMIT_WINDOW)
- Subscription tiers (TIER_LIMITS)
- Admin, JWT, Stripe, SMTP, Turnstile config
- Encryption key and Fernet instance
- Logger instance

### state.py (20 lines)
Shared mutable state variables:
- _ws_connections (WebSocket tracking)
- _network_ws_clients (lobby broadcast)
- _embed_model + _embed_lock (embedding model singleton)
- _auth_rate_limits (IP-based brute force tracking)

### models.py (493 lines)
All 60+ Pydantic BaseModel subclasses organized by domain:
- Auth: SignupRequest, LoginRequest, ForgotPasswordRequest, etc.
- Dashboard: MemoryVisibilityRequest, TransferRequest, etc.
- Integrations: IntegrationCreateRequest, IntegrationStatusResponse, etc.
- Webhooks: WebhookRegisterRequest, WebhookResponse
- Queue: QueueSubmitRequest, QueueJobResponse, QueueFailRequest
- Relay: RelayMessage
- Memory: MemorySetRequest, MemoryGetResponse, MemoryListResponse
- Health: HealthStatsResponse, HealthResponse
- Vector: VectorUpsertRequest, VectorSearchRequest
- Directory: DirectoryUpdateRequest, StatusUpdateRequest
- Marketplace: MarketplaceCreateRequest, MarketplaceDeliverRequest
- PubSub: PubSubSubscribeRequest, PubSubPublishRequest
- Admin: AdminLoginRequest
- Sessions: SessionCreateRequest, SessionAppendRequest
- Contact: ContactForm
- Orgs: OrgCreateRequest, OrgInviteRequest, OrgRoleUpdateRequest
- Events: EventAckRequest, ObstacleCourseSubmitRequest

### helpers.py (988 lines)
All cross-cutting helper functions and background loops:
- Auth: hash_key, generate_api_key, _check_auth_rate_limit, get_agent_id, get_user_id, get_optional_user_id
- JWT: _create_token, _decode_token
- Encryption: _encrypt, _decrypt
- CAPTCHA: _verify_turnstile
- Ownership: _verify_agent_ownership
- Audit: _log_memory_access, _log_audit, _queue_agent_event
- Memory: _check_memory_visibility
- Email: _branded_email, _queue_email, _send_email_smtp
- Webhooks: _fire_webhooks, _is_safe_url, _run_webhook_delivery_tick, _webhook_delivery_loop
- Billing: _apply_tier, _get_or_create_stripe_customer, _tier_from_price
- Background: _scheduler_loop, _run_scheduler_tick, _uptime_loop, _uptime_check, _liveness_loop, _run_liveness_check, _usage_reset_loop, _run_usage_reset, _email_loop, _run_email_tick
- Misc: _http_code_to_slug, _track_event, _check_usage_quota, _sanitize_text, _get_client_ip, _get_embed_model, _check_onboarding_progress

### routers/__init__.py
Empty package marker for future router module extraction in Plan 02.

## Deviations from Plan

None -- plan executed exactly as written.

## Verification

- `python -c "import config; import state; import models; import helpers"` -- all 4 modules importable
- `pytest test_main.py -x -q` -- 332 passed, 4 skipped, 0 failures
- No circular imports between new modules
- main.py completely unchanged

## Self-Check: PASSED
