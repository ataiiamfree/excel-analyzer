import type { Artifact, Conversation, ConversationList, Message, TablePreview } from "./types";

export const MAX_UPLOAD_SIZE = 100 * 1024 * 1024;

export class ApiError extends Error {
  status: number;

  constructor(message: string, status: number) {
    super(message);
    this.name = "ApiError";
    this.status = status;
  }
}

async function responseError(response: Response): Promise<ApiError> {
  let message = `${response.status} ${response.statusText}`;
  const text = await response.text().catch(() => "");
  try {
    const payload = JSON.parse(text) as { detail?: unknown };
    if (typeof payload.detail === "string") {
      message = payload.detail;
    }
  } catch {
    if (text.trim()) message = text.trim();
  }
  if (response.status >= 500) {
    message = "服务器暂时不可用，请稍后重试";
  }
  return new ApiError(message, response.status);
}

async function json<T>(input: RequestInfo | URL, init?: RequestInit): Promise<T> {
  const response = await fetch(input, init);
  if (!response.ok) {
    throw await responseError(response);
  }
  return response.json() as Promise<T>;
}

export function validateExcelFile(file: File): void {
  const extension = file.name.toLowerCase().split(".").pop();
  if (extension !== "xlsx" && extension !== "xlsm") {
    throw new ApiError("目前请上传 .xlsx 或 .xlsm 文件", 415);
  }
  if (file.size > MAX_UPLOAD_SIZE) {
    throw new ApiError("文件超过 100MB 上限", 413);
  }
}

export async function fetchConversations(): Promise<ConversationList> {
  return json<ConversationList>("/api/conversations");
}

export async function fetchConversation(id: string): Promise<Conversation> {
  return json<Conversation>(`/api/conversations/${id}`);
}

export async function fetchMessages(id: string): Promise<Message[]> {
  return json<Message[]>(`/api/conversations/${id}/messages`);
}

export async function fetchArtifacts(id: string): Promise<Artifact[]> {
  return json<Artifact[]>(`/api/conversations/${id}/artifacts`);
}

export async function fetchTablePreview(url: string): Promise<TablePreview> {
  return json<TablePreview>(url);
}

export async function createConversation(file: File, query?: string): Promise<Conversation> {
  validateExcelFile(file);
  const form = new FormData();
  form.append("file", file);
  if (query) {
    form.append("query", query);
  }
  return json<Conversation>("/api/conversations", {
    method: "POST",
    body: form
  });
}

export async function replaceConversationFile(id: string, file: File): Promise<Conversation> {
  validateExcelFile(file);
  const form = new FormData();
  form.append("file", file);
  return json<Conversation>(`/api/conversations/${id}/files`, {
    method: "POST",
    body: form
  });
}

export async function updateConversation(id: string, payload: Partial<Pick<Conversation, "title" | "starred">>) {
  return json<Conversation>(`/api/conversations/${id}`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload)
  });
}

export async function deleteConversation(id: string): Promise<void> {
  const response = await fetch(`/api/conversations/${id}`, { method: "DELETE" });
  if (!response.ok) {
    throw await responseError(response);
  }
}
