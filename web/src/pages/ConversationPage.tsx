import { useEffect, useMemo, useRef } from "react";
import { useLocation, useNavigate, useParams } from "react-router-dom";
import { useQuery, useQueryClient } from "@tanstack/react-query";

import { fetchArtifacts, fetchConversation, fetchConversations, fetchMessages } from "../api/http";
import { useConversationStream } from "../api/ws";
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

export default function ConversationPage() {
  const { conversationId = "" } = useParams();
  const location = useLocation();
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const sentInitial = useRef(false);
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

  return (
    <AppShell conversation={conversation.data} groups={conversations.data?.groups ?? []} artifacts={allArtifacts}>
      <Thread messages={hydratedMessages} livePayload={livePayload} artifacts={allArtifacts} />
      <Composer disabled={stream.status !== "open" || stream.livePayload?.status === "running"} onSend={stream.sendMessage} />
    </AppShell>
  );
}
