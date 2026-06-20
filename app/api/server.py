"""FastAPI entrypoint for ChatExcel."""

from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from app.api.deps import get_config, get_session_registry, get_store
from app.api.routers import artifacts, conversations, runs
from app.api.ws.manager import ConnectionManager
from app.api.ws.runner import run_conversation_query
from app.api.ws_events import ClientEvent

config = get_config()
app = FastAPI(title="ChatExcel API", version="0.1.0")
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

    async def send(payload: dict) -> None:
        await websocket.send_json(payload)

    try:
        while True:
            raw = await websocket.receive_json()
            event = ClientEvent(**raw)
            if event.type == "cancel":
                continue
            if event.type == "user_message" and event.content:
                await run_conversation_query(
                    store=store,
                    config=config,
                    sessions=sessions,
                    conversation_id=conversation_id,
                    query=event.content,
                    sender=send,
                )
    except WebSocketDisconnect:
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
