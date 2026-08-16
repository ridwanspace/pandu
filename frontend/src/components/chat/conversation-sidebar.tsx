"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { PlusIcon } from "lucide-react";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { ScrollArea } from "@/components/ui/scroll-area";
import { Skeleton } from "@/components/ui/skeleton";
import { createConversation, listConversations } from "@/lib/api/conversations";
import type { UUID } from "@/lib/api/types";
import { formatDateTime } from "@/lib/format";
import { cn } from "@/lib/utils";

interface ConversationSidebarProps {
  selectedId: UUID | null;
  onSelect: (id: UUID) => void;
}

export function ConversationSidebar({ selectedId, onSelect }: ConversationSidebarProps) {
  const queryClient = useQueryClient();
  const { data, isPending, isError } = useQuery({
    queryKey: ["conversations"],
    queryFn: listConversations,
  });

  const create = useMutation({
    mutationFn: () => createConversation(),
    onSuccess: async (conversation) => {
      await queryClient.invalidateQueries({ queryKey: ["conversations"] });
      onSelect(conversation.id);
    },
    onError: (err) =>
      toast.error("Could not create conversation", {
        description: err instanceof Error ? err.message : undefined,
      }),
  });

  return (
    <aside className="flex w-56 shrink-0 flex-col border-r border-border/70 bg-sidebar max-md:hidden">
      <div className="p-3">
        <Button
          className="w-full"
          size="sm"
          onClick={() => create.mutate()}
          disabled={create.isPending}
          data-testid="new-chat"
        >
          <PlusIcon className="size-4" aria-hidden />
          New chat
        </Button>
      </div>
      <ScrollArea className="flex-1 px-3 pb-3">
        {isPending ? (
          <div className="space-y-2">
            <Skeleton className="h-12 w-full" />
            <Skeleton className="h-12 w-full" />
            <Skeleton className="h-12 w-full" />
          </div>
        ) : isError ? (
          <p className="px-1 text-xs text-muted-foreground">
            Could not load conversations. Check the API connection in Settings.
          </p>
        ) : data.items.length === 0 ? (
          <p className="px-1 text-xs text-muted-foreground">
            No conversations yet. Start a new chat to ask your corpus a question.
          </p>
        ) : (
          <ul className="space-y-1">
            {data.items.map((c) => (
              <li key={c.id}>
                <button
                  type="button"
                  onClick={() => onSelect(c.id)}
                  className={cn(
                    "w-full rounded-xl px-2.5 py-2 text-left transition-colors",
                    selectedId === c.id
                      ? "bg-sidebar-accent text-sidebar-accent-foreground"
                      : "hover:bg-sidebar-accent/60",
                  )}
                >
                  <span className="block truncate text-sm font-medium">
                    {c.title ?? "Untitled conversation"}
                  </span>
                  <span className="block text-xs text-muted-foreground">
                    {formatDateTime(c.created_at)}
                  </span>
                </button>
              </li>
            ))}
          </ul>
        )}
      </ScrollArea>
    </aside>
  );
}
