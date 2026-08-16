"use client";

import { Badge } from "@/components/ui/badge";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import type { EvalRunOut } from "@/lib/api/types";
import { formatDateTime } from "@/lib/format";

function configSummary(config: Record<string, unknown>): string {
  const entries = Object.entries(config)
    .filter(([, v]) => ["string", "number", "boolean"].includes(typeof v))
    .slice(0, 4)
    .map(([k, v]) => `${k}=${String(v)}`);
  return entries.join(" · ");
}

export function EvalRunsTable({ runs }: { runs: EvalRunOut[] }) {
  if (runs.length === 0) {
    return (
      <p className="rounded-lg border border-dashed p-8 text-center text-sm text-muted-foreground">
        No eval runs recorded yet.
      </p>
    );
  }

  const ordered = [...runs].sort(
    (a, b) => new Date(b.created_at).getTime() - new Date(a.created_at).getTime(),
  );

  return (
    <div className="overflow-x-auto rounded-xl border">
      <Table>
        <TableHeader>
          <TableRow>
            <TableHead>Run</TableHead>
            <TableHead>Dataset</TableHead>
            <TableHead>Metrics</TableHead>
            <TableHead>Config</TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {ordered.map((run) => (
            <TableRow key={run.id}>
              <TableCell className="whitespace-nowrap text-xs text-muted-foreground">
                {formatDateTime(run.created_at)}
              </TableCell>
              <TableCell className="whitespace-nowrap font-mono text-xs">
                {run.dataset_version}
              </TableCell>
              <TableCell>
                <div className="flex flex-wrap gap-1">
                  {Object.entries(run.metrics).map(([name, value]) => (
                    <Badge key={name} variant="secondary" className="font-mono font-normal">
                      {name} {value.toFixed(3)}
                    </Badge>
                  ))}
                </div>
              </TableCell>
              <TableCell className="max-w-72 truncate font-mono text-xs text-muted-foreground">
                {configSummary(run.config) || "—"}
              </TableCell>
            </TableRow>
          ))}
        </TableBody>
      </Table>
    </div>
  );
}
