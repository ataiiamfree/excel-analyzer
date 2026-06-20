import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useLocation, useNavigate, useParams } from "react-router-dom";
import { useQuery, useQueryClient } from "@tanstack/react-query";

import { fetchArtifacts, fetchConversation, fetchConversations, fetchMessages } from "../api/http";
import { useConversationStream } from "../api/ws";
import type { AssistantMessagePayload, Message, UserMessagePayload } from "../api/types";
import AppShell from "../layout/AppShell";
import Composer from "../chat/Composer";
import Thread from "../chat/Thread";

interface LocationState {
  initialQuery?: string;
}

const INITIAL_QUERY_MARK = "chatexcel.initial-query.";

function wasInitialQueryConsumed(conversationId: string): boolean {
  try {
    return window.sessionStorage.getItem(`${INITIAL_QUERY_MARK}${conversationId}`) === "sent";
  } catch {
    return false;
  }
}

function markInitialQueryConsumed(conversationId: string): void {
  try {
    window.sessionStorage.setItem(`${INITIAL_QUERY_MARK}${conversationId}`, "sent");
  } catch {
    // sessionStorage can be unavailable in hardened browser modes; history cleanup still prevents refresh replays.
  }
}

function isSameUserMessage(message: Message, pending: Message): boolean {
  if (message.role !== "user") {
    return false;
  }

  const payload = message.payload as UserMessagePayload;
  const pendingPayload = pending.payload as UserMessagePayload;
  if (payload.client_msg_id && payload.client_msg_id === pendingPayload.client_msg_id) {
    return true;
  }

  const createdAt = Date.parse(message.created_at);
  const pendingAt = Date.parse(pending.created_at);
  return payload.text === pendingPayload.text && Math.abs(createdAt - pendingAt) < 60_000;
}

export default function ConversationPage() {
  const { conversationId = "" } = useParams();
  const location = useLocation();
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const sentInitial = useRef(false);
  const [threadAtBottom, setThreadAtBottom] = useState(true);
  const state = (location.state ?? {}) as LocationState;
  const initialQuery = state.initialQuery?.trim() ?? "";

  const conversations = useQuery({ queryKey: ["conversations"], queryFn: fetchConversations });
  const conversation = useQuery({
    queryKey: ["conversation", conversationId],
    queryFn: () => fetchConversation(conversationId),
    enabled: Boolean(conversationId)
  });
  const messages = useQuery({
    queryKey: ["messages", conversationId],
    queryFn: () => fetchMessages(conversationId),
    enabled: Boolean(conversationId)
  });
  const artifacts = useQuery({
    queryKey: ["artifacts", conversationId],
    queryFn: () => fetchArtifacts(conversationId),
    enabled: Boolean(conversationId),
    refetchInterval: 2500
  });
  const stream = useConversationStream(conversationId);
  const persistedMessageCount = messages.data?.length ?? 0;

  useEffect(() => {
    sentInitial.current = false;
    setThreadAtBottom(true);
  }, [conversationId]);

  useEffect(() => {
    if (stream.livePayload?.status === "done" || stream.livePayload?.status === "failed") {
      queryClient.invalidateQueries({ queryKey: ["messages", conversationId] });
      queryClient.invalidateQueries({ queryKey: ["artifacts", conversationId] });
      queryClient.invalidateQueries({ queryKey: ["conversations"] });
    }
  }, [conversationId, queryClient, stream.livePayload?.status]);

  useEffect(() => {
    if (!initialQuery || sentInitial.current || !messages.isFetched || stream.status !== "open") {
      return;
    }

    sentInitial.current = true;
    navigate(`/c/${conversationId}`, { replace: true, state: null });

    if (persistedMessageCount > 0 || wasInitialQueryConsumed(conversationId)) {
      return;
    }

    markInitialQueryConsumed(conversationId);
    stream.sendMessage(initialQuery);
  }, [
    conversationId,
    initialQuery,
    messages.isFetched,
    navigate,
    persistedMessageCount,
    stream.sendMessage,
    stream.status
  ]);

  const allArtifacts = artifacts.data ?? [];
  const livePayload = stream.livePayload?.status === "running" ? stream.livePayload : null;
  const hydratedMessages = useMemo(() => messages.data ?? [], [messages.data]);
  const displayedMessages = useMemo(() => {
    if (!stream.pendingUserMessage) {
      return hydratedMessages;
    }
    const pendingPersisted = hydratedMessages.some((message) => isSameUserMessage(message, stream.pendingUserMessage!));
    return pendingPersisted ? hydratedMessages : [...hydratedMessages, stream.pendingUserMessage];
  }, [hydratedMessages, stream.pendingUserMessage]);
  const persistedNextActions = useMemo(() => {
    const latestAssistant = [...hydratedMessages]
      .reverse()
      .find((message) => message.role === "assistant" && (message.payload as AssistantMessagePayload).status === "done");
    return ((latestAssistant?.payload as AssistantMessagePayload | undefined)?.next_actions ?? []).slice(0, 3);
  }, [hydratedMessages]);
  const nextActions =
    !threadAtBottom || stream.livePayload?.status === "running"
      ? []
      : stream.livePayload?.status === "done"
        ? (stream.livePayload.next_actions ?? []).slice(0, 3)
        : persistedNextActions;
  const handleThreadBottomChange = useCallback((atBottom: boolean) => {
    setThreadAtBottom(atBottom);
  }, []);

  return (
    <AppShell conversation={conversation.data} groups={conversations.data?.groups ?? []} artifacts={allArtifacts}>
      <Thread
        messages={displayedMessages}
        livePayload={livePayload}
        artifacts={allArtifacts}
        onAtBottomChange={handleThreadBottomChange}
      />
      <Composer
        disabled={stream.status !== "open" || stream.livePayload?.status === "running"}
        nextActions={nextActions}
        onSend={stream.sendMessage}
      />
    </AppShell>
  );
}
