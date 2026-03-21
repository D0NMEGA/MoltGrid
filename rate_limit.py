"""
Shared rate limiter instance for MoltGrid.

Both main.py and routers import from here to avoid circular imports.
"""

from slowapi import Limiter
from slowapi.util import get_remote_address

limiter = Limiter(key_func=get_remote_address, default_limits=[])
