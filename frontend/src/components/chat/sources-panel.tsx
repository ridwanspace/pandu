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
    <aside data-testid="sources-panel" className="flex w-80 shrink-0 flex-col max-lg:hidden">
      <div className="flex h-10 shrink-0 items-center justify-between px-2.5">
        <h2 className="text-sm font-semibold text-chrome-foreground">Sources</h2>
        {citations.length > 0 ? (
          <span className="text-xs text-chrome-muted">{citations.length} retrieved</span>
        ) : null}
      </div>
      <ScrollArea className="min-h-0 flex-1">
        {citations.length === 0 ? (
          <p className="px-2.5 py-3 text-sm leading-6 text-chrome-muted">
            Retrieved chunks for the latest answer appear here, with the ones the model actually
            cited marked.
          </p>
        ) : (
          <ul className="space-y-2 px-1 pb-1">
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
                      "w-full rounded-xl border bg-chrome-elevated/70 p-3 text-left transition-colors",
                      activeMarker === citation.marker
                        ? "border-primary bg-chrome-elevated"
                        : "border-transparent hover:border-chrome-border hover:bg-chrome-elevated",
                    )}
                  >
                    <div className="flex items-center gap-2">
                      <span
                        className={cn(
                          "flex size-5 shrink-0 items-center justify-center rounded-md font-mono text-xs",
                          cited
                            ? "brand-gradient text-white"
                            : "bg-white/10 text-chrome-foreground",
                        )}
                      >
                        {citation.marker}
                      </span>
                      <span className="truncate text-sm font-medium text-chrome-foreground">
                        {citation.filename}
                      </span>
                      {citedMarkers ? (
                        <Badge
                          variant={cited ? "default" : "outline"}
                          className={cn(
                            "ml-auto shrink-0",
                            !cited && "border-chrome-border text-chrome-muted",
                          )}
                        >
                          {cited ? "Cited" : "Retrieved"}
                        </Badge>
                      ) : null}
                    </div>
                    {citation.heading_path.length > 0 ? (
                      <p className="mt-1 truncate text-xs text-chrome-muted">
                        {citation.heading_path.join(" › ")}
                      </p>
                    ) : null}
                    <p className="mt-2 line-clamp-3 text-xs leading-5 text-chrome-muted">
                      {citation.snippet}
                    </p>
                    <p className="mt-2 font-mono text-[0.65rem] text-chrome-muted">
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
