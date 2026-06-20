import type { AssistantMessagePayload, PlanStep, StepRecord } from "../api/types";
import StepItem from "./StepItem";

interface PlanBlockProps {
  payload: AssistantMessagePayload;
}

function recordFor(step: PlanStep, records: StepRecord[]) {
  return records.find((record) => record.step_id === step.id);
}

export default function PlanBlock({ payload }: PlanBlockProps) {
  const steps = payload.plan?.steps ?? [];
  if (steps.length === 0) {
    return null;
  }
  const tools = new Set(steps.map((step) => step.tool)).size;
  return (
    <div className="plan">
      <h4>
        <span>执行计划</span>
        <span className="scope">
          {steps.length} 步 · {tools === 1 ? steps[0].tool : "mixed"}
        </span>
      </h4>
      {steps.map((step, index) => (
        <StepItem key={step.id} index={index} step={step} record={recordFor(step, payload.steps)} />
      ))}
    </div>
  );
}
