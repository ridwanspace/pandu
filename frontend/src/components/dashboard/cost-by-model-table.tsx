"use client";

import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import type { CostByModelOut } from "@/lib/api/types";
import { formatCount, formatUsd } from "@/lib/format";

export function CostByModelTable({ rows }: { rows: CostByModelOut[] }) {
  if (rows.length === 0) {
    return (
      <p className="rounded-lg border border-dashed p-8 text-center text-sm text-muted-foreground">
        No LLM calls recorded in this window.
      </p>
    );
  }

  return (
    <div className="overflow-x-auto rounded-lg border">
      <Table>
        <TableHeader>
          <TableRow>
            <TableHead>Model</TableHead>
            <TableHead>Operation</TableHead>
            <TableHead className="text-right">Calls</TableHead>
            <TableHead className="text-right">Prompt tok</TableHead>
            <TableHead className="text-right">Completion tok</TableHead>
            <TableHead className="text-right">Cost</TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {rows.map((row) => (
            <TableRow key={`${row.model}-${row.operation}`}>
              <TableCell className="font-mono text-xs">{row.model}</TableCell>
              <TableCell className="text-xs text-muted-foreground">{row.operation}</TableCell>
              <TableCell className="text-right font-mono text-xs tabular-nums">
                {formatCount(row.calls)}
              </TableCell>
              <TableCell className="text-right font-mono text-xs tabular-nums">
                {formatCount(row.prompt_tokens)}
              </TableCell>
              <TableCell className="text-right font-mono text-xs tabular-nums">
                {formatCount(row.completion_tokens)}
              </TableCell>
              <TableCell className="text-right font-mono text-xs tabular-nums">
                {formatUsd(row.cost_usd)}
              </TableCell>
            </TableRow>
          ))}
        </TableBody>
      </Table>
    </div>
  );
}
