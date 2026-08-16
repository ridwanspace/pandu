import { apiFetch } from "@/lib/api/client";
import type { EvalRunListOut } from "@/lib/api/types";

export async function listEvalRuns(): Promise<EvalRunListOut> {
  return apiFetch<EvalRunListOut>("/evals/runs");
}
