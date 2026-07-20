import type { PlanStep, StepRecord } from "../api/types";
import { stepTitle, toolLabel } from "./presentationLabels";

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
  const title = stepTitle(step);
  const description = step.instruction?.trim() === title ? "" : step.instruction?.trim();
  return (
    <div className={`step ${status}`}>
      <div className="marker">{String(index + 1).padStart(2, "0")}</div>
      <div className="body">
        <div className="label">{title}</div>
        {description ? <div className="desc">{description}</div> : null}
        <div className="tags">
          <span className={`tag ${step.tool}`}>{toolLabel(step.tool)}</span>
          {step.is_exploratory ? <span className="tag">探索分析</span> : null}
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
        {record?.artifact_ids.length ? <span>{record.artifact_ids.length} 个产物</span> : null}
      </div>
      {record && (record.stdout || record.error || record.script_path) ? (
        <details className="step-detail">
          <summary>技术详情</summary>
          <div className="technical-detail-content">
            {record.script_path ? (
              <div className="line">
                <span className="k">脚本</span>
                <span>{record.script_path}</span>
              </div>
            ) : null}
            {record.error ? (
              <div className="line">
                <span className="k">错误</span>
                <span>{record.error}</span>
              </div>
            ) : null}
            {record.stdout ? <div className="out">{record.stdout}</div> : null}
          </div>
        </details>
      ) : null}
    </div>
  );
}
