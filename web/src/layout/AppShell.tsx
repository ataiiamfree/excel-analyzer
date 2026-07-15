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
  const setArtifactPanelOpen = useUiStore((state) => state.setArtifactPanelOpen);
  const activeArtifactId = useUiStore((state) => state.activeArtifactId);
  const mobileSidebarOpen = useUiStore((state) => state.mobileSidebarOpen);
  const setMobileSidebarOpen = useUiStore((state) => state.setMobileSidebarOpen);
  const panelArtifacts = dedupeArtifacts(artifacts, activeArtifactId);

  return (
    <div className={`app ${artifactPanelOpen ? "" : "no-artifact"}`}>
      <Sidebar
        activeId={conversation?.id}
        groups={groups}
        mobileOpen={mobileSidebarOpen}
        onNavigate={() => setMobileSidebarOpen(false)}
      />
      {mobileSidebarOpen ? (
        <button
          className="mobile-backdrop"
          title="关闭会话列表"
          onClick={() => setMobileSidebarOpen(false)}
        />
      ) : null}
      <main className="center">
        <Topbar conversation={conversation} artifactCount={panelArtifacts.length} />
        {children}
      </main>
      {artifactPanelOpen ? (
        <>
          <button
            className="panel-backdrop"
            title="关闭产物面板"
            onClick={() => setArtifactPanelOpen(false)}
          />
          <ArtifactPanel artifacts={panelArtifacts} />
        </>
      ) : null}
    </div>
  );
}
