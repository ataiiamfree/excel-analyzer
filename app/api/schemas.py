"""HTTP payload schemas for the ChatExcel API."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field


ArtifactKind = Literal["chart", "excel", "csv", "report", "file", "data", "normalized_table"]
MessageRole = Literal["user", "assistant"]
RunStatus = Literal["running", "done", "failed", "cancelled"]


class FileAttachment(BaseModel):
    name: str
    size: int | None = None


class ConversationOut(BaseModel):
    id: str
    title: str
    file_name: str | None = None
    file_size: int | None = None
    sheet_count: int | None = None
    row_count: int | None = None
    created_at: datetime
    updated_at: datetime
    starred: bool = False
    archived_at: datetime | None = None


class ConversationGroup(BaseModel):
    label: str
    conversations: list[ConversationOut]


class ConversationListOut(BaseModel):
    groups: list[ConversationGroup]


class ConversationUpdate(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=120)
    starred: bool | None = None
    archived: bool | None = None


class MessageOut(BaseModel):
    id: str
    conversation_id: str
    role: MessageRole
    created_at: datetime
    payload: dict[str, Any]


class ArtifactOut(BaseModel):
    id: str
    conversation_id: str | None = None
    message_id: str | None = None
    kind: ArtifactKind
    name: str
    size: int
    created_at: datetime
    url: str
    preview_url: str | None = None
    sha256_url: str | None = None
    sha256: str | None = None
    description: str | None = None
    producer_step_id: str | None = None
    producer_tool: str | None = None
    input_artifact_ids: list[str] = Field(default_factory=list)
    source_tables: list[str] = Field(default_factory=list)
    script_path: str | None = None
    stdout_summary: str | None = None
    row_count: int | None = None
    chart_metadata: dict[str, Any] = Field(default_factory=dict)


class PlanStepPayload(BaseModel):
    id: str
    tool: Literal["python", "artifact_qa"] | str = "python"
    description: str = ""
    instruction: str = ""
    depends_on: list[str] = Field(default_factory=list)
    is_exploratory: bool = False


class StepRecordPayload(BaseModel):
    step_id: str
    status: Literal["pending", "running", "done", "failed", "cancelled"] = "pending"
    started_at: datetime | None = None
    ended_at: datetime | None = None
    stdout: str | None = None
    error: str | None = None
    script_path: str | None = None
    artifact_ids: list[str] = Field(default_factory=list)


class AssistantMessagePayload(BaseModel):
    status: RunStatus
    query: str
    plan: dict[str, list[PlanStepPayload]] = Field(default_factory=lambda: {"steps": []})
    reasoning: dict[str, Any] | None = None
    steps: list[StepRecordPayload] = Field(default_factory=list)
    report: str = ""
    next_actions: list[str] = Field(default_factory=list)
    artifact_ids: list[str] = Field(default_factory=list)
    metrics: dict[str, Any] = Field(default_factory=dict)
    error: dict[str, str] | None = None


class UserRunRequest(BaseModel):
    query: str = Field(min_length=1)
    stream: bool = False
    params: dict[str, Any] = Field(default_factory=dict)


class RunArtifact(ArtifactOut):
    sha256: str


class RunResult(AssistantMessagePayload):
    run_id: str
    conversation_id: str | None = None
    artifacts: list[RunArtifact] = Field(default_factory=list)


class RunStatusOut(BaseModel):
    run_id: str
    conversation_id: str | None = None
    status: RunStatus
    progress: dict[str, Any] = Field(default_factory=dict)


class TablePreviewOut(BaseModel):
    columns: list[str]
    rows: list[dict[str, Any]]
    row_count: int
