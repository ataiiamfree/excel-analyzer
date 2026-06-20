import { useEffect, useMemo, useState } from "react";
import { Download, PanelRightClose } from "lucide-react";

import type { Artifact } from "../api/types";
import { useUiStore } from "../store/uiStore";
import ChartPreview from "../artifacts/ChartPreview";
import FileList from "../artifacts/FileList";
import TablePreview from "../artifacts/TablePreview";

interface ArtifactPanelProps {
  artifacts: Artifact[];
}

export default function ArtifactPanel({ artifacts }: ArtifactPanelProps) {
  const [tab, setTab] = useState<"preview" | "files" | "code">("preview");
  const setArtifactPanelOpen = useUiStore((state) => state.setArtifactPanelOpen);
  const activeArtifactId = useUiStore((state) => state.activeArtifactId);
  const previewArtifacts = useMemo(
    () => artifacts.filter(isPreviewArtifact),
    [artifacts]
  );
  const codeArtifacts = useMemo(() => artifacts.filter(isCodeArtifact), [artifacts]);
  const activeArtifact = useMemo(
    () => artifacts.find((artifact) => artifact.id === activeArtifactId),
    [activeArtifactId, artifacts]
  );

  useEffect(() => {
    if (tab === "code" && codeArtifacts.length === 0) {
      setTab("preview");
    }
  }, [codeArtifacts.length, tab]);

  useEffect(() => {
    if (!activeArtifact) return;
    const nextTab = isPreviewArtifact(activeArtifact) ? "preview" : "files";
    setTab(nextTab);
    window.setTimeout(() => {
      document.querySelector(`[data-artifact-id="${activeArtifact.id}"]`)?.scrollIntoView({
        block: "start",
        behavior: "smooth"
      });
    }, 0);
  }, [activeArtifact?.id, activeArtifact?.kind]);

  return (
    <aside className="panel">
      <div className="panel-head">
        <span className="title">产物预览</span>
        <button className="close" title="折叠" onClick={() => setArtifactPanelOpen(false)}>
          <PanelRightClose size={16} />
        </button>
      </div>
      <div className="tabs">
        <button className={`tab ${tab === "preview" ? "active" : ""}`} onClick={() => setTab("preview")}>
          预览 <span className="count">{previewArtifacts.length}</span>
        </button>
        <button className={`tab ${tab === "files" ? "active" : ""}`} onClick={() => setTab("files")}>
          文件 <span className="count">{artifacts.length}</span>
        </button>
        {codeArtifacts.length > 0 ? (
          <button className={`tab ${tab === "code" ? "active" : ""}`} onClick={() => setTab("code")}>
            代码 <span className="count">{codeArtifacts.length}</span>
          </button>
        ) : null}
      </div>

      <div className="panel-body">
        {tab === "preview" ? (
          <>
            {previewArtifacts.map((artifact) =>
              artifact.kind === "chart" ? (
                <ChartPreview key={artifact.id} artifact={artifact} active={artifact.id === activeArtifactId} />
              ) : (
                <TablePreview key={artifact.id} artifact={artifact} active={artifact.id === activeArtifactId} />
              )
            )}
            {previewArtifacts.length === 0 ? <EmptyPanel /> : null}
          </>
        ) : null}
        {tab === "files" ? <FileList artifacts={artifacts} /> : null}
        {tab === "code" ? (
          <div className="file-list">
            {codeArtifacts.map((artifact) => (
              <div className="file-row" key={artifact.id}>
                <span className="ico c">CODE</span>
                <div>
                  <div className="nm">{artifact.name}</div>
                  <div className="mt">{Math.ceil(artifact.size / 1024)} KB</div>
                </div>
                <div className="right">
                  <a href={artifact.url} download title="下载">
                    <Download size={14} />
                  </a>
                </div>
              </div>
            ))}
            {codeArtifacts.length === 0 ? <EmptyPanel /> : null}
          </div>
        ) : null}
        <div className="signature">
          <span>ChatExcel</span>
          <span>{new Date().toLocaleDateString("zh-CN")}</span>
        </div>
      </div>
    </aside>
  );
}

function isPreviewArtifact(artifact: Artifact) {
  return ["chart", "excel", "csv", "data"].includes(artifact.kind);
}

function isCodeArtifact(artifact: Artifact) {
  return [".py", ".sql", ".ipynb", ".r", ".js", ".ts", ".tsx"].some((suffix) =>
    artifact.name.toLowerCase().endsWith(suffix)
  );
}

function EmptyPanel() {
  return (
    <div className="preview-card">
      <div className="cap">
        <span className="name">等待产物</span>
        <span className="meta">0 件</span>
      </div>
      <div style={{ padding: 16, color: "var(--ink-3)" }}>分析完成后，图表、表格和报告会出现在这里。</div>
    </div>
  );
}
