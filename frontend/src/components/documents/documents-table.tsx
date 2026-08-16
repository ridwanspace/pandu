"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { SearchIcon, Trash2Icon } from "lucide-react";
import { useState } from "react";
import { toast } from "sonner";
import { ChunkInspectorDialog } from "@/components/documents/chunk-inspector-dialog";
import { StatusBadge } from "@/components/documents/status-badge";
import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
} from "@/components/ui/alert-dialog";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { deleteDocument, listDocuments } from "@/lib/api/documents";
import { ACTIVE_DOCUMENT_STATUSES, type DocumentOut } from "@/lib/api/types";
import { formatBytes, formatDateTime } from "@/lib/format";

export function DocumentsTable() {
  const queryClient = useQueryClient();
  const [inspecting, setInspecting] = useState<DocumentOut | null>(null);
  const [deleting, setDeleting] = useState<DocumentOut | null>(null);

  const { data, isPending, isError } = useQuery({
    queryKey: ["documents"],
    queryFn: listDocuments,
    // Poll while any document is still being ingested.
    refetchInterval: (query) =>
      query.state.data?.items.some((d) => ACTIVE_DOCUMENT_STATUSES.includes(d.status))
        ? 2500
        : false,
  });

  const remove = useMutation({
    mutationFn: deleteDocument,
    onSuccess: () => {
      toast.success("Document deleted");
      queryClient.invalidateQueries({ queryKey: ["documents"] });
    },
    onError: (err) =>
      toast.error("Delete failed", {
        description: err instanceof Error ? err.message : undefined,
      }),
    onSettled: () => setDeleting(null),
  });

  if (isPending) {
    return (
      <div className="space-y-2">
        <Skeleton className="h-10 w-full" />
        <Skeleton className="h-10 w-full" />
        <Skeleton className="h-10 w-full" />
      </div>
    );
  }

  if (isError) {
    return (
      <p className="rounded-lg border border-dashed p-8 text-center text-sm text-muted-foreground">
        Could not load documents. Check the API connection in Settings.
      </p>
    );
  }

  if (data.items.length === 0) {
    return (
      <p className="rounded-lg border border-dashed p-8 text-center text-sm text-muted-foreground">
        No documents yet. Upload one above to build your corpus.
      </p>
    );
  }

  return (
    <>
      <div className="overflow-x-auto rounded-lg border">
        <Table data-testid="documents-table">
          <TableHeader>
            <TableRow>
              <TableHead>File</TableHead>
              <TableHead>Status</TableHead>
              <TableHead className="text-right">Size</TableHead>
              <TableHead className="text-right">Chunks</TableHead>
              <TableHead>Updated</TableHead>
              <TableHead className="w-24 text-right">Actions</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {data.items.map((doc) => (
              <TableRow key={doc.id}>
                <TableCell className="max-w-64">
                  <span className="block truncate font-medium">{doc.filename}</span>
                  {doc.status === "failed" && doc.error ? (
                    <span className="block truncate text-xs text-destructive">{doc.error}</span>
                  ) : null}
                </TableCell>
                <TableCell>
                  <StatusBadge status={doc.status} />
                </TableCell>
                <TableCell className="text-right font-mono text-xs tabular-nums">
                  {formatBytes(doc.size_bytes)}
                </TableCell>
                <TableCell className="text-right font-mono text-xs tabular-nums">
                  {doc.chunk_count}
                </TableCell>
                <TableCell className="text-xs text-muted-foreground">
                  {formatDateTime(doc.updated_at)}
                </TableCell>
                <TableCell className="text-right">
                  <div className="flex justify-end gap-1">
                    <Button
                      variant="ghost"
                      size="icon"
                      aria-label={`Inspect chunks of ${doc.filename}`}
                      disabled={doc.chunk_count === 0}
                      onClick={() => setInspecting(doc)}
                    >
                      <SearchIcon className="size-4" aria-hidden />
                    </Button>
                    <Button
                      variant="ghost"
                      size="icon"
                      aria-label={`Delete ${doc.filename}`}
                      onClick={() => setDeleting(doc)}
                    >
                      <Trash2Icon className="size-4" aria-hidden />
                    </Button>
                  </div>
                </TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      </div>

      <ChunkInspectorDialog document={inspecting} onClose={() => setInspecting(null)} />

      <AlertDialog open={deleting !== null} onOpenChange={(open) => !open && setDeleting(null)}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>Delete {deleting?.filename}?</AlertDialogTitle>
            <AlertDialogDescription>
              This removes the document and all of its chunks from the index. Answers will no longer
              cite it.
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel>Cancel</AlertDialogCancel>
            <AlertDialogAction
              onClick={() => deleting && remove.mutate(deleting.id)}
              disabled={remove.isPending}
            >
              Delete
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </>
  );
}
