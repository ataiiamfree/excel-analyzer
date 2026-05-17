"""Execution plan primitives.

The scheduler deliberately avoids iterating over ``plan.steps`` directly
because Adapt can insert, skip, or edit future steps while the task is running.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


TERMINAL_STATUSES = {"done", "failed", "skipped"}


@dataclass
class Step:
    id: str
    tool: str
    description: str
    instruction: str
    depends_on: list[str] = field(default_factory=list)
    is_exploratory: bool = False
    expected_outputs: list[dict[str, Any]] = field(default_factory=list)
    status: str = "pending"
    check_status: str | None = None
    error: str | None = None


@dataclass
class PlanAdjustment:
    next_step_adjusted: str | None = None
    insert_steps: list[Step] = field(default_factory=list)
    skip_steps: list[str] = field(default_factory=list)
    reasoning: str = ""


@dataclass
class ExecutionPlan:
    steps: list[Step]
    report_outline: list[dict[str, Any]] = field(default_factory=list)

    @property
    def requires_report(self) -> bool:
        return bool(self.report_outline)

    def get_step(self, step_id: str) -> Step | None:
        return next((step for step in self.steps if step.id == step_id), None)

    def next_runnable_step(self) -> Step | None:
        completed = {
            step.id
            for step in self.steps
            if step.status in {"done", "skipped"}
        }
        for step in self.steps:
            if step.status != "pending":
                continue
            if all(dep in completed for dep in step.depends_on):
                return step
        return None

    def remaining_steps(self) -> list[Step]:
        return [step for step in self.steps if step.status not in TERMINAL_STATUSES]

    def remaining_steps_overview(self) -> str:
        lines = []
        for step in self.remaining_steps():
            deps = f" depends_on={step.depends_on}" if step.depends_on else ""
            lines.append(f"- {step.id}: {step.description}{deps}")
        return "\n".join(lines)

    def mark_running(self, step_id: str) -> None:
        step = self._require_step(step_id)
        step.status = "running"

    def mark_done(self, step_id: str, check: str = "passed") -> None:
        step = self._require_step(step_id)
        step.status = "done"
        step.check_status = check
        step.error = None

    def mark_failed(self, step_id: str, error: str, check: str | None = None) -> None:
        step = self._require_step(step_id)
        step.status = "failed"
        step.error = error
        step.check_status = check

    def adjust_step(self, step_id: str, new_instruction: str) -> None:
        step = self._require_step(step_id)
        step.instruction = new_instruction

    def insert_after(self, after_id: str, new_step: Step) -> None:
        for index, step in enumerate(self.steps):
            if step.id == after_id:
                self.steps.insert(index + 1, new_step)
                return
        raise KeyError(f"Unknown step id: {after_id}")

    def skip_step(self, step_id: str) -> None:
        step = self._require_step(step_id)
        if step.status not in TERMINAL_STATUSES:
            step.status = "skipped"

    def apply_adjustment(self, adjustment: PlanAdjustment, current_step_id: str) -> None:
        next_step = self.next_runnable_step()
        if next_step and adjustment.next_step_adjusted:
            next_step.instruction = adjustment.next_step_adjusted
            next_step.description = adjustment.next_step_adjusted
        for new_step in adjustment.insert_steps:
            self.insert_after(current_step_id, new_step)
            current_step_id = new_step.id
        for step_id in adjustment.skip_steps:
            self.skip_step(step_id)

    def to_dict(self) -> dict[str, Any]:
        return {
            "steps": [step.__dict__ for step in self.steps],
            "report_outline": self.report_outline,
        }

    def _require_step(self, step_id: str) -> Step:
        step = self.get_step(step_id)
        if step is None:
            raise KeyError(f"Unknown step id: {step_id}")
        return step
