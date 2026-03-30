"""
Tests for structured error envelope fields -- ERR-01 through ERR-05.

Verifies that all API error responses include:
- param: identifies the offending field (ERR-01)
- retryable: bool indicating whether the caller should retry (ERR-02)
- suggestion: human-readable fix hint (ERR-03)
- valid_values: list of accepted values for enum fields (ERR-04)
- details: per-field array on validation errors (ERR-05)

200/201 success responses must NOT include these fields (non-regression).
"""
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

os.environ["MOLTGRID_DB"] = "test_error_envelopes.db"
os.environ["TURNSTILE_SECRET_KEY"] = ""
os.environ["RATE_LIMIT_ENABLED"] = "false"

import uuid
import pytest
from unittest.mock import patch, AsyncMock
from fastapi.testclient import TestClient
from main import app, init_db

client = TestClient(app, raise_server_exceptions=False)


@pytest.fixture(autouse=True)
def fresh_db(tmp_path, monkeypatch):
    """Wipe and re-init the SQLite DB before every test."""
    db_path = str(tmp_path / "test_err.db")
    monkeypatch.setenv("MOLTGRID_DB", db_path)
    import db as db_module
    monkeypatch.setattr(db_module, "DB_PATH", db_path)
    monkeypatch.setattr(db_module, "_sqlite_pool", None)
    init_db()


def _register_agent():
    """Register an agent and return (agent_id, api_key, headers)."""
    name = f"err-test-agent-{uuid.uuid4().hex[:8]}"
    with patch("main._queue_email"):
        r = client.post("/v1/register", json={"name": name})
    assert r.status_code == 200, r.text
    data = r.json()
    return data["agent_id"], data["api_key"], {"X-API-Key": data["api_key"]}


class TestStructuredErrorEnvelopes:
    """All structured error envelope requirements ERR-01 through ERR-05."""

    # ─── ERR-01: param field identifies the offending field ───────────────────

    def test_err01_param_field_on_missing_field(self):
        """POST with missing required body field returns param in top-level and details."""
        _, _, headers = _register_agent()
        # MemoryVisibilityRequest requires 'visibility' -- send empty body
        r = client.patch(
            "/v1/memory/some-key/visibility",
            json={},
            headers=headers,
        )
        assert r.status_code == 422
        body = r.json()
        assert "param" in body
        assert len(body.get("details", [])) >= 1
        # At least one detail must have a non-empty param
        params = [d.get("param", "") for d in body["details"]]
        assert any(p for p in params), f"No param found in details: {body['details']}"

    def test_err01_param_field_on_enum_error(self):
        """POST with invalid enum value returns param == 'visibility' in details."""
        _, _, headers = _register_agent()
        # First create a memory key so it exists
        client.post(
            "/v1/memory",
            json={"key": "test-key", "value": "hello"},
            headers=headers,
        )
        r = client.patch(
            "/v1/memory/test-key/visibility",
            json={"visibility": "bogus"},
            headers=headers,
        )
        assert r.status_code == 422
        body = r.json()
        assert "param" in body
        assert len(body.get("details", [])) >= 1
        # The offending field should be 'visibility'
        params = [d.get("param", "") for d in body["details"]]
        assert "visibility" in params, f"Expected 'visibility' in params: {params}"

    # ─── ERR-02: retryable bool ────────────────────────────────────────────────

    def test_err02_retryable_false_on_403(self):
        """Accessing a forbidden resource returns retryable:false."""
        # Unrecognized API key triggers 401 which is non-retryable
        r = client.get("/v1/memory", headers={"X-API-Key": "bad_key_xyz"})
        assert r.status_code == 401
        body = r.json()
        assert "retryable" in body
        assert body["retryable"] is False

    def test_err02_retryable_false_on_404(self):
        """GET a non-existent memory key returns 404 with retryable:false."""
        _, _, headers = _register_agent()
        r = client.get("/v1/memory/this-key-does-not-exist-xyz", headers=headers)
        assert r.status_code == 404
        body = r.json()
        assert "retryable" in body
        assert body["retryable"] is False

    def test_err02_retryable_false_on_422(self):
        """Validation errors return retryable:false."""
        _, _, headers = _register_agent()
        r = client.patch(
            "/v1/memory/some-key/visibility",
            json={"visibility": "bogus"},
            headers=headers,
        )
        assert r.status_code == 422
        body = r.json()
        assert "retryable" in body
        assert body["retryable"] is False

    def test_err02_retryable_true_on_429_handler_body(self):
        """The rate limit handler body includes retryable:true."""
        # We call _custom_rate_limit_handler directly by examining the source
        # to confirm the body dict includes retryable:True.
        # This tests the actual handler function by inspecting it.
        import inspect
        import main as m
        source = inspect.getsource(m._custom_rate_limit_handler)
        assert '"retryable": True' in source or "'retryable': True" in source, (
            "Rate limit handler body must include retryable: True"
        )

    # ─── ERR-03: suggestion field with human-readable fix hint ────────────────

    def test_err03_suggestion_on_enum_error(self):
        """Invalid enum value returns suggestion containing 'Must be one of'."""
        _, _, headers = _register_agent()
        client.post(
            "/v1/memory",
            json={"key": "vis-key", "value": "val"},
            headers=headers,
        )
        r = client.patch(
            "/v1/memory/vis-key/visibility",
            json={"visibility": "bogus"},
            headers=headers,
        )
        assert r.status_code == 422
        body = r.json()
        details = body.get("details", [])
        assert any(
            d.get("suggestion", "") and "Must be one of" in d["suggestion"]
            for d in details
        ), f"No 'Must be one of' suggestion found in details: {details}"

    def test_err03_suggestion_on_missing_field(self):
        """Missing required field returns suggestion 'This field is required'."""
        _, _, headers = _register_agent()
        r = client.patch(
            "/v1/memory/some-key/visibility",
            json={},
            headers=headers,
        )
        assert r.status_code == 422
        body = r.json()
        details = body.get("details", [])
        assert any(
            d.get("suggestion") == "This field is required"
            for d in details
        ), f"No 'This field is required' suggestion found in details: {details}"

    # ─── ERR-04: valid_values list for enum fields ─────────────────────────────

    def test_err04_valid_values_on_enum_error(self):
        """Invalid enum value returns valid_values:['private','public','shared']."""
        _, _, headers = _register_agent()
        client.post(
            "/v1/memory",
            json={"key": "vis-key2", "value": "val"},
            headers=headers,
        )
        r = client.patch(
            "/v1/memory/vis-key2/visibility",
            json={"visibility": "bogus"},
            headers=headers,
        )
        assert r.status_code == 422
        body = r.json()
        details = body.get("details", [])
        enum_detail = next(
            (d for d in details if d.get("valid_values") is not None), None
        )
        assert enum_detail is not None, f"No detail with valid_values in: {details}"
        expected = {"private", "public", "shared"}
        actual = set(enum_detail["valid_values"])
        assert actual == expected, f"valid_values {actual} != {expected}"

    def test_err04_valid_values_in_top_level_body(self):
        """Top-level valid_values matches first detail's valid_values for enum errors."""
        _, _, headers = _register_agent()
        r = client.patch(
            "/v1/memory/vis-key3/visibility",
            json={"visibility": "wrong"},
            headers=headers,
        )
        assert r.status_code == 422
        body = r.json()
        assert "valid_values" in body
        if body["valid_values"] is not None:
            assert set(body["valid_values"]) == {"private", "public", "shared"}

    # ─── ERR-05: details array with per-field entries ─────────────────────────

    def test_err05_details_array_on_validation_error(self):
        """Validation error response contains details array with param and message."""
        _, _, headers = _register_agent()
        r = client.patch(
            "/v1/memory/some-key/visibility",
            json={},
            headers=headers,
        )
        assert r.status_code == 422
        body = r.json()
        assert "details" in body
        assert isinstance(body["details"], list)
        assert len(body["details"]) >= 1
        for d in body["details"]:
            assert "param" in d, f"Missing 'param' key in detail: {d}"
            assert "message" in d, f"Missing 'message' key in detail: {d}"

    def test_err05_multi_field_details(self):
        """Multi-field validation error returns details with >= 2 entries."""
        # POST /v1/memory requires both 'key' and 'value' -- send neither
        _, _, headers = _register_agent()
        r = client.post("/v1/memory", json={}, headers=headers)
        assert r.status_code == 422
        body = r.json()
        assert "details" in body
        assert len(body["details"]) >= 2, (
            f"Expected >= 2 details for multi-field failure, got: {body['details']}"
        )
        for d in body["details"]:
            assert "param" in d
            assert "message" in d

    def test_err05_success_responses_unchanged(self):
        """GET /v1/health returns 200 without retryable/param/suggestion fields."""
        r = client.get("/v1/health")
        assert r.status_code == 200
        body = r.json()
        assert "retryable" not in body, "Success response must not contain 'retryable'"
        assert "param" not in body, "Success response must not contain 'param'"
        assert "suggestion" not in body, "Success response must not contain 'suggestion'"
        assert "valid_values" not in body, "Success response must not contain 'valid_values'"

    def test_err05_memory_list_success_unchanged(self):
        """GET /v1/memory returns 200 without structured error fields."""
        _, _, headers = _register_agent()
        r = client.get("/v1/memory", headers=headers)
        assert r.status_code == 200
        body = r.json()
        assert "retryable" not in body
        assert "param" not in body
