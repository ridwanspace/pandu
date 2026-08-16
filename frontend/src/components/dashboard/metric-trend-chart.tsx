"use client";

import { useMemo } from "react";
import { CartesianGrid, Line, LineChart, XAxis, YAxis } from "recharts";
import { CHART_SERIES, metricSlug } from "@/components/dashboard/palette";
import {
  type ChartConfig,
  ChartContainer,
  ChartLegend,
  ChartLegendContent,
  ChartTooltip,
  ChartTooltipContent,
} from "@/components/ui/chart";
import type { EvalRunOut } from "@/lib/api/types";
import { formatDateTime } from "@/lib/format";

const MAX_SERIES = CHART_SERIES.length;

/** Prefer the headline retrieval metrics, then fill up to the series cap.
 * Count-like series (e.g. `examples`) are excluded — mixing counts with 0..1
 * scores flattens the metric lines against the axis. */
function selectMetrics(runs: EvalRunOut[]): string[] {
  const names = new Set<string>();
  for (const run of runs) for (const name of Object.keys(run.metrics)) names.add(name);
  const all = [...names].filter((n) => !/example|count|^k$/i.test(n));
  const preferred = all.filter((n) => /recall|mrr/i.test(n)).sort();
  const rest = all.filter((n) => !/recall|mrr/i.test(n)).sort();
  return [...preferred, ...rest].slice(0, MAX_SERIES);
}

/** Metric trend over eval runs (oldest to newest). */
export function MetricTrendChart({ runs }: { runs: EvalRunOut[] }) {
  const { rows, config, metrics } = useMemo(() => {
    const ordered = [...runs].sort(
      (a, b) => new Date(a.created_at).getTime() - new Date(b.created_at).getTime(),
    );
    const selected = selectMetrics(ordered);
    const chartConfig: ChartConfig = {};
    selected.forEach((name, i) => {
      chartConfig[metricSlug(name)] = {
        label: name,
        theme: { light: CHART_SERIES[i].light, dark: CHART_SERIES[i].dark },
      };
    });
    const chartRows = ordered.map((run) => {
      const row: Record<string, number | string | null> = {
        run: formatDateTime(run.created_at),
      };
      for (const name of selected) row[metricSlug(name)] = run.metrics[name] ?? null;
      return row;
    });
    return { rows: chartRows, config: chartConfig, metrics: selected };
  }, [runs]);

  if (rows.length === 0) {
    return (
      <p className="flex h-56 items-center justify-center text-sm text-muted-foreground">
        No eval runs yet. Run `make evals` to populate the golden-dataset metrics.
      </p>
    );
  }

  return (
    <ChartContainer config={config} className="h-64 w-full">
      <LineChart data={rows} margin={{ top: 8, right: 12, left: 0, bottom: 0 }}>
        <CartesianGrid vertical={false} strokeOpacity={0.4} />
        <XAxis dataKey="run" tickLine={false} axisLine={false} tickMargin={8} fontSize={11} />
        <YAxis
          tickLine={false}
          axisLine={false}
          width={36}
          fontSize={11}
          domain={[0, 1]}
          tickFormatter={(v: number) => v.toFixed(1)}
        />
        <ChartTooltip content={<ChartTooltipContent />} />
        <ChartLegend content={<ChartLegendContent />} />
        {metrics.map((name) => (
          <Line
            key={name}
            type="monotone"
            dataKey={metricSlug(name)}
            stroke={`var(--color-${metricSlug(name)})`}
            strokeWidth={2}
            dot={{ r: 3, strokeWidth: 0, fill: `var(--color-${metricSlug(name)})` }}
            connectNulls
          />
        ))}
      </LineChart>
    </ChartContainer>
  );
}
