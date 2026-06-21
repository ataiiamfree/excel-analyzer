"""Shared agent execution result types."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class StepResult:
    stdout: str
    files: list[str]
    failed: bool = False
    error: str = ""
    retries_exhausted: bool = False
    script_path: str | None = None

    @property
    def success(self) -> bool:
        return not self.failed

    @property
    def stderr(self) -> str:
        return self.error

    @property
    def output_files(self) -> list[str]:
        return self.files


@dataclass
class TaskResult:
    report: str
    files: list[str]
    failed: bool = False
    failed_step_description: str = ""
    error_summary: str = ""
