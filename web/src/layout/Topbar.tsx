import { PanelRightOpen, Star } from "lucide-react";
import { useMutation, useQueryClient } from "@tanstack/react-query";

import { updateConversation } from "../api/http";
import type { Conversation } from "../api/types";
import { useUiStore } from "../store/uiStore";

interface TopbarProps {
  conversation?: Conversation;
  artifactCount: number;
}

export default function Topbar({ conversation, artifactCount }: TopbarProps) {
  const setArtifactPanelOpen = useUiStore((state) => state.setArtifactPanelOpen);
  const queryClient = useQueryClient();
  const star = useMutation({
    mutationFn: () =>
      conversation
        ? updateConversation(conversation.id, { starred: !conversation.starred })
        : Promise.resolve(undefined),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["conversations"] });
      if (conversation) {
        queryClient.invalidateQueries({ queryKey: ["conversation", conversation.id] });
      }
    }
  });

  return (
    <div className="topbar">
      <h1 className="topbar-title serif">{conversation?.title ?? "新的 Excel 分析"}</h1>
      {conversation ? (
        <>
          <button className="icon-button" title="收藏" onClick={() => star.mutate()}>
            <Star size={16} fill={conversation.starred ? "currentColor" : "none"} />
          </button>
          <button className="icon-button" title="打开产物面板" onClick={() => setArtifactPanelOpen(true)}>
            <PanelRightOpen size={17} />
          </button>
          <span className="topbar-meta">{artifactCount} artifacts</span>
        </>
      ) : null}
    </div>
  );
}
