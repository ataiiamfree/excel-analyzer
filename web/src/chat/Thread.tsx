import { useEffect, useRef } from "react";

import type { Artifact, AssistantMessagePayload, Message, UserMessagePayload } from "../api/types";
import MessageAssistant from "./MessageAssistant";
import MessageUser from "./MessageUser";

interface ThreadProps {
  messages: Message[];
  livePayload: AssistantMessagePayload | null;
  artifacts: Artifact[];
  actionsDisabled?: boolean;
  onAtBottomChange?: (atBottom: boolean) => void;
  onRegenerate?: (query: string) => void;
}

export default function Thread({
  messages,
  livePayload,
  artifacts,
  actionsDisabled,
  onAtBottomChange,
  onRegenerate
}: ThreadProps) {
  const threadRef = useRef<HTMLDivElement | null>(null);
  const atBottomRef = useRef(true);

  useEffect(() => {
    const thread = threadRef.current;
    if (!thread) return;

    if (!atBottomRef.current) {
      return;
    }
    window.requestAnimationFrame(() => {
      thread.scrollTo({ top: thread.scrollHeight, behavior: "smooth" });
    });
  }, [messages.length, livePayload?.report, livePayload?.steps.length]);

  useEffect(() => {
    const thread = threadRef.current;
    if (!thread) return;

    const updateAtBottom = () => {
      const distance = thread.scrollHeight - thread.scrollTop - thread.clientHeight;
      const atBottom = distance <= 120;
      if (atBottomRef.current !== atBottom) {
        atBottomRef.current = atBottom;
        onAtBottomChange?.(atBottom);
      }
    };

    updateAtBottom();
    thread.addEventListener("scroll", updateAtBottom, { passive: true });
    window.addEventListener("resize", updateAtBottom);
    return () => {
      thread.removeEventListener("scroll", updateAtBottom);
      window.removeEventListener("resize", updateAtBottom);
    };
  }, [onAtBottomChange]);

  return (
    <div className="thread" id="thread" ref={threadRef}>
      <div className="thread-inner">
        <div className="day-rule">
          <span>今天 · {new Date().toLocaleDateString("zh-CN")}</span>
        </div>
        {messages.map((message) =>
          message.role === "user" ? (
            <MessageUser key={message.id} payload={message.payload as UserMessagePayload} />
          ) : (
            <MessageAssistant
              key={message.id}
              payload={message.payload as AssistantMessagePayload}
              artifacts={artifacts}
              createdAt={message.created_at}
              actionsDisabled={actionsDisabled}
              onRegenerate={onRegenerate}
            />
          )
        )}
        {livePayload && livePayload.status === "running" ? (
          <MessageAssistant payload={livePayload} artifacts={artifacts} live actionsDisabled />
        ) : null}
      </div>
    </div>
  );
}
