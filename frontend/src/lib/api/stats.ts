import { apiFetch } from "@/lib/api/client";
import type { CostStatsOut } from "@/lib/api/types";

export async function getCostStats(days = 30): Promise<CostStatsOut> {
  return apiFetch<CostStatsOut>(`/stats/costs?days=${days}`);
}
