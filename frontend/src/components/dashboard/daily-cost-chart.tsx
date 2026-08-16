"use client";

import { useMemo } from "react";
import { Bar, BarChart, CartesianGrid, XAxis, YAxis } from "recharts";
import { CHART_SERIES } from "@/components/dashboard/palette";
import {
  type ChartConfig,
  ChartContainer,
  ChartTooltip,
  ChartTooltipContent,
} from "@/components/ui/chart";
import type { DailyCostOut } from "@/lib/api/types";
import { formatDate } from "@/lib/format";

const config: ChartConfig = {
  cost: {
    label: "Cost (USD)",
    theme: { light: CHART_SERIES[0].light, dark: CHART_SERIES[0].dark },
  },
};

/** Daily spend over the requested window; single series, so no legend. */
export function DailyCostChart({ daily }: { daily: DailyCostOut[] }) {
  const rows = useMemo(
    () =>
      daily.map((d) => ({
        date: formatDate(d.date),
        cost: Number(d.cost_usd),
        calls: d.calls,
      })),
    [daily],
  );

  if (rows.length === 0) {
    return (
      <p className="flex h-56 items-center justify-center text-sm text-muted-foreground">
        No LLM spend recorded yet.
      </p>
    );
  }

  return (
    <ChartContainer config={config} className="h-64 w-full">
      <BarChart data={rows} margin={{ top: 8, right: 12, left: 0, bottom: 0 }}>
        <CartesianGrid vertical={false} strokeOpacity={0.4} />
        <XAxis dataKey="date" tickLine={false} axisLine={false} tickMargin={8} fontSize={11} />
        <YAxis
          tickLine={false}
          axisLine={false}
          width={48}
          fontSize={11}
          tickFormatter={(v: number) => `$${v.toFixed(2)}`}
        />
        <ChartTooltip
          content={<ChartTooltipContent formatter={(value) => `$${Number(value).toFixed(4)}`} />}
        />
        <Bar dataKey="cost" fill="var(--color-cost)" radius={[4, 4, 0, 0]} maxBarSize={28} />
      </BarChart>
    </ChartContainer>
  );
}
