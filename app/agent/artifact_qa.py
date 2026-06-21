"""Deterministic artifact question answering helpers."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any


class ArtifactNotFoundError(RuntimeError):
    """Raised when a user asks about an artifact that cannot be resolved."""


class ArtifactExplainer:
    def resolve_by_name(self, query: str, artifacts: list[dict[str, Any]]) -> dict[str, Any]:
        if not artifacts:
            raise ArtifactNotFoundError("当前会话还没有可解释的产物。")

        normalized = (query or "").lower()
        scored: list[tuple[int, dict[str, Any]]] = []
        for artifact in artifacts:
            path = str(artifact.get("path") or artifact.get("name") or "")
            name = str(artifact.get("name") or Path(path).name)
            lower_name = name.lower()
            lower_path = path.lower()
            score = 0
            if lower_name and lower_name in normalized:
                score += 100
            if lower_path and lower_path in normalized:
                score += 80
            stem = Path(lower_name).stem
            if stem and stem in normalized:
                score += 50
            for token in re.split(r"[_\-.]+", stem):
                if len(token) >= 3 and token in normalized:
                    score += 5
            if score:
                scored.append((score, artifact))

        if scored:
            return sorted(scored, key=lambda item: item[0], reverse=True)[0][1]
        if len(artifacts) == 1:
            return artifacts[0]
        latest = sorted(artifacts, key=lambda item: str(item.get("created_at", "")), reverse=True)[0]
        return latest

    def inspect(self, workspace: Any, artifact: dict[str, Any]) -> dict[str, Any]:
        rel_path = artifact.get("path") or artifact.get("name") or ""
        path = Path(rel_path)
        if not path.is_absolute():
            path = Path(workspace.path) / str(rel_path)

        script_text = ""
        script_path = artifact.get("script_path")
        if script_path:
            try:
                script_text = workspace.read_text(script_path)
            except Exception:
                script_text = ""

        return {
            "artifact": artifact,
            "path": str(path),
            "exists": path.exists(),
            "size": path.stat().st_size if path.exists() and path.is_file() else None,
            "script_text": script_text,
            "script_hints": self._script_hints(script_text, str(rel_path)),
        }

    def explain(self, query: str, workspace: Any, artifacts: list[dict[str, Any]]) -> str:
        artifact = self.resolve_by_name(query, artifacts)
        info = self.inspect(workspace, artifact)
        return self._format_explanation(query, info)

    def _format_explanation(self, query: str, info: dict[str, Any]) -> str:
        artifact = info["artifact"]
        name = artifact.get("name") or Path(str(artifact.get("path") or "")).name
        kind = artifact.get("kind") or "file"
        producer = artifact.get("producer_step_id") or artifact.get("producer_step") or "未知步骤"
        producer_tool = artifact.get("producer_tool") or "未知工具"
        source_tables = artifact.get("source_tables") or []
        stdout_summary = artifact.get("stdout_summary") or ""
        chart_metadata = artifact.get("chart_metadata") or {}
        script_hints = info.get("script_hints") or {}

        lines = [f"# 产物解释：{name}", ""]
        lines.append(f"这是一个 `{kind}` 类型产物，由 `{producer}` 步骤通过 `{producer_tool}` 生成。")
        if source_tables:
            lines.append("数据来源：" + "、".join(map(str, source_tables)) + "。")

        if kind in {"chart", "image", "figure"} or str(name).lower().endswith((".png", ".jpg", ".jpeg", ".svg")):
            lines.append("")
            lines.append("## 图表含义")
            title = chart_metadata.get("title") or script_hints.get("title")
            x_axis = chart_metadata.get("x_axis") or script_hints.get("xlabel")
            y_axis = chart_metadata.get("y_axis") or script_hints.get("ylabel")
            series = chart_metadata.get("series") or script_hints.get("labels") or []
            if title:
                lines.append(f"- 标题/主题：{title}")
            if x_axis:
                lines.append(f"- 横轴：{x_axis}")
            if y_axis:
                y_text = "、".join(map(str, y_axis)) if isinstance(y_axis, list) else str(y_axis)
                lines.append(f"- 纵轴：{y_text}")
            if series:
                lines.append("- 图例/序列：" + "、".join(map(str, series)))
            if not any([title, x_axis, y_axis, series]):
                lines.append("- 该图片的结构化图表元数据不足，以下解释主要依据生成步骤摘要和产物血缘。")

        if stdout_summary:
            lines.append("")
            lines.append("## 生成时的关键摘要")
            lines.append(stdout_summary.strip())

        if artifact.get("description"):
            lines.append("")
            lines.append("## 产物描述")
            lines.append(str(artifact["description"]))

        if not info.get("exists"):
            lines.append("")
            lines.append("注意：当前 workspace 中未找到该产物文件，以上解释基于 manifest 和历史执行记录。")

        lines.append("")
        lines.append("## 可以从中得到什么")
        if kind in {"chart", "image", "figure"}:
            lines.append("这类图主要用于快速观察趋势、异常点、分组差异或指标变化。具体结论应以生成该图时的 stdout 摘要和源数据口径为准。")
        else:
            lines.append("这个产物主要承载上一步分析结果，可继续用于筛选、复核、下载或生成报告。")

        return "\n".join(lines).strip()

    def _script_hints(self, script_text: str, rel_path: str) -> dict[str, Any]:
        if not script_text:
            return {}
        hints: dict[str, Any] = {}
        patterns = {
            "title": r"\.title\((['\"])(.*?)\1",
            "xlabel": r"\.xlabel\((['\"])(.*?)\1",
            "ylabel": r"\.ylabel\((['\"])(.*?)\1",
        }
        for key, pattern in patterns.items():
            match = re.search(pattern, script_text)
            if match:
                hints[key] = match.group(2)
        labels = re.findall(r"label\s*=\s*(['\"])(.*?)\1", script_text)
        if labels:
            hints["labels"] = [item[1] for item in labels[:8]]
        savefig = re.search(r"savefig\((['\"])(.*?)\1", script_text)
        if savefig and not rel_path:
            hints["saved_as"] = savefig.group(2)
        return hints
