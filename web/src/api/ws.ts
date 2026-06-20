import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import type { AssistantMessagePayload, ServerEvent } from "./types";

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
        text: current.text + event.delta,
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
      status: "done",
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
        summary: event.error_summary
      }
    };
  }
  if (event.type === "cancelled") {
    return { ...payload, status: "cancelled" };
  }
  return payload;
}

export function useConversationStream(conversationId: string) {
  const socketRef = useRef<WebSocket | null>(null);
  const [status, setStatus] = useState<"connecting" | "open" | "closed">("connecting");
  const [livePayload, setLivePayload] = useState<AssistantMessagePayload | null>(null);

  const wsUrl = useMemo(() => {
    const proto = window.location.protocol === "https:" ? "wss" : "ws";
    return `${proto}://${window.location.host}/ws/conversations/${conversationId}`;
  }, [conversationId]);

  useEffect(() => {
    setLivePayload(null);
    setStatus("connecting");
    const ws = new WebSocket(wsUrl);
    socketRef.current = ws;
    ws.onopen = () => setStatus("open");
    ws.onclose = () => setStatus("closed");
    ws.onerror = () => setStatus("closed");
    ws.onmessage = (message) => {
      const event = JSON.parse(message.data) as ServerEvent;
      setLivePayload((current) => reduceEvent(current, event));
    };
    return () => {
      ws.close();
      if (socketRef.current === ws) {
        socketRef.current = null;
      }
    };
  }, [wsUrl]);

  const sendMessage = useCallback((content: string) => {
    setLivePayload(initialPayload(content));
    socketRef.current?.send(
      JSON.stringify({
        type: "user_message",
        content,
        client_msg_id: crypto.randomUUID()
      })
    );
  }, []);

  const cancel = useCallback(() => {
    socketRef.current?.send(JSON.stringify({ type: "cancel" }));
  }, []);

  return { status, livePayload, sendMessage, cancel };
}
