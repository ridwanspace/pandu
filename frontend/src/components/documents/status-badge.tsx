"use client";

import { Badge } from "@/components/ui/badge";
import type { DocumentStatus } from "@/lib/api/types";
import { cn } from "@/lib/utils";

const STATUS_STYLES: Record<DocumentStatus, { label: string; dot: string; pulse?: boolean }> = {
  queued: { label: "Queued", dot: "bg-muted-foreground" },
  parsing: { label: "Parsing", dot: "bg-blue-500", pulse: true },
  embedding: { label: "Embedding", dot: "bg-blue-500", pulse: true },
  ready: { label: "Ready", dot: "bg-emerald-500" },
  failed: { label: "Failed", dot: "bg-red-500" },
};

export function StatusBadge({ status }: { status: DocumentStatus }) {
  const style = STATUS_STYLES[status] ?? { label: status, dot: "bg-muted-foreground" };
  return (
    <Badge variant="outline" className="gap-1.5 font-normal">
      <span
        className={cn("size-1.5 rounded-full", style.dot, style.pulse && "animate-pulse")}
        aria-hidden
      />
      {style.label}
    </Badge>
  );
}
