import type { Artifact } from "../api/types";
import { useUiStore } from "../store/uiStore";

interface ArtifactChipsProps {
  artifacts: Artifact[];
}

function iconLabel(kind: string) {
  if (kind === "chart") return "IMG";
  if (kind === "csv") return "CSV";
  if (kind === "report") return "MD";
  return "XL";
}

export default function ArtifactChips({ artifacts }: ArtifactChipsProps) {
  const setActiveArtifactId = useUiStore((state) => state.setActiveArtifactId);
  if (!artifacts.length) {
    return null;
  }
  return (
    <div className="artifact-chips">
      {artifacts.map((artifact) => (
        <button className="chip" key={artifact.id} onClick={() => setActiveArtifactId(artifact.id)}>
          <span className={`ico ${artifact.kind}`}>{iconLabel(artifact.kind)}</span>
          <span className="info">
            <span className="n">{artifact.name}</span>
            <span className="s">{Math.ceil(artifact.size / 1024)} KB</span>
          </span>
        </button>
      ))}
    </div>
  );
}
