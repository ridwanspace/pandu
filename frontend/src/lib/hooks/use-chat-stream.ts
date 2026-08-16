"use client";

import { useQueryClient } from "@tanstack/react-query";
import { useCallback, useRef, useState } from "react";
import { toast } from "sonner";
import { streamAnswer } from "@/lib/api/conversations";
import type {
  CitationOut,
  DoneEventData,
  ErrorEventData,
  SourcesEventData,
  TokenEventData,
  UsageEventData,
  UUID,
} from "@/lib/api/types";
import { readSSE } from "@/lib/sse";

export interface StreamState {
  /** The question, rendered optimistically as a user message. */
  question: string;
  /** Assistant text accumulated so far. */
  content: string;
  /** Retrieved contexts from the `sources` event (marker = 1..k). */
  citations: CitationOut[];
  usage: UsageEventData | null;
  /** `finalizing` = `done` received, waiting for the messages refetch. */
  phase: "streaming" | "finalizing";
}

export interface UseChatStream {
  stream: StreamState | null;
  isStreaming: boolean;
  /** Returns true when the answer completed; false when it failed. */
  send: (conversationId: UUID, question: string) => Promise<boolean>;
}

/**
 * Drives one SSE answer stream at a time. On completion the messages query is
 * invalidated so the persisted assistant message (with citations) replaces the
 * transient stream state without a visual gap.
 */
export function useChatStream(): UseChatStream {
  const queryClient = useQueryClient();
  const [stream, setStream] = useState<StreamState | null>(null);
  const busy = useRef(false);

  const send = useCallback(
    async (conversationId: UUID, question: string): Promise<boolean> => {
      if (busy.current) return false;
      busy.current = true;
      setStream({ question, content: "", citations: [], usage: null, phase: "streaming" });

      try {
        const res = await streamAnswer(conversationId, { question });
        if (!res.body) throw new Error("Empty response body");
        let done = false;

        for await (const ev of readSSE(res.body)) {
          switch (ev.event) {
            case "sources": {
              const { citations } = JSON.parse(ev.data) as SourcesEventData;
              setStream((s) => (s ? { ...s, citations } : s));
              break;
            }
            case "token": {
              const { text } = JSON.parse(ev.data) as TokenEventData;
              setStream((s) => (s ? { ...s, content: s.content + text } : s));
              break;
            }
            case "usage": {
              const usage = JSON.parse(ev.data) as UsageEventData;
              setStream((s) => (s ? { ...s, usage } : s));
              break;
            }
            case "done": {
              JSON.parse(ev.data) as DoneEventData;
              done = true;
              setStream((s) => (s ? { ...s, phase: "finalizing" } : s));
              break;
            }
            case "error": {
              const { detail } = JSON.parse(ev.data) as ErrorEventData;
              throw new Error(detail);
            }
            default:
              break;
          }
        }
        if (!done) throw new Error("Stream ended before completion");

        await queryClient.invalidateQueries({ queryKey: ["messages", conversationId] });
        queryClient.invalidateQueries({ queryKey: ["conversations"] });
        return true;
      } catch (err) {
        toast.error("Answer failed", {
          description: err instanceof Error ? err.message : "Unexpected streaming error",
        });
        return false;
      } finally {
        setStream(null);
        busy.current = false;
      }
    },
    [queryClient],
  );

  return { stream, isStreaming: stream !== null, send };
}
