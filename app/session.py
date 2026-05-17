"""Session management for multi-turn analysis conversations.

A Session tracks one uploaded file across multiple analysis queries (follow-ups).
It caches preprocessing results so follow-up questions skip the expensive
Ingestor → Preprocessor → Profiler pipeline.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from typing import Any


@dataclass
class Session:
    session_id: str
    file_path: str
    tasks: list[str] = field(default_factory=list)
    conversation_summary: str = ""
    accumulated_findings: list[str] = field(default_factory=list)

    # Cached from first analysis — reused on follow-ups
    workbook_manifest: dict[str, Any] | None = None
    profile: dict[str, Any] | None = None
    normalized_dir: str | None = None

    _SUMMARY_MAX_CHARS: int = field(default=2000, repr=False)

    @classmethod
    def create(cls, file_path: str) -> Session:
        return cls(session_id=uuid.uuid4().hex, file_path=file_path)

    @property
    def is_follow_up(self) -> bool:
        """True if at least one analysis has been completed."""
        return len(self.tasks) > 0

    def cache_preprocessing(
        self,
        workbook_manifest: dict[str, Any],
        profile: dict[str, Any],
        normalized_dir: str,
    ) -> None:
        """Save preprocessing results so follow-ups skip re-processing."""
        self.workbook_manifest = workbook_manifest
        self.profile = profile
        self.normalized_dir = normalized_dir

    def build_follow_up_context(self) -> dict[str, Any]:
        """Return context dict for follow-up queries (prior findings + summary)."""
        return {
            "prior_findings": list(self.accumulated_findings),
            "conversation_summary": self.conversation_summary,
            "prior_tasks": list(self.tasks),
        }

    def update_after_task(
        self,
        task_id: str,
        findings: list[str] | None = None,
        summary_text: str = "",
    ) -> None:
        """Update session state after a completed analysis task."""
        self.tasks.append(task_id)
        if findings:
            self.accumulated_findings.extend(findings)

        if summary_text:
            if self.conversation_summary:
                self.conversation_summary += "\n---\n" + summary_text
            else:
                self.conversation_summary = summary_text

        # Trim summary to keep context bounded
        if len(self.conversation_summary) > self._SUMMARY_MAX_CHARS:
            self.conversation_summary = self.conversation_summary[
                -self._SUMMARY_MAX_CHARS :
            ]
