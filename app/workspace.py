"""Local task workspace management."""

from __future__ import annotations

import json
import shutil
import uuid
from dataclasses import asdict, is_dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


class Workspace:
    def __init__(self, root: str | Path = "workspace", task_id: str | None = None):
        self.root = Path(root)
        self.task_id = task_id or uuid.uuid4().hex
        self.path = self.root / self.task_id
        for dirname in ("raw", "normalized", "output", "scripts", "logs"):
            (self.path / dirname).mkdir(parents=True, exist_ok=True)
        self._ensure_json("artifact_manifest.json", [])
        # 仅在 state.json 不存在时初始化，避免覆写已有任务状态（支持恢复）
        if not (self.path / "state.json").exists():
            self.write_state(
                status="pending",
                current_step=None,
                started_at=datetime.now(timezone.utc).isoformat(),
                retry_count=0,
            )

    @classmethod
    def create(cls, root: str | Path = "workspace") -> "Workspace":
        return cls(root=root)

    def save_upload(self, source_path: str | Path) -> str:
        source = Path(source_path)
        target = self.path / "raw" / source.name
        if source.resolve() != target.resolve():
            shutil.copy2(source, target)
        return str(target)

    def save_json(self, name: str, value: Any) -> None:
        target = self.path / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(
            json.dumps(self._jsonable(value), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    def read_json(self, name: str, default: Any = None) -> Any:
        target = self.path / name
        if not target.exists():
            return default
        return json.loads(target.read_text(encoding="utf-8"))

    def write_state(self, status: str, current_step: str | None = None, **extra: Any) -> None:
        state = self.read_json("state.json", {}) or {}
        state.update(
            {
                "task_id": self.task_id,
                "status": status,
                "current_step": current_step,
                "updated_at": datetime.now(timezone.utc).isoformat(),
                **extra,
            }
        )
        self.save_json("state.json", state)

    def request_cancel(self) -> None:
        state = self.read_json("state.json", {}) or {}
        state["cancel_requested"] = True
        self.save_json("state.json", state)

    def is_cancel_requested(self) -> bool:
        state = self.read_json("state.json", {}) or {}
        return bool(state.get("cancel_requested"))

    def save_artifacts(self, tables: list[Any]) -> None:
        manifest = self.read_artifact_manifest()
        for table in tables:
            manifest.append(
                {
                    "path": getattr(table, "parquet_path", ""),
                    "kind": "normalized_table",
                    "description": getattr(table, "table_id", ""),
                    "producer_step": "preprocess",
                    "inputs": [getattr(table, "source_file", "")],
                    "schema": getattr(table, "columns", []),
                    "row_count": getattr(table, "row_count", None),
                    "created_at": datetime.now(timezone.utc).isoformat(),
                }
            )
        self.save_json("artifact_manifest.json", manifest)

    def register_artifact(
        self,
        path: str,
        kind: str,
        producer_step: str,
        description: str = "",
        inputs: list[str] | None = None,
    ) -> None:
        """注册单个产物（图表、导出文件等）到 artifact manifest。"""
        manifest = self.read_artifact_manifest()
        manifest.append({
            "path": path,
            "kind": kind,
            "description": description,
            "producer_step": producer_step,
            "inputs": inputs or [],
            "created_at": datetime.now(timezone.utc).isoformat(),
        })
        self.save_json("artifact_manifest.json", manifest)

    def read_artifact_manifest(self) -> list[dict[str, Any]]:
        return self.read_json("artifact_manifest.json", []) or []

    def list_files(self) -> list[dict[str, Any]]:
        files = []
        for item in self.read_artifact_manifest():
            path = item.get("path")
            if path:
                files.append({"name": path, **item})
        return files

    def list_output_files(self) -> list[str]:
        output = self.path / "output"
        return [str(path.relative_to(self.path)) for path in output.glob("*") if path.is_file()]

    def record_code(self, step_id: str, script_path: str | None, attempt: int) -> None:
        history = self.read_json("code_history.json", []) or []
        history.append({"step_id": step_id, "script_path": script_path, "attempt": attempt})
        self.save_json("code_history.json", history)

    def read_text(self, path: str | Path | None) -> str:
        if not path:
            return ""
        target = Path(path)
        if not target.is_absolute():
            target = self.path / target
        return target.read_text(encoding="utf-8") if target.exists() else ""

    def _ensure_json(self, name: str, default: Any) -> None:
        target = self.path / name
        if not target.exists():
            self.save_json(name, default)

    def cleanup(self, keep_recent: int = 5) -> list[str]:
        """清理过期任务目录，保留最近 N 个任务。返回被删除的 task_id 列表。"""
        if not self.root.exists():
            return []
        task_dirs = sorted(
            [d for d in self.root.iterdir() if d.is_dir()],
            key=lambda d: d.stat().st_mtime,
            reverse=True,
        )
        removed = []
        for task_dir in task_dirs[keep_recent:]:
            shutil.rmtree(task_dir, ignore_errors=True)
            removed.append(task_dir.name)
        return removed

    def _jsonable(self, value: Any) -> Any:
        if is_dataclass(value):
            return asdict(value)
        if isinstance(value, Path):
            return str(value)
        if isinstance(value, list):
            return [self._jsonable(item) for item in value]
        if isinstance(value, dict):
            return {key: self._jsonable(item) for key, item in value.items()}
        return value
