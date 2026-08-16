import { apiFetch, apiStream } from "@/lib/api/client";
import type {
  ConversationCreateIn,
  ConversationListOut,
  ConversationOut,
  MessageCreateIn,
  MessageListOut,
  UUID,
} from "@/lib/api/types";

export async function createConversation(
  input: ConversationCreateIn = {},
): Promise<ConversationOut> {
  return apiFetch<ConversationOut>("/conversations", { method: "POST", json: input });
}

export async function listConversations(): Promise<ConversationListOut> {
  return apiFetch<ConversationListOut>("/conversations");
}

export async function listMessages(conversationId: UUID): Promise<MessageListOut> {
  return apiFetch<MessageListOut>(`/conversations/${conversationId}/messages`);
}

/**
 * Ask a question; returns the raw SSE response. Events arrive in order:
 * `sources`, many `token`, `usage`, `done` — or `error` on failure.
 */
export async function streamAnswer(
  conversationId: UUID,
  input: MessageCreateIn,
): Promise<Response> {
  return apiStream(`/conversations/${conversationId}/messages`, input);
}
