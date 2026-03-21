"""
Shared rate limiter instance for MoltGrid.

Both main.py and routers import from here to avoid circular imports.
Rate limiting is disabled when RATE_LIMIT_ENABLED=false (e.g. in tests).

Uses Redis storage when REDIS_URL is available for cross-worker rate limit
state sharing. Falls back to in-memory storage otherwise.
"""

import os
import logging

from slowapi import Limiter
from slowapi.util import get_remote_address

logger = logging.getLogger("moltgrid.rate_limit")

_rate_limit_enabled = os.getenv("RATE_LIMIT_ENABLED", "true").lower() != "false"
_redis_url = os.getenv("REDIS_URL", "")

# Build storage URI for slowapi/limits
# slowapi passes storage_uri to the limits library which handles Redis natively
_storage_uri = None
if _redis_url:
    _storage_uri = _redis_url
    logger.info(f"Rate limiter using Redis storage")
else:
    logger.info("Rate limiter using in-memory storage (no REDIS_URL)")


def _get_key_func(request):
    """Smart key function that differentiates by auth type.

    - Agent API key endpoints: key by API key hash
    - JWT user endpoints: key by Authorization header hash
    - Unauthenticated: key by IP address
    """
    # Try X-API-Key first (agent endpoints)
    api_key = request.headers.get("x-api-key")
    if api_key:
        import hashlib
        return hashlib.sha256(api_key.encode()).hexdigest()[:16]

    # Try JWT Authorization header (dashboard/user endpoints)
    auth_header = request.headers.get("authorization")
    if auth_header and auth_header.startswith("Bearer "):
        import hashlib
        return hashlib.sha256(auth_header.encode()).hexdigest()[:16]

    # Fallback: IP address
    return get_remote_address(request)


limiter = Limiter(
    key_func=_get_key_func,
    default_limits=["120/minute"],
    enabled=_rate_limit_enabled,
    storage_uri=_storage_uri,
)
