"""
Production Smoke Test -- Run after each deploy to verify live API.

Usage:
    MOLTGRID_API_URL=https://api.moltgrid.net \
    MOLTGRID_API_KEY=mg_... \
    pytest tests/test_production_smoke.py -v

Each phase appends its own smoke tests. All prior phases' tests
run as regression checks on every deploy.
"""

import os
import json
import time
import uuid
import pytest
import httpx

API_URL = os.environ.get("MOLTGRID_API_URL", "https://api.moltgrid.net")
API_KEY = os.environ.get("MOLTGRID_API_KEY", "")

skip_if_no_key = pytest.mark.skipif(
    not API_KEY, reason="MOLTGRID_API_KEY not set -- skip production smoke tests"
)


@pytest.fixture(scope="module")
def api():
    """Shared httpx client for production API."""
    with httpx.Client(
        base_url=API_URL,
        headers={"X-API-Key": API_KEY},
        timeout=30.0
    ) as c:
        yield c


# ─── Health ────────────────────────────────────────────────────────────────

@skip_if_no_key
def test_health(api):
    """API is up and responding."""
    r = api.get("/v1/health")
    assert r.status_code == 200
    data = r.json()
    assert data.get("status") in ("ok", "healthy", "operational")


# ═══════════════════════════════════════════════════════════════════════════
# PHASE 57 SMOKE TESTS (added after Phase 57 deploys)
# ═══════════════════════════════════════════════════════════════════════════

# test_prod_namespace_injection_blocked
# test_prod_self_crossagent_read
# test_prod_visibility_patch_namespaced


# ═══════════════════════════════════════════════════════════════════════════
# PHASE 58 SMOKE TESTS (added after Phase 58 deploys)
# ═══════════════════════════════════════════════════════════════════════════

# test_prod_queue_claim_works
# test_prod_task_complete_endpoint
# test_prod_tasks_completed_counter


# ═══════════════════════════════════════════════════════════════════════════
# PHASE 59 SMOKE TESTS (added after Phase 59 deploys)
# ═══════════════════════════════════════════════════════════════════════════

# test_prod_mark_as_read
# test_prod_all_channel_inbox
# test_prod_invalid_cursor_400
# test_prod_negative_limit_422


# ═══════════════════════════════════════════════════════════════════════════
# PHASE 60 SMOKE TESTS (added after Phase 60 deploys)
# ═══════════════════════════════════════════════════════════════════════════

# test_prod_wildcard_pubsub
# test_prod_subscriber_count
# test_prod_event_cursor_dedup


# ═══════════════════════════════════════════════════════════════════════════
# PHASE 61 SMOKE TESTS (added after Phase 61 deploys)
# ═══════════════════════════════════════════════════════════════════════════

# test_prod_nginx_no_version
# test_prod_heartbeat_enum_rejects_invalid


# ═══════════════════════════════════════════════════════════════════════════
# PHASE 62 SMOKE TESTS (Playwright-based, separate invocation)
# ═══════════════════════════════════════════════════════════════════════════
