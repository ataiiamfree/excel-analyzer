export type RunStatus = "running" | "done" | "failed" | "cancelled";
export type ArtifactKind = "chart" | "excel" | "csv" | "report" | "file" | "data" | "normalized_table";

export interface Conversation {
  id: string;
  title: string;
  file_name?: string | null;
  file_size?: number | null;
  sheet_count?: number | null;
  row_count?: number | null;
  created_at: string;
  updated_at: string;
  starred: boolean;
  archived_at?: string | null;
}

export interface ConversationGroup {
  label: string;
  conversations: Conversation[];
}

export interface ConversationList {
  groups: ConversationGroup[];
}

export interface Message {
  id: string;
  conversation_id: string;
  role: "user" | "assistant";
  created_at: string;
  payload: UserMessagePayload | AssistantMessagePayload;
}

export interface UserMessagePayload {
  text: string;
  client_msg_id?: string | null;
  attached_file?: {
    name?: string | null;
    size?: number | null;
  } | null;
}

export interface PlanStep {
  id: string;
  tool: string;
  description: string;
  instruction: string;
  depends_on: string[];
  is_exploratory: boolean;
}

export interface StepRecord {
  step_id: string;
  status: "pending" | "running" | "done" | "failed";
  started_at?: string;
  ended_at?: string;
  stdout?: string;
  error?: string;
  script_path?: string;
  artifact_ids: string[];
}

export interface AssistantMessagePayload {
  status: RunStatus;
  query: string;
  plan: { steps: PlanStep[] };
  reasoning?: { text: string; tokens: number } | null;
  steps: StepRecord[];
  report: string;
  next_actions: string[];
  artifact_ids: string[];
  metrics: Record<string, unknown>;
  error?: { failed_step_description: string; summary: string } | null;
}

export interface Artifact {
  id: string;
  conversation_id?: string | null;
  message_id?: string | null;
  kind: ArtifactKind;
  name: string;
  size: number;
  created_at: string;
  url: string;
  preview_url?: string | null;
  sha256_url?: string | null;
  sha256?: string | null;
  description?: string | null;
  producer_step_id?: string | null;
  producer_tool?: string | null;
  input_artifact_ids?: string[];
  source_tables?: string[];
  script_path?: string | null;
  stdout_summary?: string | null;
  row_count?: number | null;
  chart_metadata?: Record<string, unknown>;
}

export interface TablePreview {
  columns: string[];
  rows: Record<string, unknown>[];
  row_count: number;
}

export type ServerEvent =
  | { type: "run.start"; seq: number; ts: string; message_id: string }
  | { type: "plan.ready"; seq: number; ts: string; steps: PlanStep[] }
  | {
      type: "step.start";
      seq: number;
      ts: string;
      step_id: string;
      index: number;
      total: number;
      description: string;
      tool: string;
      instruction: string;
    }
  | { type: "reasoning.delta"; seq: number; ts: string; delta: string; step_id?: string | null }
  | {
      type: "step.end";
      seq: number;
      ts: string;
      step_id: string;
      status: "done" | "failed";
      stdout: string;
      error: string;
      files: string[];
      script_path?: string | null;
      duration_ms?: number | null;
    }
  | { type: "report.delta"; seq: number; ts: string; delta: string }
  | {
      type: "artifact.created";
      seq: number;
      ts: string;
      artifact_id: string;
      name: string;
      kind: ArtifactKind;
      size: number;
      message_id: string;
    }
  | {
      type: "run.complete";
      seq: number;
      ts: string;
      message_id: string;
      report: string;
      file_ids: string[];
      duration_ms: number;
      result?: AssistantMessagePayload & { artifacts?: Artifact[] };
    }
  | { type: "run.failed"; seq: number; ts: string; failed_step_description: string; error_summary: string }
  | { type: "cancelled"; seq: number; ts: string };
