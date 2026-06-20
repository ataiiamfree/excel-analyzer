import type { ReactNode } from "react";

import type { Artifact, Conversation, ConversationGroup } from "../api/types";
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

  return (
    <div className={`app ${artifactPanelOpen ? "" : "no-artifact"}`}>
      <Sidebar activeId={conversation?.id} groups={groups} />
      <main className="center">
        <Topbar conversation={conversation} artifactCount={artifacts.length} />
        {children}
      </main>
      {artifactPanelOpen ? <ArtifactPanel artifacts={artifacts} /> : null}
    </div>
  );
}
