"""
Shared rate limiter instance for MoltGrid.

Both main.py and routers import from here to avoid circular imports.
Rate limiting is disabled when RATE_LIMIT_ENABLED=false (e.g. in tests).
"""

import os

from slowapi import Limiter
from slowapi.util import get_remote_address

_rate_limit_enabled = os.getenv("RATE_LIMIT_ENABLED", "true").lower() != "false"

limiter = Limiter(
    key_func=get_remote_address,
    default_limits=[],
    enabled=_rate_limit_enabled,
)
