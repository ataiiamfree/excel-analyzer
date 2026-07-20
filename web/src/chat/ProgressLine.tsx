import type { AssistantMessagePayload } from "../api/types";
import { stepTitle } from "./presentationLabels";

interface ProgressLineProps {
  payload: AssistantMessagePayload;
}

export default function ProgressLine({ payload }: ProgressLineProps) {
  const running = payload.steps.find((step) => step.status === "running");
  const runningPlanStep = payload.plan.steps.find((step) => step.id === running?.step_id);
  const total = payload.plan.steps.length;
  const done = payload.steps.filter((step) => step.status === "done").length;

  return (
    <div className="progress-line">
      <span className="spin" />
      <span>
        正在执行 <strong>{stepTitle(runningPlanStep)}</strong>
        <span className="progress-count">进度 {Math.min(done + 1, total || 1)}/{total || 1}</span>
      </span>
    </div>
  );
}
