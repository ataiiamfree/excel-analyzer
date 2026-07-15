import type { PlanStep, StepRecord } from "../api/types";

interface StepItemProps {
  index: number;
  step: PlanStep;
  record?: StepRecord;
}

function statusClass(record?: StepRecord) {
  return record?.status ?? "pending";
}

function duration(record?: StepRecord) {
  if (!record?.started_at) return "";
  const start = new Date(record.started_at).getTime();
  const end = record.ended_at ? new Date(record.ended_at).getTime() : Date.now();
  return `${Math.max(0.1, (end - start) / 1000).toFixed(1)}s`;
}

export default function StepItem({ index, step, record }: StepItemProps) {
  const status = statusClass(record);
  return (
    <div className={`step ${status}`}>
      <div className="marker">{String(index + 1).padStart(2, "0")}</div>
      <div className="body">
        <div className="label">{step.description || step.instruction || "执行分析"}</div>
        <div className="desc">{step.instruction || step.description}</div>
        <div className="tags">
          <span className={`tag ${step.tool}`}>{step.tool}</span>
          {step.is_exploratory ? <span className="tag">explore</span> : null}
        </div>
      </div>
      <div className="timing">
        {status === "running" ? (
          <span className="pulse">执行中</span>
        ) : status === "cancelled" ? (
          <span>已取消</span>
        ) : (
          <span>{duration(record)}</span>
        )}
        {record?.artifact_ids.length ? <span>{record.artifact_ids.length} artifacts</span> : null}
      </div>
      {record && (record.stdout || record.error || record.script_path) ? (
        <div className="step-detail">
          {record.script_path ? (
            <div className="line">
              <span className="k">script</span>
              <span>{record.script_path}</span>
            </div>
          ) : null}
          {record.error ? (
            <div className="line">
              <span className="k">error</span>
              <span>{record.error}</span>
            </div>
          ) : null}
          {record.stdout ? <div className="out">{record.stdout}</div> : null}
        </div>
      ) : null}
    </div>
  );
}
