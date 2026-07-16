"""v0.9.2 smoke：会话删除生命周期（真实 API + 真实 LLM）。

用法：`python scripts/smoke_delete_lifecycle.py`

场景：
  S1 空闲 WS 连接不阻塞删除（P1-6 修正回归）
  S2 分析运行中删除 → 409；run.complete 后删除 → 204
  S3 分析取消后删除 → 204

工作区与 DB 重定向到临时目录，不碰开发环境数据；S2 会执行一次
真实 LLM 分析（约 1 分钟），需要 .env 中配置 DEEPSEEK_API_KEY。
"""

import os
import sys
import tempfile
import time
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
_tmp = tempfile.TemporaryDirectory(prefix="smoke_delete_lifecycle_")
SCRATCH = Path(_tmp.name)
os.environ["WORKSPACE_DIR"] = str(SCRATCH / "workspace")
os.environ["API_DB_PATH"] = str(SCRATCH / "smoke.sqlite3")

sys.path.insert(0, str(REPO))
os.chdir(REPO)

from fastapi.testclient import TestClient  # noqa: E402

from app.api import server  # noqa: E402

client = TestClient(server.app)
DATASETS = REPO / "docs" / "test_datasets" / "simple"

FAILURES: list[str] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    mark = "✓" if ok else "✗"
    print(f"  {mark} {name}" + (f" — {detail}" if detail else ""), flush=True)
    if not ok:
        FAILURES.append(name)


def create_conversation(file_name: str) -> str:
    path = DATASETS / file_name
    with path.open("rb") as fh:
        resp = client.post(
            "/api/conversations",
            files={"file": (file_name, fh, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
        )
    assert resp.status_code == 200, f"create failed: {resp.status_code} {resp.text}"
    return resp.json()["id"]


def wait_no_active_run(conversation_id: str, timeout: float = 10.0) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if not server.manager.has_active_run(conversation_id):
            return True
        time.sleep(0.05)
    return False


def workspace_gone(conversation_id: str) -> bool:
    return not (SCRATCH / "workspace" / conversation_id).exists()


print("S1 空闲 WS 连接不阻塞删除", flush=True)
conv = create_conversation("12_设备巡检记录.xlsx")
with client.websocket_connect(f"/ws/conversations/{conv}"):
    check("WS 已连接", server.manager.has_connections(conv))
    check("无运行中分析", not server.manager.has_active_run(conv))
    resp = client.delete(f"/api/conversations/{conv}")
    check("空闲连接下删除返回 204", resp.status_code == 204, f"got {resp.status_code}")
check("会话已不存在（404）", client.get(f"/api/conversations/{conv}").status_code == 404)
check("workspace 目录已清理", workspace_gone(conv))

print("S2 运行中 409 → 完成后可删", flush=True)
conv = create_conversation("01_门店月度销售.xlsx")
with client.websocket_connect(f"/ws/conversations/{conv}") as ws:
    ws.send_json({
        "type": "user_message",
        "content": "哪家门店上半年总销售额最高？各门店排名如何？",
    })
    event = ws.receive_json()
    check("收到 run.start", event["type"] == "run.start", event["type"])

    resp = client.delete(f"/api/conversations/{conv}")
    check("运行中删除返回 409", resp.status_code == 409, f"got {resp.status_code}")
    check(
        "409 文案指向运行中分析",
        "正在运行" in resp.json().get("detail", ""),
        resp.text,
    )

    terminal = None
    while terminal is None:
        event = ws.receive_json()
        if event["type"] in ("run.complete", "run.failed"):
            terminal = event["type"]
    check("分析正常完成", terminal == "run.complete", terminal)
    check("运行标记已释放", wait_no_active_run(conv))

    resp = client.delete(f"/api/conversations/{conv}")
    check("完成后删除返回 204", resp.status_code == 204, f"got {resp.status_code}")
check("会话已不存在（404）", client.get(f"/api/conversations/{conv}").status_code == 404)
check("workspace 目录已清理", workspace_gone(conv))

print("S3 取消后可删", flush=True)
conv = create_conversation("07_客户与订单.xlsx")
with client.websocket_connect(f"/ws/conversations/{conv}") as ws:
    ws.send_json({
        "type": "user_message",
        "content": "订单取消率是多少？各客户取消订单数是多少？",
    })
    event = ws.receive_json()
    check("收到 run.start", event["type"] == "run.start", event["type"])

    # 第一次 cancel 终止分析；第二次 cancel 的 no_active_run 应答确保
    # handler 已完整 await 掉被取消的任务（含 end_run）。
    ws.send_json({"type": "cancel"})
    ws.send_json({"type": "cancel"})
    saw_no_active_run = False
    while not saw_no_active_run:
        event = ws.receive_json()
        if event["type"] == "error" and event.get("error_kind") == "no_active_run":
            saw_no_active_run = True
    check("取消握手完成", saw_no_active_run)
    check("运行标记已释放", wait_no_active_run(conv))

    resp = client.delete(f"/api/conversations/{conv}")
    check("取消后删除返回 204", resp.status_code == 204, f"got {resp.status_code}")
check("会话已不存在（404）", client.get(f"/api/conversations/{conv}").status_code == 404)
check("workspace 目录已清理", workspace_gone(conv))

print(flush=True)
if FAILURES:
    print(f"SMOKE FAILED: {len(FAILURES)} 项未通过: {FAILURES}")
    sys.exit(1)
print("SMOKE PASSED: 删除生命周期全部场景通过")
