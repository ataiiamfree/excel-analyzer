"""Generate concise follow-up actions from an analysis result."""

from __future__ import annotations

import json
import logging
import re
from typing import Any

logger = logging.getLogger(__name__)

MAX_ACTIONS = 3
MAX_ACTION_CHARS = 48
MAX_REPORT_CHARS = 3000
MAX_STEP_CHARS = 1200


def _clip(text: str, limit: int) -> str:
    stripped = (text or "").strip()
    if len(stripped) <= limit:
        return stripped
    return stripped[:limit].rstrip() + "..."


def _extract_json_text(text: str) -> str:
    stripped = (text or "").strip()
    fence = re.search(r"```(?:json)?\s*(.*?)```", stripped, flags=re.DOTALL | re.IGNORECASE)
    if fence:
        return fence.group(1).strip()
    start = stripped.find("{")
    end = stripped.rfind("}")
    if start >= 0 and end > start:
        return stripped[start : end + 1]
    return stripped


def parse_next_actions_response(text: str) -> list[str]:
    """Parse and normalize the LLM JSON response."""
    if not text.strip():
        return []

    try:
        data = json.loads(_extract_json_text(text))
    except ValueError:
        logger.warning("next action response is not JSON: %s", text[:200])
        return []

    if isinstance(data, dict):
        raw_actions = data.get("actions", [])
    elif isinstance(data, list):
        raw_actions = data
    else:
        raw_actions = []
    if not isinstance(raw_actions, list):
        return []

    actions: list[str] = []
    seen: set[str] = set()
    for raw in raw_actions:
        if not isinstance(raw, str):
            continue
        action = re.sub(r"^\s*[-*0-9一二三四五六七八九十]+[.、)\s]+", "", raw).strip()
        action = re.sub(r"\s+", " ", action)
        if not action:
            continue
        action = action[:MAX_ACTION_CHARS].rstrip()
        key = action.lower()
        if key in seen:
            continue
        seen.add(key)
        actions.append(action)
        if len(actions) >= MAX_ACTIONS:
            break
    return actions


def build_next_actions_prompt(
    *,
    query: str,
    report: str,
    steps: list[dict[str, Any]],
    artifacts: list[dict[str, Any]],
) -> str:
    context = {
        "user_query": _clip(query, 600),
        "report_excerpt": _clip(report, MAX_REPORT_CHARS),
        "steps": [
            {
                "step_id": step.get("step_id"),
                "status": step.get("status"),
                "stdout": _clip(str(step.get("stdout") or ""), MAX_STEP_CHARS),
                "error": _clip(str(step.get("error") or ""), 500),
            }
            for step in steps[-4:]
        ],
        "artifacts": [
            {
                "name": item.get("name"),
                "kind": item.get("kind"),
            }
            for item in artifacts
        ],
    }
    return (
        "你是 ChatExcel 的下一步行动建议器。请只基于下面的分析摘要、步骤反馈和产物清单，"
        "给用户 2-3 条可直接继续追问的短建议。\n"
        "要求：\n"
        "- 每条建议必须是用户可以直接发送的分析请求。\n"
        "- 不要建议重新上传文件、查看原始数据或泛泛地说“进一步分析”。\n"
        "- 优先围绕当前结果的可解释性、细分维度、异常归因、导出明细或图表补充。\n"
        "- 不要编造摘要里没有依据的字段名；可以使用“按可用维度”这类保守说法。\n"
        "- 只输出 JSON，格式为 {\"actions\":[\"...\",\"...\"]}。\n\n"
        f"上下文：\n{json.dumps(context, ensure_ascii=False)}"
    )


async def generate_next_actions(
    *,
    llm_client: Any,
    query: str,
    report: str,
    steps: list[dict[str, Any]],
    artifacts: list[dict[str, Any]],
) -> list[str]:
    """Call the LLM for dynamic follow-up actions.

    This is best-effort: suggestion failures must not fail the completed analysis.
    """
    if llm_client is None or not report.strip():
        return []

    prompt = build_next_actions_prompt(query=query, report=report, steps=steps, artifacts=artifacts)
    try:
        response = await llm_client.call(
            prompt,
            max_tokens=500,
            temperature=0.2,
            thinking=False,
        )
    except Exception as exc:  # noqa: BLE001 - suggestions are non-critical.
        logger.warning("next action generation failed: %s", exc)
        return []
    return parse_next_actions_response(response)
