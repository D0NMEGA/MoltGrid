"""Pydantic v2 models for all MoltGrid API responses."""

from __future__ import annotations

from typing import Any, Optional

from pydantic import BaseModel


class RegisterResponse(BaseModel):
    agent_id: str
    api_key: str
    message: str


class MemoryEntry(BaseModel):
    key: str
    value: str
    namespace: str
    created_at: str
    expires_at: Optional[str] = None


class MemoryListResponse(BaseModel):
    entries: list[MemoryEntry]


class QueueJob(BaseModel):
    job_id: str
    agent_id: str
    queue_name: str
    payload: Any
    priority: int
    status: str
    attempts: int
    max_attempts: int
    retry_delay_seconds: int
    created_at: str
    claimed_at: Optional[str] = None
    completed_at: Optional[str] = None
    result: Optional[str] = None
    error: Optional[str] = None


class Message(BaseModel):
    message_id: str
    from_agent: str
    to_agent: str
    channel: str
    payload: str
    read: bool
    created_at: str


class InboxResponse(BaseModel):
    messages: list[Message]


class VectorMatch(BaseModel):
    key: str
    value: str
    namespace: str
    similarity: float
    created_at: str


class VectorSearchResponse(BaseModel):
    results: list[VectorMatch]
