"use client";

import { useQuery } from "@tanstack/react-query";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { ScrollArea } from "@/components/ui/scroll-area";
import { Skeleton } from "@/components/ui/skeleton";
import { listChunks } from "@/lib/api/documents";
import type { DocumentOut } from "@/lib/api/types";

interface ChunkInspectorDialogProps {
  document: DocumentOut | null;
  onClose: () => void;
}

/** Read-only view of a document's chunks: heading path, tokens, text. */
export function ChunkInspectorDialog({ document, onClose }: ChunkInspectorDialogProps) {
  const { data, isPending, isError } = useQuery({
    queryKey: ["chunks", document?.id],
    queryFn: () => listChunks(document?.id ?? "", 50),
    enabled: document !== null,
  });

  return (
    <Dialog open={document !== null} onOpenChange={(open) => !open && onClose()}>
      <DialogContent className="flex max-h-[85dvh] flex-col sm:max-w-2xl">
        <DialogHeader>
          <DialogTitle className="truncate">{document?.filename}</DialogTitle>
          <DialogDescription>
            {document
              ? `${document.chunk_count} chunks · first ${Math.min(50, document.chunk_count)} shown`
              : ""}
          </DialogDescription>
        </DialogHeader>
        <ScrollArea className="min-h-0 flex-1 pr-3">
          {isPending ? (
            <div className="space-y-3">
              <Skeleton className="h-24 w-full" />
              <Skeleton className="h-24 w-full" />
              <Skeleton className="h-24 w-full" />
            </div>
          ) : isError ? (
            <p className="text-sm text-muted-foreground">Could not load chunks.</p>
          ) : data.items.length === 0 ? (
            <p className="text-sm text-muted-foreground">No chunks yet.</p>
          ) : (
            <ol className="space-y-3">
              {data.items.map((chunk) => (
                <li key={chunk.seq} className="rounded-md border bg-card p-3">
                  <div className="flex items-center gap-2 font-mono text-xs text-muted-foreground">
                    <span>#{chunk.seq}</span>
                    <span>{chunk.token_count} tok</span>
                    {chunk.heading_path.length > 0 ? (
                      <span className="truncate">{chunk.heading_path.join(" › ")}</span>
                    ) : null}
                  </div>
                  <p className="mt-2 whitespace-pre-wrap break-words font-mono text-xs leading-5">
                    {chunk.text}
                  </p>
                </li>
              ))}
            </ol>
          )}
        </ScrollArea>
      </DialogContent>
    </Dialog>
  );
}
