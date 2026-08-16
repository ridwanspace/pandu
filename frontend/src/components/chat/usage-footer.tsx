"use client";

import { formatLatency, formatUsd } from "@/lib/format";

interface UsageFooterProps {
  model: string | null;
  promptTokens: number | null;
  completionTokens: number | null;
  costUsd: string | null;
  latencyMs: number | null;
}

/** Per-answer telemetry row: model, token split, cost and latency. */
export function UsageFooter({
  model,
  promptTokens,
  completionTokens,
  costUsd,
  latencyMs,
}: UsageFooterProps) {
  if (!model && promptTokens == null && costUsd == null) return null;

  return (
    <div
      data-testid="usage-footer"
      className="mt-2 flex flex-wrap items-center gap-x-3 gap-y-1 font-mono text-xs text-muted-foreground"
    >
      {model ? <span>{model}</span> : null}
      {promptTokens != null || completionTokens != null ? (
        <span>
          {promptTokens ?? 0}
          {" → "}
          {completionTokens ?? 0} tok
        </span>
      ) : null}
      {costUsd != null ? <span>{formatUsd(costUsd)}</span> : null}
      {latencyMs != null ? <span>{formatLatency(latencyMs)}</span> : null}
    </div>
  );
}
