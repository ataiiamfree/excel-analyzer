import { useEffect, useState } from "react";
import { Copy, Download, Maximize2, X } from "lucide-react";

import type { Artifact } from "../api/types";

interface ChartPreviewProps {
  artifact: Artifact;
  active?: boolean;
}

export default function ChartPreview({ artifact, active }: ChartPreviewProps) {
  const [expanded, setExpanded] = useState(false);

  useEffect(() => {
    if (!expanded) return;
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        setExpanded(false);
      }
    };
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [expanded]);

  return (
    <div className={`preview-card ${active ? "active" : ""}`} data-artifact-id={artifact.id}>
      <div className="cap">
        <span className="name">{artifact.name}</span>
        <span className="meta">{Math.ceil(artifact.size / 1024)} KB</span>
        <button className="act" title="放大预览" onClick={() => setExpanded(true)}>
          <Maximize2 size={13} />
        </button>
        <button className="act" title="复制链接" onClick={() => navigator.clipboard.writeText(artifact.url)}>
          <Copy size={13} />
        </button>
        <a className="act" href={artifact.url} download title="下载">
          <Download size={13} />
        </a>
      </div>
      <div className="chart">
        <img src={artifact.url} alt={artifact.name} />
      </div>
      {expanded ? (
        <div className="artifact-modal" role="dialog" aria-modal="true" onClick={(event) => {
          if (event.target === event.currentTarget) {
            setExpanded(false);
          }
        }}>
          <div className="artifact-modal-card image-modal-card">
            <div className="artifact-modal-head">
              <div>
                <div className="name">{artifact.name}</div>
                <div className="meta">{Math.ceil(artifact.size / 1024)} KB</div>
              </div>
              <div className="modal-actions">
                <a className="icon-button" href={artifact.url} download title="下载">
                  <Download size={16} />
                </a>
                <button className="icon-button" title="关闭" onClick={() => setExpanded(false)}>
                  <X size={16} />
                </button>
              </div>
            </div>
            <div className="image-modal-body">
              <img src={artifact.url} alt={artifact.name} />
            </div>
          </div>
        </div>
      ) : null}
    </div>
  );
}
