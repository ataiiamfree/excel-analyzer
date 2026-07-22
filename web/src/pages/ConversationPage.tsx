import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useLocation, useNavigate, useParams } from "react-router-dom";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import {
  fetchArtifacts,
  fetchConversation,
  fetchConversations,
  fetchMessages,
  replaceConversationFile
} from "../api/http";
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
  const [fileNotice, setFileNotice] = useState("");
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
  const replaceFile = useMutation({
    mutationFn: (file: File) => replaceConversationFile(conversationId, file),
    onSuccess: (updated) => {
      setFileNotice(`已切换到 ${updated.file_name ?? "新 Excel 文件"}`);
      queryClient.invalidateQueries({ queryKey: ["conversation", conversationId] });
      queryClient.invalidateQueries({ queryKey: ["conversations"] });
    },
    onError: (error) => {
      setFileNotice(error instanceof Error ? error.message : "替换 Excel 失败");
    }
  });
  const persistedMessageCount = messages.data?.length ?? 0;

  useEffect(() => {
    sentInitial.current = false;
    setThreadAtBottom(true);
  }, [conversationId]);

  useEffect(() => {
    if (["done", "failed", "cancelled"].includes(stream.livePayload?.status ?? "")) {
      queryClient.invalidateQueries({ queryKey: ["messages", conversationId] });
      queryClient.invalidateQueries({ queryKey: ["artifacts", conversationId] });
      queryClient.invalidateQueries({ queryKey: ["conversations"] });
    }
  }, [conversationId, queryClient, stream.livePayload?.status]);

  useEffect(() => {
    if (stream.status !== "open") return;
    queryClient.invalidateQueries({ queryKey: ["messages", conversationId] });
    queryClient.invalidateQueries({ queryKey: ["conversation", conversationId] });
  }, [conversationId, queryClient, stream.status]);

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
  const isRunning = stream.livePayload?.status === "running";
  const connectionUnavailable = stream.status !== "open";
  const conversationUnavailable =
    conversation.isLoading || messages.isLoading || conversation.isError || messages.isError;
  const actionsDisabled = connectionUnavailable || isRunning;
  const handleRegenerate = useCallback(
    (query: string) => {
      if (actionsDisabled) {
        return;
      }
      stream.sendMessage(query);
    },
    [actionsDisabled, stream.sendMessage]
  );

  const connectionNotice =
    stream.status === "connecting"
      ? "正在连接分析服务..."
      : stream.status === "reconnecting"
        ? stream.connectionError || "连接中断，正在自动重连..."
        : stream.status === "closed"
          ? stream.connectionError || "连接已断开"
          : stream.connectionError;
  const composerNotice = replaceFile.isPending
    ? "正在校验并替换 Excel..."
    : fileNotice || connectionNotice;

  const threadContent = conversation.isLoading || messages.isLoading ? (
    <div className="page-state" role="status">
      <span className="state-spinner" />
      <strong>正在加载会话</strong>
    </div>
  ) : conversation.isError || messages.isError ? (
    <div className="page-state error" role="alert">
      <strong>无法加载该会话</strong>
      <span>{(conversation.error ?? messages.error)?.message ?? "会话不存在或服务暂时不可用"}</span>
      <button onClick={() => navigate("/")}>返回首页</button>
    </div>
  ) : (
    <Thread
      messages={displayedMessages}
      livePayload={livePayload}
      artifacts={allArtifacts}
      actionsDisabled={actionsDisabled}
      onAtBottomChange={handleThreadBottomChange}
      onRegenerate={handleRegenerate}
    />
  );

  return (
    <AppShell conversation={conversation.data} groups={conversations.data?.groups ?? []} artifacts={allArtifacts}>
      {threadContent}
      <Composer
        disabled={connectionUnavailable || conversationUnavailable}
        running={isRunning}
        attaching={replaceFile.isPending}
        nextActions={nextActions}
        notice={composerNotice}
        onSend={stream.sendMessage}
        onCancel={stream.cancel}
        onAttach={(file) => replaceFile.mutateAsync(file)}
        onReconnect={stream.reconnect}
        reconnectAvailable={stream.status === "closed" || stream.persistentRetry}
      />
    </AppShell>
  );
}
