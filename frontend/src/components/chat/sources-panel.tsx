"use client";

import { useEffect, useRef } from "react";
import { Badge } from "@/components/ui/badge";
import { ScrollArea } from "@/components/ui/scroll-area";
import type { CitationOut } from "@/lib/api/types";
import { cn } from "@/lib/utils";

interface SourcesPanelProps {
  citations: CitationOut[];
  /**
   * Markers referenced inline by the finished answer. `null` while the answer
   * is still streaming — the cited/retrieved split is only meaningful after
   * the `done` event.
   */
  citedMarkers: ReadonlySet<number> | null;
  activeMarker: number | null;
  onSelect: (marker: number | null) => void;
}

/** Retrieved contexts for the latest answer, cited vs merely retrieved. */
export function SourcesPanel({
  citations,
  citedMarkers,
  activeMarker,
  onSelect,
}: SourcesPanelProps) {
  const itemRefs = useRef<Map<number, HTMLLIElement>>(new Map());

  useEffect(() => {
    if (activeMarker == null) return;
    itemRefs.current.get(activeMarker)?.scrollIntoView({ block: "nearest", behavior: "smooth" });
  }, [activeMarker]);

  return (
    <aside
      data-testid="sources-panel"
      className="flex w-80 shrink-0 flex-col border-l bg-sidebar max-lg:hidden"
    >
      <div className="flex h-11 items-center justify-between border-b px-4">
        <h2 className="text-sm font-semibold">Sources</h2>
        {citations.length > 0 ? (
          <span className="text-xs text-muted-foreground">{citations.length} retrieved</span>
        ) : null}
      </div>
      <ScrollArea className="flex-1">
        {citations.length === 0 ? (
          <p className="p-4 text-sm text-muted-foreground">
            Retrieved chunks for the latest answer appear here, with the ones the model actually
            cited marked.
          </p>
        ) : (
          <ul className="space-y-2 p-3">
            {citations.map((citation) => {
              const cited = citedMarkers?.has(citation.marker) ?? false;
              return (
                <li
                  key={citation.marker}
                  ref={(el) => {
                    if (el) itemRefs.current.set(citation.marker, el);
                    else itemRefs.current.delete(citation.marker);
                  }}
                >
                  <button
                    type="button"
                    onClick={() =>
                      onSelect(activeMarker === citation.marker ? null : citation.marker)
                    }
                    className={cn(
                      "w-full rounded-md border bg-card p-3 text-left transition-colors",
                      activeMarker === citation.marker
                        ? "border-primary"
                        : "border-border hover:border-primary/40",
                    )}
                  >
                    <div className="flex items-center gap-2">
                      <span className="flex size-5 shrink-0 items-center justify-center rounded-sm bg-secondary font-mono text-xs">
                        {citation.marker}
                      </span>
                      <span className="truncate text-sm font-medium">{citation.filename}</span>
                      {citedMarkers ? (
                        <Badge variant={cited ? "default" : "outline"} className="ml-auto shrink-0">
                          {cited ? "Cited" : "Retrieved"}
                        </Badge>
                      ) : null}
                    </div>
                    {citation.heading_path.length > 0 ? (
                      <p className="mt-1 truncate text-xs text-muted-foreground">
                        {citation.heading_path.join(" › ")}
                      </p>
                    ) : null}
                    <p className="mt-2 line-clamp-3 text-xs leading-5 text-muted-foreground">
                      {citation.snippet}
                    </p>
                    <p className="mt-2 font-mono text-[0.65rem] text-muted-foreground">
                      score {citation.score.toFixed(3)}
                    </p>
                  </button>
                </li>
              );
            })}
          </ul>
        )}
      </ScrollArea>
    </aside>
  );
}
