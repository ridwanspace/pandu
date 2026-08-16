"use client";

import { SendHorizonalIcon } from "lucide-react";
import { useRef, useState } from "react";
import { Button } from "@/components/ui/button";
import { Textarea } from "@/components/ui/textarea";

interface ChatInputProps {
  disabled: boolean;
  /** Returns false when sending failed, so the draft is restored. */
  onSend: (question: string) => Promise<boolean>;
}

export function ChatInput({ disabled, onSend }: ChatInputProps) {
  const [value, setValue] = useState("");
  const textareaRef = useRef<HTMLTextAreaElement>(null);

  const submit = async () => {
    const question = value.trim();
    if (!question || disabled) return;
    setValue("");
    const ok = await onSend(question);
    if (!ok) setValue(question);
    textareaRef.current?.focus();
  };

  return (
    <form
      className="border-t bg-background p-4"
      onSubmit={(e) => {
        e.preventDefault();
        void submit();
      }}
    >
      <div className="mx-auto flex max-w-3xl items-end gap-2">
        <Textarea
          ref={textareaRef}
          data-testid="chat-input"
          value={value}
          onChange={(e) => setValue(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter" && !e.shiftKey) {
              e.preventDefault();
              void submit();
            }
          }}
          placeholder="Ask a question about your documents…"
          rows={2}
          className="max-h-40 min-h-9 flex-1 resize-none"
          disabled={disabled}
        />
        <Button
          type="submit"
          size="icon"
          data-testid="send-button"
          disabled={disabled || value.trim().length === 0}
          aria-label="Send question"
        >
          <SendHorizonalIcon className="size-4" aria-hidden />
        </Button>
      </div>
      <p className="mx-auto mt-1.5 max-w-3xl text-xs text-muted-foreground">
        Enter to send · Shift+Enter for a new line
      </p>
    </form>
  );
}
