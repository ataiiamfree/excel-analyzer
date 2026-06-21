import { useMemo, useState } from "react";
import { Check, Copy, FileDown, RotateCcw } from "lucide-react";

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
  actionsDisabled?: boolean;
  onRegenerate?: (query: string) => void;
}

function timeLabel(payload: AssistantMessagePayload, createdAt?: string, live?: boolean) {
  if (live || payload.status === "running") return "正在分析...";
  const duration = Number(payload.metrics?.duration_ms ?? 0);
  if (duration > 0) return `用时 ${(duration / 1000).toFixed(1)}s`;
  if (createdAt) return new Date(createdAt).toLocaleTimeString("zh-CN", { hour: "2-digit", minute: "2-digit" });
  return "已完成";
}

function safeFileName(value: string) {
  return value
    .trim()
    .replace(/[\\/:*?"<>|]+/g, "-")
    .replace(/\s+/g, "-")
    .slice(0, 48) || "chatexcel-report";
}

function artifactUrl(artifact: Artifact) {
  return new URL(artifact.url, window.location.origin).toString();
}

function exportMarkdown(payload: AssistantMessagePayload, artifacts: Artifact[]) {
  const lines = [
    "# ChatExcel 分析结果",
    "",
    `- 问题：${payload.query || "未记录"}`,
    `- 状态：${payload.status}`,
  ];

  const duration = Number(payload.metrics?.duration_ms ?? 0);
  if (duration > 0) {
    lines.push(`- 用时：${(duration / 1000).toFixed(1)}s`);
  }

  if (payload.error?.summary) {
    lines.push("", "## 错误", "", payload.error.summary);
  }

  if (payload.report?.trim()) {
    lines.push("", "## 报告", "", payload.report.trim());
  }

  if (artifacts.length > 0) {
    lines.push("", "## 产物", "");
    artifacts.forEach((artifact) => {
      lines.push(`- [${artifact.name}](${artifactUrl(artifact)})`);
    });
  }

  return `${lines.join("\n")}\n`;
}

async function writeClipboard(text: string) {
  if (navigator.clipboard?.writeText) {
    await navigator.clipboard.writeText(text);
    return;
  }

  const textarea = document.createElement("textarea");
  textarea.value = text;
  textarea.setAttribute("readonly", "");
  textarea.style.position = "fixed";
  textarea.style.left = "-9999px";
  document.body.appendChild(textarea);
  textarea.select();
  const copied = document.execCommand("copy");
  textarea.remove();
  if (!copied) {
    throw new Error("clipboard unavailable");
  }
}

export default function MessageAssistant({
  payload,
  artifacts,
  createdAt,
  live,
  actionsDisabled,
  onRegenerate
}: MessageAssistantProps) {
  const [copyState, setCopyState] = useState<"idle" | "copied" | "failed">("idle");
  const visibleArtifacts = useMemo(
    () => artifacts.filter((artifact) => payload.artifact_ids?.includes(artifact.id)),
    [artifacts, payload.artifact_ids]
  );
  const canAct = !live && payload.status !== "running";
  const canRegenerate = canAct && !actionsDisabled && Boolean(payload.query.trim()) && Boolean(onRegenerate);
  const canCopy = canAct && Boolean((payload.report || payload.error?.summary || "").trim());
  const canExport = canAct && (canCopy || visibleArtifacts.length > 0);

  const copyText = async () => {
    if (!canCopy) return;
    try {
      await writeClipboard(payload.report || payload.error?.summary || "");
      setCopyState("copied");
      window.setTimeout(() => setCopyState("idle"), 1400);
    } catch {
      setCopyState("failed");
      window.setTimeout(() => setCopyState("idle"), 1800);
    }
  };

  const exportReport = () => {
    if (!canExport) return;
    const markdown = exportMarkdown(payload, visibleArtifacts);
    const blob = new Blob([markdown], { type: "text/markdown;charset=utf-8" });
    const url = URL.createObjectURL(blob);
    const link = document.createElement("a");
    const stamp = new Date().toISOString().replace(/[:.]/g, "-");
    link.href = url;
    link.download = `${safeFileName(payload.query)}-${stamp}.md`;
    document.body.appendChild(link);
    link.click();
    link.remove();
    window.setTimeout(() => URL.revokeObjectURL(url), 1000);
  };

  return (
    <div className="msg assistant">
      <div className="assistant-head">
        <span className="glyph" />
        <span className="name">ChatExcel</span>
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
      <ArtifactChips artifacts={visibleArtifacts} />

      <div className="msg-actions">
        <button title="重新生成" onClick={() => onRegenerate?.(payload.query)} disabled={!canRegenerate}>
          <RotateCcw size={13} /> 重新生成
        </button>
        <button title="复制" onClick={copyText} disabled={!canCopy}>
          {copyState === "copied" ? <Check size={13} /> : <Copy size={13} />}
          {copyState === "copied" ? "已复制" : copyState === "failed" ? "复制失败" : "复制"}
        </button>
        <button title="导出" onClick={exportReport} disabled={!canExport}>
          <FileDown size={13} /> 导出
        </button>
      </div>
    </div>
  );
}
