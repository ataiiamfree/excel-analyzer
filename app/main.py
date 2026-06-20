"""Chainlit chat interface for Excel analysis agent."""

from __future__ import annotations

import logging
import os
import sys
import mimetypes
from pathlib import Path
from typing import Optional

import pandas as pd

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
_log_file_error: OSError | None = None
try:
    _handlers.append(logging.FileHandler(_LOG_FILE, encoding="utf-8"))
except OSError as exc:
    _log_file_error = exc
logging.basicConfig(
    level=getattr(logging, _LOG_LEVEL, logging.INFO),
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%H:%M:%S",
    handlers=_handlers,
)
if _log_file_error is not None:
    logging.getLogger(__name__).warning("runtime.log 不可写，仅输出到终端: %s", _log_file_error)

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
TABLE_PREVIEW_EXTENSIONS = {".xlsx", ".xlsm", ".xls", ".csv", ".tsv"}
MAX_TABLE_PREVIEWS = 1
TABLE_PREVIEW_ROWS = 50
TABLE_PREVIEW_COLS = 24
MAX_REASONING_UI_CHARS = 12000
UPLOAD_HELP = (
    "把 Excel 文件拖到这里，或点击选择文件。支持 `.xlsx` / `.xlsm`，单个文件不超过 100MB。"
)


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


def _friendly_error(exc: Exception) -> str:
    """Turn an exception into a user-friendly message with actionable guidance."""
    msg = str(exc)
    # Network / DNS errors
    if any(kw in msg for kw in ("nodename nor servname", "Name or service not known",
                                 "Connection refused", "Connection reset",
                                 "RemoteDisconnected", "Connection timed out")):
        return "网络连接异常，请检查网络后重试。"
    # LLM timeout
    if "TimeoutError" in msg or "timed out" in msg.lower():
        return "分析超时了。可以尝试简化问题，或拆成几个小问题分别提问。"
    # LLM rate limit
    if "429" in msg or "rate limit" in msg.lower():
        return "请求太频繁，请等一会儿再试。"
    # LLM API errors
    if "LLMError" in type(exc).__name__ or "LLMError" in msg:
        return f"AI 服务暂时不可用，请稍后重试。（{msg[:100]}）"
    # File / data errors
    if any(kw in msg for kw in ("openpyxl", "InvalidFileException", "BadZipFile")):
        return "文件解析出错，请确认上传的是有效的 Excel 文件（.xlsx/.xlsm）。"
    # Generic fallback
    return f"分析过程出错：{msg[:200]}\n\n可以换个问法重试，或上传新文件重新开始。"


def _describe_file(path: str) -> str:
    """Generate a short description for a downloadable file."""
    p = Path(path)
    suffix = p.suffix.lower()
    name = p.stem
    if suffix in {".png", ".jpg", ".jpeg", ".svg"}:
        return f"图表: {name}"
    if suffix in {".csv", ".tsv"}:
        try:
            lines = p.read_text(encoding="utf-8-sig").strip().split("\n")
            row_count = max(0, len(lines) - 1)
            return f"{name}.csv（{row_count} 行）"
        except Exception:
            pass
        return f"{name}.csv"
    if suffix in {".xlsx", ".xlsm"}:
        return f"{name}.xlsx"
    return p.name


def _table_preview_for_path(path: str) -> pd.DataFrame | None:
    """Load a bounded table preview for inline UI rendering."""
    p = Path(path)
    suffix = p.suffix.lower()
    try:
        if suffix == ".csv":
            df = pd.read_csv(p, encoding="utf-8-sig", nrows=TABLE_PREVIEW_ROWS)
        elif suffix == ".tsv":
            df = pd.read_csv(p, sep="\t", encoding="utf-8-sig", nrows=TABLE_PREVIEW_ROWS)
        elif suffix in {".xlsx", ".xlsm", ".xls"}:
            df = pd.read_excel(p, sheet_name=0, nrows=TABLE_PREVIEW_ROWS)
        else:
            return None
    except Exception:
        logger.exception("表格预览读取失败: %s", path)
        return None

    if df.empty:
        return None
    if len(df.columns) > TABLE_PREVIEW_COLS:
        df = df.iloc[:, :TABLE_PREVIEW_COLS].copy()
    return df


async def _stream_text_message(text: str) -> cl.Message:
    """Stream already assembled text so short responses use the same UI path."""
    msg = cl.Message(content="")
    await msg.send()
    for chunk in _chunk_text_for_stream(text):
        await msg.stream_token(chunk)
    await msg.update()
    return msg


def _chunk_text_for_stream(text: str, chunk_size: int = 32) -> list[str]:
    return [text[index:index + chunk_size] for index in range(0, len(text), chunk_size)]


def _format_plan_for_ui(steps: list[Step]) -> str:
    if not steps:
        return "**执行计划**\n\n- 使用默认流程完成分析"
    lines = ["**执行计划**"]
    for index, step in enumerate(steps, start=1):
        label = step.description or step.instruction or "执行分析"
        lines.append(f"{index}. `{step.tool}` {label}")
    return "\n".join(lines)


def _format_step_result_for_ui(step: Step, result: StepResult) -> str:
    parts: list[str] = []
    if result.failed:
        parts.append("状态：失败")
        if result.error:
            parts.append("错误摘要：\n```text\n" + _truncate_text(result.error, 1200) + "\n```")
    else:
        parts.append("状态：完成")

    if result.stdout:
        parts.append("执行输出：\n```text\n" + _truncate_text(result.stdout, 1600) + "\n```")
    if result.files:
        files = "\n".join(f"- {path}" for path in result.files[:8])
        if len(result.files) > 8:
            files += f"\n- ... 另有 {len(result.files) - 8} 个文件"
        parts.append("产物：\n" + files)
    if result.script_path:
        parts.append(f"脚本：`{result.script_path}`")
    return "\n\n".join(parts) if parts else f"{step.description} 已完成。"


def _truncate_text(text: str, max_chars: int) -> str:
    clean = (text or "").strip()
    if len(clean) <= max_chars:
        return clean
    return clean[:max_chars].rstrip() + "\n..."


async def _setup_session(file_path: str, file_name: str):
    """Create a new session and orchestrator for the given file."""
    session = Session.create(file_path=file_path)
    cl.user_session.set("session", session)
    cl.user_session.set("orchestrator", build_orchestrator())
    cl.user_session.set("current_file", file_name)
    logger.info("新建 session: file=%s", file_name)


@cl.set_starter_categories
async def starter_categories(user: Optional[cl.User] = None):
    return [
        cl.StarterCategory(
            label="常用分析",
            starters=[
                cl.Starter(
                    label="汇总与排名",
                    message="按关键维度汇总数据，输出排名和可核对明细。",
                ),
                cl.Starter(
                    label="同比环比",
                    message="统计最新月份的本月、全年、同比和环比，并说明计算口径。",
                ),
                cl.Starter(
                    label="异常核查",
                    message="找出数据中的异常记录、缺失值和重复项。",
                ),
            ],
        ),
        cl.StarterCategory(
            label="输出格式",
            starters=[
                cl.Starter(
                    label="生成结果表",
                    message="处理数据并把结果、过程明细输出成新的 Excel 或 CSV 文件。",
                ),
                cl.Starter(
                    label="图表分析",
                    message="分析关键指标趋势和分布，输出图表和结论摘要。",
                ),
            ],
        ),
    ]


@cl.on_chat_start
async def start():
    """Ask the user to upload an Excel file and create a session."""
    files = await cl.AskFileMessage(
        content=(
            "# 开始一次 Excel 分析\n\n"
            f"{UPLOAD_HELP}\n\n"
            "上传后直接输入你的问题；也可以在任意时候发送新的 Excel 文件切换数据。"
        ),
        accept=["*/*"],
        max_size_mb=100,
    ).send()

    if not files:
        await cl.Message(content=f"未收到文件。{UPLOAD_HELP}").send()
        return

    uploaded = files[0]
    suffix = Path(uploaded.name).suffix.lower()
    if suffix not in EXCEL_EXTENSIONS:
        await cl.Message(content="目前请上传 `.xlsx` 或 `.xlsm` 文件。").send()
        return

    await _setup_session(uploaded.path, uploaded.name)
    await cl.Message(
        content=(
            f"已上传 **{uploaded.name}**。\n\n"
            "现在告诉我你想怎么处理这份表：可以要求汇总、筛选、同比环比、画图、导出新表，"
            "也可以要求把计算过程一并输出用于核对。"
        )
    ).send()


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
            await cl.Message(
                content=(
                    f"已切换到 **{current_file}**。\n\n"
                    "请输入新的分析需求；如果是复杂口径，可以直接逐条写规则。"
                )
            ).send()
            return
        # 有文件也有问题文本，继续往下走分析流程

    session: Session | None = cl.user_session.get("session")
    if session is None:
        await cl.Message(content=f"请先上传 Excel 文件。{UPLOAD_HELP}").send()
        return

    orchestrator = cl.user_session.get("orchestrator")
    current_file = cl.user_session.get("current_file") or "Excel"
    report_msg: cl.Message | None = None
    reasoning_msg: cl.Message | None = None
    reasoning_chars = 0
    reasoning_truncated = False
    active_steps: dict[str, cl.Step] = {}

    async def on_report_token(token: str):
        nonlocal report_msg
        if not token:
            return
        if report_msg is None:
            report_msg = cl.Message(content="")
            await report_msg.send()
        await report_msg.stream_token(token)

    async def on_reasoning_token(token: str):
        nonlocal reasoning_msg, reasoning_chars, reasoning_truncated
        if not token or reasoning_truncated:
            return
        if reasoning_msg is None:
            reasoning_msg = cl.Message(content="**DeepSeek 思考**\n\n")
            await reasoning_msg.send()

        remaining = MAX_REASONING_UI_CHARS - reasoning_chars
        if remaining <= 0:
            await reasoning_msg.stream_token("\n\n（思考内容较长，后续已省略。）")
            reasoning_truncated = True
            return

        chunk = token[:remaining]
        reasoning_chars += len(chunk)
        await reasoning_msg.stream_token(chunk)
        if len(token) > remaining:
            await reasoning_msg.stream_token("\n\n（思考内容较长，后续已省略。）")
            reasoning_truncated = True

    reporter = getattr(orchestrator, "reporter", None)
    if reporter is not None:
        reporter.stream_callback = on_report_token
    llm = getattr(orchestrator, "llm", None)
    if llm is not None:
        llm.reasoning_callback = on_reasoning_token

    # Progress callbacks — update a single status message in place
    progress_msg = cl.Message(content=f"正在分析 **{current_file}**...")
    await progress_msg.send()

    async def on_plan_ready(plan):
        await cl.Message(content=_format_plan_for_ui(plan.steps)).send()

    async def on_step_start(step: Step, step_index: int = 0, total_steps: int = 0):
        if total_steps > 1:
            progress_msg.content = f"正在分析 **{current_file}**... `[{step_index}/{total_steps}]` {step.description}"
        else:
            progress_msg.content = f"正在分析 **{current_file}**... {step.description}"
        await progress_msg.update()
        step_title = f"[{step_index}/{total_steps}] {step.description}" if total_steps > 0 else step.description
        cl_step = cl.Step(name=step_title or step.id)
        cl_step.input = step.instruction or step.description
        await cl_step.__aenter__()
        active_steps[step.id] = cl_step

    async def on_step_end(step: Step, result: StepResult):
        cl_step = active_steps.pop(step.id, None)
        if cl_step is None:
            await cl.Message(content=_format_step_result_for_ui(step, result)).send()
            return
        cl_step.output = _format_step_result_for_ui(step, result)
        await cl_step.__aexit__(None, None, None)

    try:
        task_result = await orchestrator.run(
            query=message.content,
            session=session,
            on_step_start=on_step_start,
            on_step_end=on_step_end,
            on_plan_ready=on_plan_ready,
        )
    except Exception as e:
        logger.exception("分析过程出错")
        await cl.Message(content=_friendly_error(e)).send()
        return
    finally:
        if reporter is not None:
            reporter.stream_callback = None
        if llm is not None:
            llm.reasoning_callback = None
        if reasoning_msg is not None:
            await reasoning_msg.update()
        for cl_step in active_steps.values():
            cl_step.output = "任务中断，未收到步骤完成回调。"
            await cl_step.__aexit__(None, None, None)
        active_steps.clear()

    # Handle task failure with actionable message
    if task_result.failed:
        fail_msg = f"在「{task_result.failed_step_description}」这一步出错了"
        if task_result.error_summary:
            # Show a short, readable error hint
            hint = task_result.error_summary.split("\n")[0][:120]
            fail_msg += f"：{hint}"
        fail_msg += "\n\n可以换个说法重试，或简化问题拆成几步。"
        await cl.Message(content=fail_msg).send()
        return

    # Send report
    report_text = _report_for_ui(task_result.report)

    # Collect downloadable elements and keep table previews in separate messages.
    # Dataframe elements become cramped when grouped with file cards.
    elements: list[cl.Element] = []
    table_previews: list[tuple[str, cl.Element]] = []
    file_descriptions: list[str] = []
    table_preview_count = 0
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
            file_descriptions.append(f"- {_describe_file(full_path)}")
        else:
            if suffix in TABLE_PREVIEW_EXTENSIONS and table_preview_count < MAX_TABLE_PREVIEWS:
                preview = _table_preview_for_path(full_path)
                if preview is not None:
                    table_previews.append(
                        (
                            f"**结果表预览：** {name}（前 {len(preview)} 行）",
                            cl.Dataframe(
                                name=f"预览：{name}",
                                data=preview,
                                display="inline",
                            ),
                        )
                    )
                    table_preview_count += 1
            elements.append(cl.File(path=full_path, name=name, mime=_mime_for_path(full_path)))
            file_descriptions.append(f"- {_describe_file(full_path)}")

    # Finalize streamed report, then send files separately to avoid disrupting token flow.
    if report_msg is not None:
        await report_msg.update()
    elif report_text:
        await _stream_text_message(report_text)

    if elements:
        file_list = "\n".join(file_descriptions)
        heading = "**可下载的文件：**" if report_text else "**分析完成，可下载的文件：**"
        await cl.Message(content=f"{heading}\n{file_list}", elements=elements).send()

    for title, preview_element in table_previews:
        await cl.Message(content=title, elements=[preview_element]).send()
