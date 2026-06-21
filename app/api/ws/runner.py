"""Run orchestration for REST and WebSocket API entrypoints."""

from __future__ import annotations

import asyncio
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Awaitable, Callable

from app.agent.runtime import RuntimeRequest, build_agent_runtime
from app.agent.types import StepResult
from app.agent.next_actions import generate_next_actions
from app.agent.plan import ExecutionPlan, Step
from app.api.artifact_utils import artifact_metadata_from_manifest, artifact_urls, infer_artifact_kind, sha256_file
from app.api.deps import SessionRegistry
from app.api.persistence.store import Store
from app.api.schemas import RunArtifact, RunResult
from app.api.ws_events import (
    ArtifactCreatedEvent,
    CancelledEvent,
    PlanReadyEvent,
    ReasoningDeltaEvent,
    ReportDeltaEvent,
    RunCompleteEvent,
    RunFailedEvent,
    RunStartEvent,
    StepEndEvent,
    StepStartEvent,
)
from app.config import Config
from app.llm.client import build_llm_client
from app.session import Session
from app.workspace import Workspace


EventSender = Callable[[dict[str, Any]], Awaitable[None]]


class EventEmitter:
    def __init__(self, sender: EventSender | None = None) -> None:
        self.seq = 0
        self.sender = sender
        self.events: list[dict[str, Any]] = []

    async def emit(self, event: Any) -> None:
        self.seq += 1
        event.seq = self.seq
        payload = event.model_dump(mode="json")
        self.events.append(payload)
        if self.sender is not None:
            await self.sender(payload)


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def plan_step_payload(step: Step) -> dict[str, Any]:
    return {
        "id": step.id,
        "tool": step.tool,
        "description": step.description,
        "instruction": step.instruction,
        "depends_on": step.depends_on,
        "is_exploratory": step.is_exploratory,
    }


def initial_payload(query: str, started_at: datetime) -> dict[str, Any]:
    return {
        "status": "running",
        "query": query,
        "plan": {"steps": []},
        "reasoning": {"text": "", "tokens": 0},
        "steps": [],
        "report": "",
        "next_actions": [],
        "artifact_ids": [],
        "metrics": {"started_at": started_at.isoformat()},
    }


def output_path_for_file(workspace: Workspace, file_path: str) -> tuple[Path, str]:
    path = Path(file_path)
    if not path.is_absolute():
        path = Path(workspace.path) / path
    try:
        rel_path = str(path.resolve().relative_to(Path(workspace.path).resolve()))
    except ValueError:
        rel_path = str(path.resolve())
    return path, rel_path


def artifact_out(row: dict[str, Any]) -> dict[str, Any]:
    data = {
        "id": row["id"],
        "conversation_id": row.get("conversation_id"),
        "message_id": row.get("message_id"),
        "kind": row["kind"],
        "name": row["name"],
        "size": row["size"],
        "created_at": row["created_at"],
        "sha256": row.get("sha256"),
        **artifact_urls(row["id"], row["kind"]),
    }
    metadata = row.get("metadata") or {}
    if isinstance(metadata, dict):
        data.update(metadata)
    for key in (
        "description",
        "producer_step_id",
        "producer_tool",
        "input_artifact_ids",
        "source_tables",
        "script_path",
        "stdout_summary",
        "row_count",
        "chart_metadata",
    ):
        if key in row and key not in data:
            data[key] = row.get(key)
    return data


async def run_conversation_query(
    *,
    store: Store,
    config: Config,
    sessions: SessionRegistry,
    conversation_id: str,
    query: str,
    client_msg_id: str | None = None,
    sender: EventSender | None = None,
) -> RunResult:
    conversation = store.get_conversation(conversation_id)
    session = sessions.get_or_create(conversation)
    return await _run_query(
        store=store,
        config=config,
        session=session,
        query=query,
        client_msg_id=client_msg_id,
        sender=sender,
        conversation_id=conversation_id,
        persist_messages=True,
    )


async def run_ephemeral_query(
    *,
    store: Store,
    config: Config,
    file_path: str,
    query: str,
    sender: EventSender | None = None,
) -> RunResult:
    run_id = f"run_{uuid.uuid4().hex}"
    session = Session(session_id=run_id, file_path=file_path)
    return await _run_query(
        store=store,
        config=config,
        session=session,
        query=query,
        client_msg_id=None,
        sender=sender,
        conversation_id=None,
        persist_messages=False,
    )


async def _run_query(
    *,
    store: Store,
    config: Config,
    session: Session,
    query: str,
    client_msg_id: str | None,
    sender: EventSender | None,
    conversation_id: str | None,
    persist_messages: bool,
) -> RunResult:
    emitter = EventEmitter(sender)
    started_at = utc_now()
    run_id = f"run_{uuid.uuid4().hex}"
    user_message_id: str | None = None
    assistant_message_id = uuid.uuid4().hex
    payload = initial_payload(query, started_at)
    step_starts: dict[str, datetime] = {}

    if persist_messages and conversation_id is not None:
        attached_file = {
            "name": store.get_conversation(conversation_id).get("file_name"),
            "size": store.get_conversation(conversation_id).get("file_size"),
        }
        user = store.create_message(
            conversation_id=conversation_id,
            role="user",
            payload={"text": query, "attached_file": attached_file, "client_msg_id": client_msg_id},
        )
        user_message_id = user["id"]
        store.create_message(
            conversation_id=conversation_id,
            role="assistant",
            payload=payload,
            message_id=assistant_message_id,
        )

    await emitter.emit(RunStartEvent(seq=0, message_id=assistant_message_id))
    agent_runtime = build_agent_runtime(config)

    async def persist_payload() -> None:
        if persist_messages:
            store.update_message_payload(assistant_message_id, payload)

    async def on_plan_ready(plan: ExecutionPlan) -> None:
        steps = [plan_step_payload(step) for step in plan.steps]
        payload["plan"] = {"steps": steps}
        await persist_payload()
        await emitter.emit(PlanReadyEvent(seq=0, steps=steps))

    async def on_step_start(step: Step, step_index: int, total_steps: int) -> None:
        now = utc_now()
        step_starts[step.id] = now
        payload["steps"].append(
            {
                "step_id": step.id,
                "status": "running",
                "started_at": now.isoformat(),
                "artifact_ids": [],
            }
        )
        await persist_payload()
        await emitter.emit(
            StepStartEvent(
                seq=0,
                step_id=step.id,
                index=step_index,
                total=total_steps,
                description=step.description,
                tool=step.tool,
                instruction=step.instruction,
            )
        )

    async def on_reasoning_token(token: str) -> None:
        if not token:
            return
        reasoning = payload.setdefault("reasoning", {"text": "", "tokens": 0})
        reasoning["text"] = (reasoning.get("text") or "") + token
        reasoning["tokens"] = int(reasoning.get("tokens") or 0) + max(1, len(token) // 4)
        await emitter.emit(ReasoningDeltaEvent(seq=0, delta=token))

    async def on_step_end(step: Step, result: StepResult) -> None:
        ended_at = utc_now()
        started = step_starts.get(step.id)
        duration_ms = int((ended_at - started).total_seconds() * 1000) if started else None
        for record in payload["steps"]:
            if record["step_id"] == step.id:
                record.update(
                    {
                        "status": "failed" if result.failed else "done",
                        "ended_at": ended_at.isoformat(),
                        "stdout": result.stdout,
                        "error": result.error,
                        "script_path": result.script_path,
                    }
                )
                break
        await persist_payload()
        await emitter.emit(
            StepEndEvent(
                seq=0,
                step_id=step.id,
                status="failed" if result.failed else "done",
                stdout=result.stdout,
                error=result.error,
                files=result.files,
                script_path=result.script_path,
                duration_ms=duration_ms,
            )
        )

    async def on_report_token(token: str) -> None:
        if not token:
            return
        payload["report"] = payload.get("report", "") + token
        await emitter.emit(ReportDeltaEvent(seq=0, delta=token))

    try:
        task_result = await asyncio.wait_for(
            agent_runtime.run(
                RuntimeRequest(
                    query=query,
                    session=session,
                    callbacks={
                        "on_step_start": on_step_start,
                        "on_step_end": on_step_end,
                        "on_plan_ready": on_plan_ready,
                        "on_report_token": on_report_token,
                        "on_reasoning_token": on_reasoning_token,
                    },
                )
            ),
            timeout=config.run_timeout_seconds,
        )
    except asyncio.CancelledError:
        payload["status"] = "cancelled"
        await persist_payload()
        await emitter.emit(CancelledEvent(seq=0))
        raise
    except Exception as exc:
        payload["status"] = "failed"
        payload["error"] = {
            "failed_step_description": "",
            "summary": f"{type(exc).__name__}: {exc}",
        }
        await persist_payload()
        await emitter.emit(
            RunFailedEvent(
                seq=0,
                failed_step_description="",
                error_summary=payload["error"]["summary"],
            )
        )
        raise

    ended_at = utc_now()
    duration_ms = int((ended_at - started_at).total_seconds() * 1000)
    workspace = Workspace(root=config.workspace_dir, task_id=session.session_id)
    artifacts = []
    artifact_ids: list[str] = []
    for file_path in task_result.files:
        path, stored_path = output_path_for_file(workspace, file_path)
        if not path.exists():
            continue
        kind = infer_artifact_kind(path)
        sha = sha256_file(path)
        manifest_item = workspace.find_artifact_by_path(stored_path)
        metadata = artifact_metadata_from_manifest(manifest_item)
        row = store.create_artifact(
            conversation_id=conversation_id,
            message_id=assistant_message_id if persist_messages else None,
            path=stored_path,
            kind=kind,
            name=path.name,
            size=path.stat().st_size,
            sha256=sha,
            metadata=metadata,
        )
        artifact_ids.append(row["id"])
        artifact = artifact_out(row)
        artifacts.append(artifact)
        await emitter.emit(
            ArtifactCreatedEvent(
                seq=0,
                artifact_id=row["id"],
                name=row["name"],
                kind=row["kind"],
                size=row["size"],
                message_id=assistant_message_id,
            )
        )

    payload["status"] = "failed" if task_result.failed else "done"
    payload["report"] = task_result.report or payload.get("report", "")
    payload["artifact_ids"] = artifact_ids
    if not task_result.failed:
        payload["next_actions"] = await generate_next_actions(
            llm_client=build_llm_client(config),
            query=query,
            report=payload["report"],
            steps=payload["steps"],
            artifacts=artifacts,
        )
    payload["metrics"].update(
        {
            "duration_ms": duration_ms,
            "started_at": started_at.isoformat(),
            "ended_at": ended_at.isoformat(),
            "user_message_id": user_message_id,
        }
    )
    if task_result.failed:
        payload["error"] = {
            "failed_step_description": task_result.failed_step_description,
            "summary": task_result.error_summary,
        }
        await emitter.emit(
            RunFailedEvent(
                seq=0,
                failed_step_description=task_result.failed_step_description,
                error_summary=task_result.error_summary,
            )
        )
    await persist_payload()
    result = RunResult(
        **payload,
        run_id=run_id,
        conversation_id=conversation_id,
        artifacts=[RunArtifact(**artifact) for artifact in artifacts],
    )
    await emitter.emit(
        RunCompleteEvent(
            seq=0,
            message_id=assistant_message_id,
            report=payload["report"],
            file_ids=artifact_ids,
            duration_ms=duration_ms,
            result=result,
        )
    )
    return result
