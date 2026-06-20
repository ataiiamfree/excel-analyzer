import type { AssistantMessagePayload } from "../api/types";

interface ProgressLineProps {
  payload: AssistantMessagePayload;
}

export default function ProgressLine({ payload }: ProgressLineProps) {
  const running = payload.steps.find((step) => step.status === "running");
  const total = payload.plan.steps.length;
  const done = payload.steps.filter((step) => step.status === "done").length;

  return (
    <div className="progress-line">
      <span className="spin" />
      <span>
        正在生成 <strong>{running?.step_id ?? "分析结果"}</strong>... step {Math.min(done + 1, total || 1)}/
        {total || 1}
      </span>
    </div>
  );
}
