/**
 * Hand-written mirror of the backend HTTP contract (see repo BRIEF /
 * ARCHITECTURE_REVIEW.md). Field names intentionally match the wire format
 * (snake_case). `pnpm generate:api` emits `generated.d.ts` from the live
 * OpenAPI schema; CI drift-checks it against this file.
 */

/** ISO-8601 timestamp string. */
export type ISODateTime = string;
export type UUID = string;
/** Decimal money serialized as a string, e.g. "0.001234". */
export type UsdString = string;

// ---------------------------------------------------------------------------
// Documents
// ---------------------------------------------------------------------------

export type DocumentStatus = "queued" | "parsing" | "embedding" | "ready" | "failed";

/** Statuses that mean ingestion is still in flight (drives table polling). */
export const ACTIVE_DOCUMENT_STATUSES: readonly DocumentStatus[] = [
  "queued",
  "parsing",
  "embedding",
];

export interface DocumentOut {
  id: UUID;
  filename: string;
  content_type: string;
  size_bytes: number;
  status: DocumentStatus;
  error: string | null;
  chunk_count: number;
  created_at: ISODateTime;
  updated_at: ISODateTime;
}

export interface DocumentUploadOut {
  id: UUID;
  filename: string;
  status: DocumentStatus;
}

export interface DocumentListOut {
  items: DocumentOut[];
}

export interface ChunkOut {
  seq: number;
  text: string;
  token_count: number;
  heading_path: string[];
}

export interface ChunkListOut {
  items: ChunkOut[];
}

// ---------------------------------------------------------------------------
// Conversations / chat
// ---------------------------------------------------------------------------

export interface ConversationCreateIn {
  title?: string;
}

export interface ConversationOut {
  id: UUID;
  title: string | null;
  created_at: ISODateTime;
}

export interface ConversationListOut {
  items: ConversationOut[];
}

export interface CitationOut {
  /** 1-based marker matching inline `[n]` references in the answer. */
  marker: number;
  chunk_id: UUID;
  document_id: UUID;
  filename: string;
  heading_path: string[];
  snippet: string;
  score: number;
}

export interface MessageOut {
  id: UUID;
  role: "user" | "assistant";
  content: string;
  created_at: ISODateTime;
  model: string | null;
  prompt_tokens: number | null;
  completion_tokens: number | null;
  cost_usd: UsdString | null;
  latency_ms: number | null;
  citations: CitationOut[];
}

export interface MessageListOut {
  items: MessageOut[];
}

export interface MessageCreateIn {
  question: string;
  document_ids?: UUID[];
}

// SSE event payloads for POST /conversations/{id}/messages, in stream order.

export interface SourcesEventData {
  citations: CitationOut[];
}

export interface TokenEventData {
  text: string;
}

export interface UsageEventData {
  model: string;
  prompt_tokens: number;
  completion_tokens: number;
  cost_usd: UsdString;
  latency_ms: number;
}

export interface DoneEventData {
  message_id: UUID;
}

export interface ErrorEventData {
  detail: string;
}

// ---------------------------------------------------------------------------
// Retrieval
// ---------------------------------------------------------------------------

export interface SearchIn {
  query: string;
  document_ids?: UUID[];
}

export interface SearchItemOut {
  chunk_id: UUID;
  document_id: UUID;
  seq: number;
  text: string;
  filename: string;
  heading_path: string[];
  fused_score: number;
  rerank_score: number | null;
  dense_rank: number | null;
  lexical_rank: number | null;
}

export interface SearchListOut {
  items: SearchItemOut[];
}

// ---------------------------------------------------------------------------
// Evaluation / stats
// ---------------------------------------------------------------------------

export interface EvalRunOut {
  id: UUID;
  created_at: ISODateTime;
  dataset_version: string;
  metrics: Record<string, number>;
  config: Record<string, unknown>;
}

export interface EvalRunListOut {
  items: EvalRunOut[];
}

export interface CostByModelOut {
  model: string;
  operation: string;
  calls: number;
  prompt_tokens: number;
  completion_tokens: number;
  cost_usd: UsdString;
}

export interface DailyCostOut {
  date: string;
  cost_usd: UsdString;
  calls: number;
}

export interface CostStatsOut {
  total_usd: UsdString;
  by_model: CostByModelOut[];
  daily: DailyCostOut[];
}
