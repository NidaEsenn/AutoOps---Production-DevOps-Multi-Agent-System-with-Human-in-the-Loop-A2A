"""Pydantic models for the AutoOps A2A protocol."""

from datetime import UTC, datetime
from typing import Literal
from uuid import uuid4

from pydantic import BaseModel, Field


class A2ATask(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid4()))
    type: str
    input: dict
    status: Literal["submitted", "working", "completed", "failed", "cancelled"] = "submitted"
    output: dict | None = None
    error: str | None = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class AgentCapabilities(BaseModel):
    tasks: list[str]


class AgentAuthentication(BaseModel):
    type: Literal["none", "bearer", "oauth"]


class AgentCard(BaseModel):
    name: str
    version: str
    description: str
    url: str
    capabilities: AgentCapabilities
    authentication: AgentAuthentication

