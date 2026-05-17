"""Cross-session memory — schema fingerprinting and session history.

Stores user_memory.json with known schemas (column fingerprints) and recent
session records so the Profiler and Planner can leverage past experience.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


_DEFAULT_PATH = Path("memory/user_memory.json")
_MAX_HISTORY = 50


class Memory:
    def __init__(self, path: str | Path = _DEFAULT_PATH):
        self.path = Path(path)
        self._data: dict[str, Any] = self._load()

    # ------------------------------------------------------------------
    # Schema matching
    # ------------------------------------------------------------------

    def match_schema(self, columns: list[str]) -> dict[str, Any] | None:
        """Find a known schema whose columns overlap significantly."""
        fingerprint = set(columns)
        best: dict[str, Any] | None = None
        best_score = 0.0
        for schema in self._data.get("schemas", []):
            known = set(schema.get("columns", []))
            if not known:
                continue
            overlap = len(fingerprint & known)
            union = len(fingerprint | known)
            score = overlap / union if union else 0.0
            if score > best_score and score >= 0.5:
                best_score = score
                best = schema
        return best

    def save_schema(
        self,
        columns: list[str],
        *,
        label: str = "",
        common_dimensions: list[str] | None = None,
        time_columns: list[str] | None = None,
        amount_columns: list[str] | None = None,
    ) -> None:
        """Save a new schema fingerprint (or update existing if overlap ≥ 0.8)."""
        schemas = self._data.setdefault("schemas", [])
        fingerprint = set(columns)

        # Check for existing high-overlap schema to update
        for schema in schemas:
            known = set(schema.get("columns", []))
            union = len(fingerprint | known)
            overlap = len(fingerprint & known) / union if union else 0.0
            if overlap >= 0.8:
                schema["columns"] = columns
                if label:
                    schema["label"] = label
                if common_dimensions:
                    schema["common_dimensions"] = common_dimensions
                if time_columns:
                    schema["time_columns"] = time_columns
                if amount_columns:
                    schema["amount_columns"] = amount_columns
                schema["updated_at"] = datetime.now(timezone.utc).isoformat()
                self._save()
                return

        schemas.append({
            "columns": columns,
            "label": label,
            "common_dimensions": common_dimensions or [],
            "time_columns": time_columns or [],
            "amount_columns": amount_columns or [],
            "created_at": datetime.now(timezone.utc).isoformat(),
        })
        self._save()

    # ------------------------------------------------------------------
    # Session history
    # ------------------------------------------------------------------

    def add_session_record(
        self,
        session_id: str,
        file_name: str,
        queries: list[str],
        findings: list[str] | None = None,
    ) -> None:
        """Append a session record, keeping at most _MAX_HISTORY entries."""
        history = self._data.setdefault("history", [])
        history.append({
            "session_id": session_id,
            "file_name": file_name,
            "queries": queries,
            "findings": findings or [],
            "timestamp": datetime.now(timezone.utc).isoformat(),
        })
        if len(history) > _MAX_HISTORY:
            self._data["history"] = history[-_MAX_HISTORY:]
        self._save()

    def recent_sessions(self, n: int = 10) -> list[dict[str, Any]]:
        return list(self._data.get("history", [])[-n:])

    # ------------------------------------------------------------------
    # Persistence
    # ------------------------------------------------------------------

    def _load(self) -> dict[str, Any]:
        if self.path.exists():
            try:
                return json.loads(self.path.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, ValueError):
                return {}
        return {}

    def _save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(
            json.dumps(self._data, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
