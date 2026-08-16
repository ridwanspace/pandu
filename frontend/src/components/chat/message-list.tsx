"use client";

import { useEffect, useRef } from "react";
import { CitationText } from "@/components/chat/citation-text";
import { UsageFooter } from "@/components/chat/usage-footer";
import { Skeleton } from "@/components/ui/skeleton";
import type { MessageOut } from "@/lib/api/types";
import type { StreamState } from "@/lib/hooks/use-chat-stream";
import { cn } from "@/lib/utils";

interface MessageListProps {
  messages: MessageOut[];
  stream: StreamState | null;
  isLoading: boolean;
  activeMarker: number | null;
  onMarkerClick: (marker: number) => void;
}

function UserBubble({ content }: { content: string }) {
  return (
    <div className="flex justify-end">
      <div className="max-w-[85%] rounded-lg bg-primary px-3.5 py-2.5 text-sm text-primary-foreground">
        <span className="whitespace-pre-wrap break-words">{content}</span>
      </div>
    </div>
  );
}

export function MessageList({
  messages,
  stream,
  isLoading,
  activeMarker,
  onMarkerClick,
}: MessageListProps) {
  const bottomRef = useRef<HTMLDivElement>(null);
  const streamContentLength = stream?.content.length ?? 0;

  // Follow the stream / new messages.
  // biome-ignore lint/correctness/useExhaustiveDependencies: scroll on content growth, not on dep identity
  useEffect(() => {
    bottomRef.current?.scrollIntoView({ block: "end" });
  }, [messages.length, streamContentLength]);

  if (isLoading) {
    return (
      <div className="mx-auto w-full max-w-3xl space-y-4 p-6">
        <Skeleton className="ml-auto h-10 w-2/5" />
        <Skeleton className="h-24 w-full" />
        <Skeleton className="ml-auto h-10 w-1/3" />
        <Skeleton className="h-24 w-full" />
      </div>
    );
  }

  if (messages.length === 0 && !stream) {
    return (
      <div className="flex flex-1 items-center justify-center p-6">
        <div className="max-w-sm text-center">
          <p className="text-sm font-medium">Ask your corpus a question</p>
          <p className="mt-1 text-sm text-muted-foreground">
            Answers stream in with inline [n] citations you can trace back to the exact chunk.
          </p>
        </div>
      </div>
    );
  }

  return (
    <div className="mx-auto w-full max-w-3xl space-y-6 p-6">
      {messages.map((message) =>
        message.role === "user" ? (
          <UserBubble key={message.id} content={message.content} />
        ) : (
          <div key={message.id} data-testid="assistant-message" className="text-sm leading-6">
            <CitationText
              text={message.content}
              validMarkers={new Set(message.citations.map((c) => c.marker))}
              activeMarker={activeMarker}
              onMarkerClick={onMarkerClick}
            />
            <UsageFooter
              model={message.model}
              promptTokens={message.prompt_tokens}
              completionTokens={message.completion_tokens}
              costUsd={message.cost_usd}
              latencyMs={message.latency_ms}
            />
          </div>
        ),
      )}

      {stream ? (
        <>
          <UserBubble content={stream.question} />
          <div data-testid="assistant-message" className="text-sm leading-6" aria-live="polite">
            {stream.content ? (
              <CitationText
                text={stream.content}
                validMarkers={new Set(stream.citations.map((c) => c.marker))}
                activeMarker={activeMarker}
                onMarkerClick={onMarkerClick}
              />
            ) : (
              <span className="text-muted-foreground">
                {stream.citations.length > 0 ? "Generating answer…" : "Retrieving sources…"}
              </span>
            )}
            <span
              className={cn(
                "ml-0.5 inline-block h-4 w-2 translate-y-0.5 animate-pulse bg-foreground/70",
                stream.phase === "finalizing" && "hidden",
              )}
              aria-hidden
            />
            {stream.usage ? (
              <UsageFooter
                model={stream.usage.model}
                promptTokens={stream.usage.prompt_tokens}
                completionTokens={stream.usage.completion_tokens}
                costUsd={stream.usage.cost_usd}
                latencyMs={stream.usage.latency_ms}
              />
            ) : null}
          </div>
        </>
      ) : null}
      <div ref={bottomRef} />
    </div>
  );
}
