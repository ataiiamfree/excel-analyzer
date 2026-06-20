import type { Artifact, Conversation, ConversationList, Message, TablePreview } from "./types";

async function json<T>(input: RequestInfo | URL, init?: RequestInit): Promise<T> {
  const response = await fetch(input, init);
  if (!response.ok) {
    const text = await response.text();
    throw new Error(text || `${response.status} ${response.statusText}`);
  }
  return response.json() as Promise<T>;
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
    throw new Error(await response.text());
  }
}
