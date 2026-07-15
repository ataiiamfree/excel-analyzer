import asyncio
from types import SimpleNamespace

from app.api.deps import SessionRegistry
from app.api.persistence.store import Store
from app.api.ws import runner
from app.config import Config


class FakeRuntime:
    async def run(self, request):
        await request.callbacks["on_report_token"]("报告")
        return SimpleNamespace(failed=False, report="报告", files=[])


class FailedRuntime:
    async def run(self, request):
        return SimpleNamespace(
            failed=True,
            report="",
            files=[],
            failed_step_description="计算失败",
            error_summary="无法完成计算",
        )


class TimeoutRuntime:
    async def run(self, request):
        raise asyncio.TimeoutError("model timed out")


class LongReasoningRuntime:
    async def run(self, request):
        await request.callbacks["on_reasoning_token"]("x" * 25_000)
        return SimpleNamespace(failed=False, report="完成", files=[])


def test_run_conversation_persists_client_message_id(tmp_path, monkeypatch):
    monkeypatch.setattr(runner, "build_agent_runtime", lambda config: FakeRuntime())
    monkeypatch.setattr(runner, "build_llm_client", lambda config: None)
    store = Store(tmp_path / "chat.sqlite3")
    source = tmp_path / "source.xlsx"
    source.write_bytes(b"xlsx")
    store.create_conversation(
        conversation_id="conversation_1",
        title="追问测试",
        file_name="source.xlsx",
        file_size=source.stat().st_size,
        local_file_path=str(source),
    )
    config = Config(
        workspace_dir=str(tmp_path / "workspace"),
        api_db_path=str(tmp_path / "chat.sqlite3"),
    )

    asyncio.run(
        runner.run_conversation_query(
            store=store,
            config=config,
            sessions=SessionRegistry(),
            conversation_id="conversation_1",
            query="继续分析",
            client_msg_id="client-123",
        )
    )

    user_messages = [message for message in store.list_messages("conversation_1") if message["role"] == "user"]
    assert user_messages[0]["payload"]["client_msg_id"] == "client-123"


def test_failed_run_emits_failed_as_the_only_terminal_event(tmp_path, monkeypatch):
    monkeypatch.setattr(runner, "build_agent_runtime", lambda config: FailedRuntime())
    events = []

    async def sender(payload):
        events.append(payload)

    result = asyncio.run(
        runner.run_ephemeral_query(
            store=Store(tmp_path / "chat.sqlite3"),
            config=Config(workspace_dir=str(tmp_path / "workspace")),
            file_path=str(tmp_path / "source.xlsx"),
            query="计算",
            sender=sender,
        )
    )

    assert result.status == "failed"
    assert result.error["kind"] == "analysis_failed"
    assert [event["type"] for event in events if event["type"] in {"run.failed", "run.complete"}] == [
        "run.failed"
    ]


def test_timeout_returns_structured_failure_without_raising(tmp_path, monkeypatch):
    monkeypatch.setattr(runner, "build_agent_runtime", lambda config: TimeoutRuntime())
    events = []

    async def sender(payload):
        events.append(payload)

    result = asyncio.run(
        runner.run_ephemeral_query(
            store=Store(tmp_path / "chat.sqlite3"),
            config=Config(workspace_dir=str(tmp_path / "workspace"), run_timeout_seconds=1),
            file_path=str(tmp_path / "source.xlsx"),
            query="计算",
            sender=sender,
        )
    )

    assert result.status == "failed"
    assert result.error["kind"] == "timeout"
    assert events[-1]["type"] == "run.failed"
    assert events[-1]["error_kind"] == "timeout"


def test_reasoning_persistence_is_bounded(tmp_path, monkeypatch):
    monkeypatch.setattr(runner, "build_agent_runtime", lambda config: LongReasoningRuntime())
    monkeypatch.setattr(runner, "build_llm_client", lambda config: None)

    result = asyncio.run(
        runner.run_ephemeral_query(
            store=Store(tmp_path / "chat.sqlite3"),
            config=Config(workspace_dir=str(tmp_path / "workspace")),
            file_path=str(tmp_path / "source.xlsx"),
            query="计算",
        )
    )

    assert len(result.reasoning["text"]) == runner.MAX_PERSISTED_REASONING_CHARS
    assert result.reasoning["tokens"] == 6_250
