import { useEffect, useRef } from "react";

import type { Artifact, AssistantMessagePayload, Message } from "../api/types";
import MessageAssistant from "./MessageAssistant";
import MessageUser from "./MessageUser";

interface ThreadProps {
  messages: Message[];
  livePayload: AssistantMessagePayload | null;
  artifacts: Artifact[];
}

export default function Thread({ messages, livePayload, artifacts }: ThreadProps) {
  const endRef = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    endRef.current?.scrollIntoView({ behavior: "smooth", block: "end" });
  }, [messages.length, livePayload?.report, livePayload?.steps.length]);

  return (
    <div className="thread" id="thread">
      <div className="thread-inner">
        <div className="day-rule">
          <span>今天 · {new Date().toLocaleDateString("zh-CN")}</span>
        </div>
        {messages.map((message) =>
          message.role === "user" ? (
            <MessageUser key={message.id} payload={message.payload as never} />
          ) : (
            <MessageAssistant
              key={message.id}
              payload={message.payload as AssistantMessagePayload}
              artifacts={artifacts}
              createdAt={message.created_at}
            />
          )
        )}
        {livePayload && livePayload.status === "running" ? (
          <MessageAssistant payload={livePayload} artifacts={artifacts} live />
        ) : null}
        <div ref={endRef} />
      </div>
    </div>
  );
}
