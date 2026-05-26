"""Chainlit chat interface for Excel analysis agent."""

from __future__ import annotations

import logging
import os
import sys
import mimetypes
from pathlib import Path

# Ensure project root is on sys.path so `app.*` imports work when
# Chainlit runs this file directly.
_PROJECT_ROOT = str(Path(__file__).resolve().parent.parent)
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

from dotenv import load_dotenv
load_dotenv(Path(_PROJECT_ROOT) / ".env")

# ── 日志配置 ──────────────────────────────────────────────
_LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO").upper()
_LOG_FILE = Path(_PROJECT_ROOT) / "runtime.log"
_handlers: list[logging.Handler] = [logging.StreamHandler()]
_handlers.append(logging.FileHandler(_LOG_FILE, encoding="utf-8"))
logging.basicConfig(
    level=getattr(logging, _LOG_LEVEL, logging.INFO),
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%H:%M:%S",
    handlers=_handlers,
)

import chainlit as cl

from app.agent.orchestrator import build_orchestrator, StepResult
from app.agent.plan import Step
from app.session import Session


logger = logging.getLogger(__name__)


EXCEL_EXTENSIONS = {".xlsx", ".xlsm"}
DOWNLOADABLE_EXTENSIONS = {
    ".xlsx", ".xlsm", ".xls", ".csv", ".tsv", ".parquet", ".pdf",
    ".png", ".jpg", ".jpeg", ".svg",
}


def _report_for_ui(report: str) -> str:
    """Remove relative artifact links that are sent separately as elements."""
    marker = "\n## 附件"
    if marker in report:
        return report.split(marker, 1)[0].rstrip()
    if report.startswith("## 附件"):
        return ""
    return report


def _mime_for_path(path: str) -> str:
    suffix = Path(path).suffix.lower()
    if suffix in {".xlsx", ".xlsm"}:
        return "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    guessed, _ = mimetypes.guess_type(path)
    return guessed or "application/octet-stream"


def _extract_excel_from_message(message: cl.Message) -> cl.File | None:
    """If the message has an Excel attachment, return it."""
    for elem in (message.elements or []):
        if isinstance(elem, cl.File):
            suffix = Path(elem.name or "").suffix.lower()
            if suffix in EXCEL_EXTENSIONS:
                return elem
    return None


async def _setup_session(file_path: str, file_name: str):
    """Create a new session and orchestrator for the given file."""
    session = Session.create(file_path=file_path)
    cl.user_session.set("session", session)
    cl.user_session.set("orchestrator", build_orchestrator())
    cl.user_session.set("current_file", file_name)
    logger.info("新建 session: file=%s", file_name)


@cl.on_chat_start
async def start():
    """Ask the user to upload an Excel file and create a session."""
    files = await cl.AskFileMessage(
        content="请上传 Excel 文件（.xlsx/.xlsm），然后输入你的分析需求。",
        accept=["*/*"],
        max_size_mb=100,
    ).send()

    if not files:
        await cl.Message(content="未收到文件，请重新上传。").send()
        return

    uploaded = files[0]
    suffix = Path(uploaded.name).suffix.lower()
    if suffix not in EXCEL_EXTENSIONS:
        await cl.Message(content="目前请上传 .xlsx 或 .xlsm 文件。").send()
        return

    await _setup_session(uploaded.path, uploaded.name)
    await cl.Message(content=f"已上传 **{uploaded.name}**，请输入你的分析需求。\n\n💡 分析完成后可以继续追问，也可以直接发送新的 Excel 文件切换数据。").send()


@cl.on_message
async def main(message: cl.Message):
    """Handle user analysis queries, follow-ups, and new file uploads."""

    # ── 检测是否发送了新 Excel 文件 ──────────────────────
    new_file = _extract_excel_from_message(message)
    if new_file and new_file.path:
        await _setup_session(new_file.path, new_file.name or "unknown.xlsx")
        current_file = cl.user_session.get("current_file")
        query = (message.content or "").strip()
        if not query:
            await cl.Message(content=f"已切换到 **{current_file}**，请输入你的分析需求。").send()
            return
        # 有文件也有问题文本，继续往下走分析流程

    session: Session | None = cl.user_session.get("session")
    if session is None:
        await cl.Message(content="请先上传 Excel 文件。你可以直接在对话框发送 .xlsx 文件。").send()
        return

    orchestrator = cl.user_session.get("orchestrator")
    current_file = cl.user_session.get("current_file") or "Excel"

    # Progress callbacks — show each step as a collapsible Chainlit Step
    async def on_step_start(step: Step):
        cl_step = cl.Step(name=step.description)
        await cl_step.__aenter__()
        cl.user_session.set("current_cl_step", cl_step)

    async def on_step_end(step: Step, result: StepResult):
        cl_step: cl.Step | None = cl.user_session.get("current_cl_step")
        if cl_step:
            cl_step.output = result.stdout[:500] if result.stdout else "(完成)"
            await cl_step.__aexit__(None, None, None)
            cl.user_session.set("current_cl_step", None)

    # Run the analysis
    await cl.Message(content=f"正在分析 **{current_file}**，请稍候...").send()
    try:
        task_result = await orchestrator.run(
            query=message.content,
            session=session,
            on_step_start=on_step_start,
            on_step_end=on_step_end,
        )
    except Exception as e:
        logger.exception("分析过程出错")
        await cl.Message(content=f"分析过程出错：{e}").send()
        return

    # Send report
    report_text = _report_for_ui(task_result.report)
    if report_text:
        await cl.Message(content=report_text).send()

    # Send charts and downloadable files
    elements: list[cl.Element] = []
    for fpath in task_result.files:
        name = os.path.basename(fpath)
        full_path = fpath if os.path.isabs(fpath) else str(Path(fpath))
        if not os.path.exists(full_path):
            continue
        suffix = Path(full_path).suffix.lower()
        if suffix not in DOWNLOADABLE_EXTENSIONS:
            continue
        if suffix in {".png", ".jpg", ".jpeg", ".svg"}:
            elements.append(cl.Image(path=full_path, name=name, display="inline"))
        else:
            elements.append(cl.File(path=full_path, name=name, mime=_mime_for_path(full_path)))

    if elements:
        await cl.Message(content="分析产物：", elements=elements).send()
