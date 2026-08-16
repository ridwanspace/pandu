"use client";

import { useQuery } from "@tanstack/react-query";
import { CostByModelTable } from "@/components/dashboard/cost-by-model-table";
import { DailyCostChart } from "@/components/dashboard/daily-cost-chart";
import { EvalRunsTable } from "@/components/dashboard/eval-runs-table";
import { MetricTrendChart } from "@/components/dashboard/metric-trend-chart";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { listEvalRuns } from "@/lib/api/evals";
import { getCostStats } from "@/lib/api/stats";
import { formatCount, formatUsd } from "@/lib/format";

const COST_WINDOW_DAYS = 30;

function StatCard({ label, value, hint }: { label: string; value: string; hint?: string }) {
  return (
    <Card>
      <CardHeader className="pb-2">
        <CardTitle className="text-sm font-medium text-muted-foreground">{label}</CardTitle>
      </CardHeader>
      <CardContent>
        <p className="text-2xl font-semibold tracking-tight">{value}</p>
        {hint ? <p className="mt-1 text-xs text-muted-foreground">{hint}</p> : null}
      </CardContent>
    </Card>
  );
}

function SectionSkeleton() {
  return (
    <div className="space-y-2">
      <Skeleton className="h-8 w-1/3" />
      <Skeleton className="h-56 w-full" />
    </div>
  );
}

export default function DashboardPage() {
  const costs = useQuery({
    queryKey: ["costs", COST_WINDOW_DAYS],
    queryFn: () => getCostStats(COST_WINDOW_DAYS),
  });
  const evals = useQuery({ queryKey: ["eval-runs"], queryFn: listEvalRuns });

  const totalCalls = costs.data?.daily.reduce((sum, d) => sum + d.calls, 0) ?? 0;
  const models = new Set(costs.data?.by_model.map((m) => m.model)).size;
  const avgCost =
    costs.data && totalCalls > 0 ? String(Number(costs.data.total_usd) / totalCalls) : null;

  return (
    <div className="mx-auto w-full max-w-6xl space-y-8 p-6">
      <div>
        <h1 className="text-lg font-semibold tracking-tight">Dashboard</h1>
        <p className="text-sm text-muted-foreground">
          Retrieval quality over eval runs and LLM spend for the last {COST_WINDOW_DAYS} days.
        </p>
      </div>

      {costs.isError && evals.isError ? (
        <p className="rounded-lg border border-dashed p-8 text-center text-sm text-muted-foreground">
          Could not reach the API. Check the connection in Settings.
        </p>
      ) : null}

      <section aria-label="Cost summary" className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
        {costs.isPending ? (
          <>
            <Skeleton className="h-28" />
            <Skeleton className="h-28" />
            <Skeleton className="h-28" />
            <Skeleton className="h-28" />
          </>
        ) : costs.data ? (
          <>
            <StatCard
              label="Total spend"
              value={formatUsd(costs.data.total_usd)}
              hint={`last ${COST_WINDOW_DAYS} days`}
            />
            <StatCard label="LLM calls" value={formatCount(totalCalls)} />
            <StatCard label="Avg cost / call" value={formatUsd(avgCost)} />
            <StatCard label="Models used" value={String(models)} />
          </>
        ) : null}
      </section>

      <section aria-label="Evaluation" className="space-y-4">
        <Card>
          <CardHeader>
            <CardTitle className="text-base">Retrieval metrics over runs</CardTitle>
          </CardHeader>
          <CardContent>
            {evals.isPending ? (
              <SectionSkeleton />
            ) : evals.isError ? (
              <p className="text-sm text-muted-foreground">Could not load eval runs.</p>
            ) : (
              <MetricTrendChart runs={evals.data.items} />
            )}
          </CardContent>
        </Card>
        {evals.data ? <EvalRunsTable runs={evals.data.items} /> : null}
      </section>

      <section aria-label="Costs" className="space-y-4">
        <Card>
          <CardHeader>
            <CardTitle className="text-base">Daily spend</CardTitle>
          </CardHeader>
          <CardContent>
            {costs.isPending ? (
              <SectionSkeleton />
            ) : costs.isError ? (
              <p className="text-sm text-muted-foreground">Could not load cost stats.</p>
            ) : (
              <DailyCostChart daily={costs.data.daily} />
            )}
          </CardContent>
        </Card>
        {costs.data ? <CostByModelTable rows={costs.data.by_model} /> : null}
      </section>
    </div>
  );
}
