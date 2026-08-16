"use client";

import { cn } from "@/lib/utils";

export type CitationSegment =
  | { type: "text"; value: string }
  | { type: "citation"; marker: number };

const MARKER_RE = /\[(\d+)\]/g;

/** Split answer text into plain-text runs and `[n]` citation markers. */
export function splitCitationSegments(text: string): CitationSegment[] {
  const segments: CitationSegment[] = [];
  let last = 0;
  for (const match of text.matchAll(MARKER_RE)) {
    const index = match.index;
    if (index > last) segments.push({ type: "text", value: text.slice(last, index) });
    segments.push({ type: "citation", marker: Number(match[1]) });
    last = index + match[0].length;
  }
  if (last < text.length) segments.push({ type: "text", value: text.slice(last) });
  return segments;
}

/** Markers actually referenced in the answer text (the "cited" set). */
export function citedMarkers(text: string): Set<number> {
  const markers = new Set<number>();
  for (const match of text.matchAll(MARKER_RE)) markers.add(Number(match[1]));
  return markers;
}

export interface CitationTextProps {
  text: string;
  /**
   * Markers that map to a known citation. Markers outside this set render as
   * literal text. Omit to treat every `[n]` as clickable.
   */
  validMarkers?: ReadonlySet<number>;
  activeMarker?: number | null;
  onMarkerClick?: (marker: number) => void;
}

/**
 * Renders assistant text with inline `[n]` citations as clickable superscript
 * chips that highlight the matching entry in the sources panel.
 */
export function CitationText({
  text,
  validMarkers,
  activeMarker,
  onMarkerClick,
}: CitationTextProps) {
  const segments = splitCitationSegments(text);

  return (
    <span className="whitespace-pre-wrap break-words">
      {segments.map((segment, i) => {
        if (segment.type === "text") {
          // biome-ignore lint/suspicious/noArrayIndexKey: segments are positional and static per render
          return <span key={i}>{segment.value}</span>;
        }
        const { marker } = segment;
        if (validMarkers && !validMarkers.has(marker)) {
          // biome-ignore lint/suspicious/noArrayIndexKey: segments are positional and static per render
          return <span key={i}>{`[${marker}]`}</span>;
        }
        return (
          // biome-ignore lint/suspicious/noArrayIndexKey: segments are positional and static per render
          <sup key={i} className="mx-px">
            <button
              type="button"
              data-testid="citation-chip"
              aria-label={`Source ${marker}`}
              onClick={() => onMarkerClick?.(marker)}
              className={cn(
                "inline-flex min-w-4 items-center justify-center rounded-sm border px-1 font-mono text-[0.65rem] leading-4 transition-colors",
                activeMarker === marker
                  ? "border-primary bg-primary text-primary-foreground"
                  : "border-border bg-secondary text-secondary-foreground hover:border-primary/50",
              )}
            >
              {marker}
            </button>
          </sup>
        );
      })}
    </span>
  );
}
