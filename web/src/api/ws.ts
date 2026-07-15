import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import type { AssistantMessagePayload, Message, ServerEvent } from "./types";

const MAX_LIVE_REASONING_CHARS = 20_000;

function initialPayload(query = ""): AssistantMessagePayload {
  return {
    status: "running",
    query,
    plan: { steps: [] },
    reasoning: { text: "", tokens: 0 },
    steps: [],
    report: "",
    next_actions: [],
    artifact_ids: [],
    metrics: {}
  };
}

function reduceEvent(payload: AssistantMessagePayload | null, event: ServerEvent): AssistantMessagePayload | null {
  if (event.type === "run.start") {
    return payload ?? initialPayload();
  }
  if (!payload) {
    return null;
  }
  if (event.type === "plan.ready") {
    return { ...payload, plan: { steps: event.steps } };
  }
  if (event.type === "reasoning.delta") {
    const current = payload.reasoning ?? { text: "", tokens: 0 };
    return {
      ...payload,
      reasoning: {
        text: (current.text + event.delta).slice(-MAX_LIVE_REASONING_CHARS),
        tokens: current.tokens + Math.max(1, Math.floor(event.delta.length / 4))
      }
    };
  }
  if (event.type === "step.start") {
    return {
      ...payload,
      steps: [
        ...payload.steps,
        {
          step_id: event.step_id,
          status: "running",
          started_at: event.ts,
          artifact_ids: []
        }
      ]
    };
  }
  if (event.type === "step.end") {
    return {
      ...payload,
      steps: payload.steps.map((step) =>
        step.step_id === event.step_id
          ? {
              ...step,
              status: event.status,
              ended_at: event.ts,
              stdout: event.stdout,
              error: event.error,
              script_path: event.script_path ?? undefined
            }
          : step
      )
    };
  }
  if (event.type === "report.delta") {
    return { ...payload, report: payload.report + event.delta };
  }
  if (event.type === "artifact.created") {
    return { ...payload, artifact_ids: [...payload.artifact_ids, event.artifact_id] };
  }
  if (event.type === "run.complete") {
    const result = event.result;
    return {
      ...(result ?? payload),
      status: result?.status ?? "done",
      report: event.report || result?.report || payload.report,
      next_actions: result?.next_actions ?? payload.next_actions ?? [],
      artifact_ids: event.file_ids.length ? event.file_ids : result?.artifact_ids ?? payload.artifact_ids,
      metrics: { ...payload.metrics, ...(result?.metrics ?? {}), duration_ms: event.duration_ms }
    };
  }
  if (event.type === "run.failed") {
    return {
      ...payload,
      status: "failed",
      error: {
        failed_step_description: event.failed_step_description,
        summary: event.error_summary,
        kind: event.error_kind
      }
    };
  }
  if (event.type === "cancelled") {
    return {
      ...payload,
      status: "cancelled",
      steps: payload.steps.map((step) =>
        step.status === "running"
          ? { ...step, status: "cancelled", ended_at: event.ts }
          : step
      )
    };
  }
  return payload;
}

export function useConversationStream(conversationId: string) {
  const socketRef = useRef<WebSocket | null>(null);
  const [status, setStatus] = useState<"connecting" | "open" | "reconnecting" | "closed">("connecting");
  const [livePayload, setLivePayload] = useState<AssistantMessagePayload | null>(null);
  const [pendingUserMessage, setPendingUserMessage] = useState<Message | null>(null);
  const [connectionError, setConnectionError] = useState("");
  const [reconnectKey, setReconnectKey] = useState(0);

  const wsUrl = useMemo(() => {
    const proto = window.location.protocol === "https:" ? "wss" : "ws";
    return `${proto}://${window.location.host}/ws/conversations/${conversationId}`;
  }, [conversationId]);

  useEffect(() => {
    let disposed = false;
    let retryTimer: number | undefined;
    let retryCount = 0;

    setLivePayload(null);
    setPendingUserMessage(null);
    setConnectionError("");
    setStatus("connecting");

    const connect = () => {
      if (disposed) return;
      setStatus(retryCount === 0 ? "connecting" : "reconnecting");
      const ws = new WebSocket(wsUrl);
      socketRef.current = ws;
      ws.onopen = () => {
        retryCount = 0;
        setConnectionError("");
        setStatus("open");
      };
      ws.onclose = () => {
        if (disposed) return;
        socketRef.current = null;
        if (retryCount < 3) {
          retryCount += 1;
          setStatus("reconnecting");
          retryTimer = window.setTimeout(connect, 2 ** (retryCount - 1) * 1000);
        } else {
          setStatus("closed");
          setConnectionError("连接已断开，请检查后端服务后重连");
        }
      };
      ws.onerror = () => ws.close();
      ws.onmessage = (message) => {
        try {
          const event = JSON.parse(message.data) as ServerEvent;
          if (event.type === "error") {
            setConnectionError(event.summary);
            return;
          }
          setLivePayload((current) => reduceEvent(current, event));
        } catch {
          setConnectionError("收到了无法解析的服务器消息");
        }
      };
    };

    connect();
    return () => {
      disposed = true;
      if (retryTimer) window.clearTimeout(retryTimer);
      socketRef.current?.close();
      socketRef.current = null;
    };
  }, [reconnectKey, wsUrl]);

  const sendMessage = useCallback((content: string) => {
    const text = content.trim();
    const socket = socketRef.current;
    if (!text || socket?.readyState !== WebSocket.OPEN) {
      return;
    }

    const clientMsgId = crypto.randomUUID();
    setPendingUserMessage({
      id: `pending-${clientMsgId}`,
      conversation_id: conversationId,
      role: "user",
      created_at: new Date().toISOString(),
      payload: { text, client_msg_id: clientMsgId }
    });
    setLivePayload(initialPayload(text));
    socket.send(
      JSON.stringify({
        type: "user_message",
        content: text,
        client_msg_id: clientMsgId
      })
    );
  }, [conversationId]);

  const cancel = useCallback(() => {
    socketRef.current?.send(JSON.stringify({ type: "cancel" }));
  }, []);

  const reconnect = useCallback(() => {
    socketRef.current?.close();
    setReconnectKey((value) => value + 1);
  }, []);

  return {
    status,
    connectionError,
    livePayload,
    pendingUserMessage,
    sendMessage,
    cancel,
    reconnect
  };
}
