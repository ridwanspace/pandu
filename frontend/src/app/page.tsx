"use client";

import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useCallback, useEffect, useMemo, useState } from "react";
import { ChatInput } from "@/components/chat/chat-input";
import { citedMarkers } from "@/components/chat/citation-text";
import { ConversationSidebar } from "@/components/chat/conversation-sidebar";
import { MessageList } from "@/components/chat/message-list";
import { SourcesPanel } from "@/components/chat/sources-panel";
import { createConversation, listConversations, listMessages } from "@/lib/api/conversations";
import type { UUID } from "@/lib/api/types";
import { useChatStream } from "@/lib/hooks/use-chat-stream";

export default function ChatPage() {
  const queryClient = useQueryClient();
  const [conversationId, setConversationId] = useState<UUID | null>(null);
  const [activeMarker, setActiveMarker] = useState<number | null>(null);

  const conversations = useQuery({ queryKey: ["conversations"], queryFn: listConversations });

  // Land in the most recent conversation instead of an empty pane.
  useEffect(() => {
    if (conversationId === null && conversations.data && conversations.data.items.length > 0) {
      setConversationId(conversations.data.items[0].id);
    }
  }, [conversationId, conversations.data]);

  const messages = useQuery({
    queryKey: ["messages", conversationId],
    queryFn: () => listMessages(conversationId as UUID),
    enabled: conversationId !== null,
  });

  const { stream, isStreaming, send } = useChatStream();

  const selectConversation = useCallback((id: UUID) => {
    setConversationId(id);
    setActiveMarker(null);
  }, []);

  const handleSend = useCallback(
    async (question: string): Promise<boolean> => {
      setActiveMarker(null);
      let id = conversationId;
      if (id === null) {
        try {
          const conversation = await createConversation();
          id = conversation.id;
          setConversationId(id);
          await queryClient.invalidateQueries({ queryKey: ["conversations"] });
        } catch {
          return false;
        }
      }
      return send(id, question);
    },
    [conversationId, queryClient, send],
  );

  const items = messages.data?.items ?? [];
  const lastAssistant = useMemo(
    () => [...items].reverse().find((m) => m.role === "assistant") ?? null,
    [items],
  );

  // Sources for the in-flight answer, else for the latest persisted one.
  const citations = stream ? stream.citations : (lastAssistant?.citations ?? []);
  // Cited-vs-retrieved is only decidable once the answer is complete.
  const cited = useMemo(() => {
    if (stream) return stream.phase === "finalizing" ? citedMarkers(stream.content) : null;
    return lastAssistant ? citedMarkers(lastAssistant.content) : null;
  }, [stream, lastAssistant]);

  return (
    <div className="flex h-[calc(100dvh-3.5rem)] overflow-hidden">
      <ConversationSidebar selectedId={conversationId} onSelect={selectConversation} />
      <section className="flex min-w-0 flex-1 flex-col">
        <div className="flex-1 overflow-y-auto">
          <MessageList
            messages={items}
            stream={stream}
            isLoading={conversationId !== null && messages.isPending}
            activeMarker={activeMarker}
            onMarkerClick={(marker) => setActiveMarker(marker)}
          />
        </div>
        <ChatInput disabled={isStreaming} onSend={handleSend} />
      </section>
      <SourcesPanel
        citations={citations}
        citedMarkers={cited}
        activeMarker={activeMarker}
        onSelect={setActiveMarker}
      />
    </div>
  );
}
