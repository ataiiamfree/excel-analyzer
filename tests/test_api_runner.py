import asyncio
from types import SimpleNamespace

from app.api.deps import SessionRegistry
from app.api.persistence.store import Store
from app.api.ws import runner
from app.config import Config


class FakeOrchestrator:
    llm = None

    async def run(self, **kwargs):
        await kwargs["on_report_token"]("报告")
        return SimpleNamespace(failed=False, report="报告", files=[])


def test_run_conversation_persists_client_message_id(tmp_path, monkeypatch):
    monkeypatch.setattr(runner, "build_orchestrator", lambda config: FakeOrchestrator())
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
    config = Config(workspace_dir=str(tmp_path / "workspace"), api_db_path=str(tmp_path / "chat.sqlite3"))

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
