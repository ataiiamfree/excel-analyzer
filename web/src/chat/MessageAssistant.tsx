import { Copy, FileDown, RotateCcw, Star } from "lucide-react";

import type { Artifact, AssistantMessagePayload } from "../api/types";
import ArtifactChips from "./ArtifactChips";
import PlanBlock from "./PlanBlock";
import ProgressLine from "./ProgressLine";
import ReasoningCapsule from "./ReasoningCapsule";
import ReportArticle from "./ReportArticle";

interface MessageAssistantProps {
  payload: AssistantMessagePayload;
  artifacts: Artifact[];
  createdAt?: string;
  live?: boolean;
}

function timeLabel(payload: AssistantMessagePayload, createdAt?: string, live?: boolean) {
  if (live || payload.status === "running") return "正在分析...";
  const duration = Number(payload.metrics?.duration_ms ?? 0);
  if (duration > 0) return `用时 ${(duration / 1000).toFixed(1)}s`;
  if (createdAt) return new Date(createdAt).toLocaleTimeString("zh-CN", { hour: "2-digit", minute: "2-digit" });
  return "已完成";
}

export default function MessageAssistant({ payload, artifacts, createdAt, live }: MessageAssistantProps) {
  const visibleArtifacts = artifacts.filter((artifact) => payload.artifact_ids?.includes(artifact.id));

  return (
    <div className="msg assistant">
      <div className="assistant-head">
        <span className="glyph" />
        <span className="name">ChatExcel</span>
        <span className="role">分析师 · API</span>
        <span className="ts">{timeLabel(payload, createdAt, live)}</span>
      </div>

      <ReasoningCapsule reasoning={payload.reasoning} open={payload.status === "running"} />
      <PlanBlock payload={payload} />
      {payload.status === "running" ? <ProgressLine payload={payload} /> : null}
      {payload.report ? <ReportArticle markdown={payload.report} /> : null}
      {payload.error ? (
        <div className="progress-line">
          <span />
          <span>{payload.error.summary}</span>
        </div>
      ) : null}
      <ArtifactChips artifacts={visibleArtifacts.length ? visibleArtifacts : artifacts.filter((a) => payload.artifact_ids?.includes(a.id))} />

      <div className="msg-actions">
        <button title="重新生成">
          <RotateCcw size={13} /> 重新生成
        </button>
        <button title="复制" onClick={() => navigator.clipboard.writeText(payload.report || "")}>
          <Copy size={13} /> 复制
        </button>
        <button title="导出">
          <FileDown size={13} /> 导出
        </button>
        <button title="收藏">
          <Star size={13} /> 收藏
        </button>
      </div>
    </div>
  );
}
