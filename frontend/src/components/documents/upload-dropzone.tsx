"use client";

import { useMutation, useQueryClient } from "@tanstack/react-query";
import { UploadIcon } from "lucide-react";
import { useRef, useState } from "react";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { uploadDocument } from "@/lib/api/documents";
import { cn } from "@/lib/utils";

export function UploadDropzone() {
  const queryClient = useQueryClient();
  const inputRef = useRef<HTMLInputElement>(null);
  const [dragging, setDragging] = useState(false);

  const upload = useMutation({
    mutationFn: uploadDocument,
    onSuccess: (doc) => {
      toast.success(`Uploaded ${doc.filename}`, { description: "Ingestion queued." });
      queryClient.invalidateQueries({ queryKey: ["documents"] });
    },
    onError: (err, file) =>
      toast.error(`Upload failed for ${file.name}`, {
        description: err instanceof Error ? err.message : undefined,
      }),
  });

  const handleFiles = (files: FileList | null) => {
    if (!files) return;
    for (const file of Array.from(files)) upload.mutate(file);
  };

  return (
    // biome-ignore lint/a11y/noNoninteractiveElementInteractions: drag-and-drop is a pointer-only enhancement; the keyboard-accessible path is the browse button + file input below
    <section
      aria-label="Upload documents"
      onDragOver={(e) => {
        e.preventDefault();
        setDragging(true);
      }}
      onDragLeave={() => setDragging(false)}
      onDrop={(e) => {
        e.preventDefault();
        setDragging(false);
        handleFiles(e.dataTransfer.files);
      }}
      className={cn(
        "flex flex-col items-center justify-center gap-2 rounded-lg border border-dashed p-8 text-center transition-colors",
        dragging ? "border-primary bg-primary/5" : "border-border",
      )}
    >
      <UploadIcon className="size-5 text-muted-foreground" aria-hidden />
      <p className="text-sm">
        Drag and drop files here, or
        <Button
          type="button"
          variant="link"
          className="h-auto px-1"
          disabled={upload.isPending}
          onClick={() => inputRef.current?.click()}
        >
          browse
        </Button>
      </p>
      <p className="text-xs text-muted-foreground">
        PDF, Markdown or text. Files are parsed, chunked and embedded in the background.
      </p>
      <input
        ref={inputRef}
        data-testid="file-input"
        type="file"
        multiple
        className="sr-only"
        aria-label="Choose files to upload"
        onChange={(e) => {
          handleFiles(e.target.files);
          e.target.value = "";
        }}
      />
    </section>
  );
}
