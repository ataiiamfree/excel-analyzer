import { Copy, Download } from "lucide-react";

import type { Artifact } from "../api/types";

interface ChartPreviewProps {
  artifact: Artifact;
  active?: boolean;
}

export default function ChartPreview({ artifact, active }: ChartPreviewProps) {
  return (
    <div className={`preview-card ${active ? "active" : ""}`} data-artifact-id={artifact.id}>
      <div className="cap">
        <span className="name">{artifact.name}</span>
        <span className="meta">{Math.ceil(artifact.size / 1024)} KB</span>
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
    </div>
  );
}
