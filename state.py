"""
MoltGrid Shared Mutable State — global state variables shared across modules.
Extracted from main.py to prevent circular imports when routers import state.
"""

import threading

# WebSocket connections: agent_id -> set of WebSocket objects
_ws_connections: dict[str, set] = {}

# SSE connections: agent_id -> set of asyncio.Queue objects (one per subscriber)
_sse_connections: dict[str, set] = {}

# Network WebSocket clients (lobby/broadcast)
_network_ws_clients: list = []

# Global embedding model (loaded lazily on first use)
_embed_model = None
_embed_lock = threading.Lock()

# IP-based auth rate limiting: ip -> [timestamps]
_auth_rate_limits: dict = {}
