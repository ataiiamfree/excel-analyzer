"""WebSocket event models shared by the API runner and React client."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Literal

from pydantic import BaseModel, Field

from app.api.schemas import PlanStepPayload, RunResult


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class ServerEvent(BaseModel):
    type: str
    seq: int
    ts: datetime = Field(default_factory=utc_now)


class RunStartEvent(ServerEvent):
    type: Literal["run.start"] = "run.start"
    message_id: str


class PlanReadyEvent(ServerEvent):
    type: Literal["plan.ready"] = "plan.ready"
    steps: list[PlanStepPayload]


class StepStartEvent(ServerEvent):
    type: Literal["step.start"] = "step.start"
    step_id: str
    index: int
    total: int
    description: str
    tool: str
    instruction: str


class ReasoningDeltaEvent(ServerEvent):
    type: Literal["reasoning.delta"] = "reasoning.delta"
    delta: str
    step_id: str | None = None


class StepEndEvent(ServerEvent):
    type: Literal["step.end"] = "step.end"
    step_id: str
    status: Literal["done", "failed"]
    stdout: str = ""
    error: str = ""
    files: list[str] = Field(default_factory=list)
    script_path: str | None = None
    duration_ms: int | None = None


class ReportDeltaEvent(ServerEvent):
    type: Literal["report.delta"] = "report.delta"
    delta: str


class ArtifactCreatedEvent(ServerEvent):
    type: Literal["artifact.created"] = "artifact.created"
    artifact_id: str
    name: str
    kind: str
    size: int
    message_id: str


class RunCompleteEvent(ServerEvent):
    type: Literal["run.complete"] = "run.complete"
    message_id: str
    report: str
    file_ids: list[str] = Field(default_factory=list)
    duration_ms: int
    result: RunResult | None = None


class RunFailedEvent(ServerEvent):
    type: Literal["run.failed"] = "run.failed"
    failed_step_description: str
    error_summary: str
    error_kind: Literal["timeout", "rate_limit", "analysis_failed", "other"] = "other"


class CancelledEvent(ServerEvent):
    type: Literal["cancelled"] = "cancelled"


class ClientErrorEvent(ServerEvent):
    type: Literal["error"] = "error"
    error_kind: Literal["invalid_message", "run_in_progress", "no_active_run"]
    summary: str


class ClientEvent(BaseModel):
    type: Literal["user_message", "cancel"]
    content: str | None = None
    client_msg_id: str | None = None
    resume_from_seq: int | None = None


JsonEvent = dict[str, Any]
