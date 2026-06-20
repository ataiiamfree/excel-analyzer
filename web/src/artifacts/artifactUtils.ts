import type { Artifact } from "../api/types";

function artifactKey(artifact: Artifact) {
  return `${artifact.kind}:${artifact.name.toLowerCase()}`;
}

function timestamp(artifact: Artifact) {
  const value = Date.parse(artifact.created_at);
  return Number.isFinite(value) ? value : 0;
}

export function dedupeArtifacts(artifacts: Artifact[], preferredArtifactId?: string): Artifact[] {
  const preferred = artifacts.find((artifact) => artifact.id === preferredArtifactId);
  const preferredKey = preferred ? artifactKey(preferred) : "";
  const byKey = new Map<string, Artifact>();

  for (const artifact of artifacts) {
    const key = artifactKey(artifact);
    const current = byKey.get(key);
    if (key === preferredKey) {
      if (artifact.id === preferredArtifactId) {
        byKey.set(key, artifact);
      } else if (!current) {
        byKey.set(key, artifact);
      }
      continue;
    }

    if (!current || timestamp(artifact) >= timestamp(current)) {
      byKey.set(key, artifact);
    }
  }

  return Array.from(byKey.values()).sort((left, right) => timestamp(right) - timestamp(left));
}
