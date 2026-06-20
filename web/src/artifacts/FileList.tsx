import { Download, Eye } from "lucide-react";

import type { Artifact } from "../api/types";
import { useUiStore } from "../store/uiStore";

interface FileListProps {
  artifacts: Artifact[];
}

function iconClass(kind: string) {
  if (kind === "chart") return "p";
  if (kind === "csv" || kind === "data") return "c";
  return "x";
}

function iconLabel(kind: string) {
  if (kind === "chart") return "IMG";
  if (kind === "csv") return "CSV";
  if (kind === "report") return "MD";
  return "XL";
}

export default function FileList({ artifacts }: FileListProps) {
  const activeArtifactId = useUiStore((state) => state.activeArtifactId);
  const setActiveArtifactId = useUiStore((state) => state.setActiveArtifactId);

  return (
    <div className="preview-card">
      <div className="cap">
        <span className="name">所有产物</span>
        <span className="meta">{artifacts.length} 件</span>
      </div>
      <div style={{ padding: "10px 12px" }}>
        <div className="file-list">
          {artifacts.map((artifact) => (
            <div
              className={`file-row ${artifact.id === activeArtifactId ? "active" : ""}`}
              data-artifact-id={artifact.id}
              key={artifact.id}
            >
              <span className={`ico ${iconClass(artifact.kind)}`}>{iconLabel(artifact.kind)}</span>
              <div style={{ minWidth: 0 }}>
                <div className="nm">{artifact.name}</div>
                <div className="mt">
                  {Math.ceil(artifact.size / 1024)} KB · {new Date(artifact.created_at).toLocaleTimeString("zh-CN")}
                </div>
              </div>
              <div className="right">
                {isPreviewArtifact(artifact) ? (
                  <button title="在预览中打开" onClick={() => setActiveArtifactId(artifact.id)}>
                    <Eye size={14} />
                  </button>
                ) : null}
                <a href={artifact.url} download title="下载">
                  <Download size={14} />
                </a>
              </div>
            </div>
          ))}
          {artifacts.length === 0 ? (
            <div style={{ padding: 10, color: "var(--ink-3)" }}>暂无产物。</div>
          ) : null}
        </div>
      </div>
    </div>
  );
}

function isPreviewArtifact(artifact: Artifact) {
  return ["chart", "excel", "csv", "data"].includes(artifact.kind);
}
