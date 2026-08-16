import { apiFetch } from "@/lib/api/client";
import type { SearchIn, SearchListOut } from "@/lib/api/types";

export async function search(input: SearchIn): Promise<SearchListOut> {
  return apiFetch<SearchListOut>("/retrieval/search", { method: "POST", json: input });
}
