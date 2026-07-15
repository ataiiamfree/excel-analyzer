"""FastAPI entrypoint for ChatExcel."""

from __future__ import annotations

import asyncio
from contextlib import suppress
from pathlib import Path

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from app.api.deps import get_config, get_session_registry, get_store
from app.api.routers import artifacts, conversations, runs
from app.api.ws.manager import ConnectionManager
from app.api.ws.runner import run_conversation_query
from app.api.ws_events import ClientErrorEvent, ClientEvent
from pydantic import ValidationError

config = get_config()
app = FastAPI(title="ChatExcel API", version="0.9.0")
manager = ConnectionManager()

origins = [item.strip() for item in config.cors_origins.split(",") if item.strip()]
app.add_middleware(
    CORSMiddleware,
    allow_origins=origins or ["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(conversations.router)
app.include_router(artifacts.router)
app.include_router(runs.router)


@app.get("/api/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


@app.websocket("/ws/conversations/{conversation_id}")
async def conversation_ws(websocket: WebSocket, conversation_id: str) -> None:
    await manager.connect(conversation_id, websocket)
    store = get_store()
    sessions = get_session_registry()
    active_run: asyncio.Task | None = None

    async def send(payload: dict) -> None:
        await websocket.send_json(payload)

    async def send_client_error(error_kind: str, summary: str) -> None:
        event = ClientErrorEvent(
            seq=0,
            error_kind=error_kind,
            summary=summary,
        )
        await send(event.model_dump(mode="json"))

    async def execute_query(event: ClientEvent) -> None:
        try:
            await run_conversation_query(
                store=store,
                config=config,
                sessions=sessions,
                conversation_id=conversation_id,
                query=(event.content or "").strip(),
                client_msg_id=event.client_msg_id,
                sender=send,
            )
        except asyncio.CancelledError:
            pass
        except Exception:
            # The runner emits and persists a structured failure before an
            # unexpected transport error reaches this boundary.
            pass

    try:
        while True:
            raw = await websocket.receive_json()
            try:
                event = ClientEvent(**raw)
            except ValidationError:
                await send_client_error("invalid_message", "消息格式无效，请重试")
                continue
            if event.type == "cancel":
                if active_run is None or active_run.done():
                    await send_client_error("no_active_run", "当前没有正在运行的分析")
                    continue
                active_run.cancel()
                with suppress(asyncio.CancelledError):
                    await active_run
                active_run = None
                continue
            if event.type == "user_message" and event.content and event.content.strip():
                if active_run is not None and not active_run.done():
                    await send_client_error("run_in_progress", "当前分析仍在运行，请等待完成或先取消")
                    continue
                active_run = asyncio.create_task(execute_query(event))
    except WebSocketDisconnect:
        pass
    finally:
        if active_run is not None and not active_run.done():
            active_run.cancel()
            with suppress(asyncio.CancelledError):
                await active_run
        manager.disconnect(conversation_id, websocket)


web_dist = Path(config.web_dist_dir)
if web_dist.exists():
    app.mount("/assets", StaticFiles(directory=web_dist / "assets"), name="assets")

    @app.get("/{path:path}", include_in_schema=False)
    async def spa_fallback(path: str) -> FileResponse:
        target = web_dist / path
        if path and target.exists() and target.is_file():
            return FileResponse(target)
        return FileResponse(web_dist / "index.html")
