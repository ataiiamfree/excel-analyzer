import type { ReactNode } from "react";

import type { Artifact, Conversation, ConversationGroup } from "../api/types";
import { dedupeArtifacts } from "../artifacts/artifactUtils";
import { useUiStore } from "../store/uiStore";
import ArtifactPanel from "./ArtifactPanel";
import Sidebar from "./Sidebar";
import Topbar from "./Topbar";

interface AppShellProps {
  conversation?: Conversation;
  groups: ConversationGroup[];
  artifacts: Artifact[];
  children: ReactNode;
}

export default function AppShell({ conversation, groups, artifacts, children }: AppShellProps) {
  const artifactPanelOpen = useUiStore((state) => state.artifactPanelOpen);
  const activeArtifactId = useUiStore((state) => state.activeArtifactId);
  const panelArtifacts = dedupeArtifacts(artifacts, activeArtifactId);

  return (
    <div className={`app ${artifactPanelOpen ? "" : "no-artifact"}`}>
      <Sidebar activeId={conversation?.id} groups={groups} />
      <main className="center">
        <Topbar conversation={conversation} artifactCount={panelArtifacts.length} />
        {children}
      </main>
      {artifactPanelOpen ? <ArtifactPanel artifacts={panelArtifacts} /> : null}
    </div>
  );
}
