import { Menu, PanelRightClose, PanelRightOpen } from "lucide-react";

import type { Conversation } from "../api/types";
import { useUiStore } from "../store/uiStore";

interface TopbarProps {
  conversation?: Conversation;
  artifactCount: number;
}

export default function Topbar({ conversation, artifactCount }: TopbarProps) {
  const artifactPanelOpen = useUiStore((state) => state.artifactPanelOpen);
  const setArtifactPanelOpen = useUiStore((state) => state.setArtifactPanelOpen);
  const setMobileSidebarOpen = useUiStore((state) => state.setMobileSidebarOpen);

  return (
    <div className="topbar">
      <button
        className="icon-button mobile-menu"
        title="打开会话列表"
        onClick={() => setMobileSidebarOpen(true)}
      >
        <Menu size={17} />
      </button>
      <h1 className="topbar-title serif">{conversation?.title ?? "新的 Excel 分析"}</h1>
      {conversation ? (
        <div className="topbar-actions">
          <span className="topbar-meta">{artifactCount} 个产物</span>
          <button
            className="icon-button"
            title={artifactPanelOpen ? "隐藏产物面板" : "打开产物面板"}
            onClick={() => setArtifactPanelOpen(!artifactPanelOpen)}
          >
            {artifactPanelOpen ? <PanelRightClose size={17} /> : <PanelRightOpen size={17} />}
          </button>
        </div>
      ) : null}
    </div>
  );
}
