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
logging.basicConfig(
    level=getattr(logging, _LOG_LEVEL, logging.INFO),
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%H:%M:%S",
)

import chainlit as cl

from app.agent.orchestrator import build_orchestrator, StepResult
from app.agent.plan import Step
from app.session import Session


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


@cl.on_chat_start
async def start():
    """Ask the user to upload an Excel file and create a session."""
    files = await cl.AskFileMessage(
        content="请上传 Excel 文件（.xlsx/.xlsm），然后输入你的分析需求。",
        # Browser/office apps often report xlsx as application/octet-stream or
        # application/zip. Accept broadly here, then validate by extension below.
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

    session = Session.create(file_path=uploaded.path)
    cl.user_session.set("session", session)
    cl.user_session.set("orchestrator", build_orchestrator())

    await cl.Message(content=f"已上传 **{uploaded.name}**，请输入你的分析需求。").send()


@cl.on_message
async def main(message: cl.Message):
    """Handle user analysis queries and follow-ups."""
    session: Session | None = cl.user_session.get("session")
    if session is None:
        await cl.Message(content="请先上传 Excel 文件。").send()
        return

    orchestrator = cl.user_session.get("orchestrator")

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
    try:
        task_result = await orchestrator.run(
            query=message.content,
            session=session,
            on_step_start=on_step_start,
            on_step_end=on_step_end,
        )
    except Exception as e:
        await cl.Message(content=f"分析过程出错：{e}").send()
        return

    # Send report
    await cl.Message(content=_report_for_ui(task_result.report)).send()

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
