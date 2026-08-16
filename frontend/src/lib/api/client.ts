import { useSettings } from "@/lib/settings-store";

/** Error raised for non-2xx responses, carrying the backend `detail` if any. */
export class ApiError extends Error {
  readonly status: number;

  constructor(status: number, message: string) {
    super(message);
    this.name = "ApiError";
    this.status = status;
  }
}

function connection(): { baseUrl: string; apiKey: string } {
  const { apiBaseUrl, apiKey } = useSettings.getState();
  return { baseUrl: apiBaseUrl.replace(/\/+$/, ""), apiKey };
}

/** Absolute URL for a path under the versioned API prefix. */
export function apiUrl(path: string): string {
  return `${connection().baseUrl}/api/v1${path}`;
}

async function toApiError(res: Response): Promise<ApiError> {
  let detail = `Request failed with status ${res.status}`;
  try {
    const body: unknown = await res.json();
    if (
      typeof body === "object" &&
      body !== null &&
      "detail" in body &&
      typeof (body as { detail: unknown }).detail === "string"
    ) {
      detail = (body as { detail: string }).detail;
    }
  } catch {
    // Non-JSON error body; keep the generic message.
  }
  return new ApiError(res.status, detail);
}

export interface ApiFetchInit extends Omit<RequestInit, "body"> {
  /** JSON-serialized into the body with the right content type. */
  json?: unknown;
  /** Raw body (e.g. FormData for multipart uploads). */
  body?: BodyInit;
}

/**
 * Fetch wrapper: prefixes the base URL, injects `X-API-Key`, serializes JSON
 * and normalizes errors. `T = undefined` for 204 responses.
 */
export async function apiFetch<T>(path: string, init: ApiFetchInit = {}): Promise<T> {
  const { json, headers: extraHeaders, ...rest } = init;
  const { apiKey } = connection();

  const headers = new Headers(extraHeaders);
  if (apiKey) headers.set("X-API-Key", apiKey);
  let body = rest.body;
  if (json !== undefined) {
    headers.set("Content-Type", "application/json");
    body = JSON.stringify(json);
  }

  const res = await fetch(apiUrl(path), { ...rest, headers, body });
  if (!res.ok) throw await toApiError(res);
  if (res.status === 204) return undefined as T;
  return (await res.json()) as T;
}

/**
 * POST returning a raw SSE `Response` for manual stream parsing
 * (see `lib/sse.ts`). The caller iterates `readSSE(res.body)`.
 */
export async function apiStream(path: string, json: unknown): Promise<Response> {
  const { apiKey } = connection();
  const headers = new Headers({
    "Content-Type": "application/json",
    Accept: "text/event-stream",
  });
  if (apiKey) headers.set("X-API-Key", apiKey);

  const res = await fetch(apiUrl(path), {
    method: "POST",
    headers,
    body: JSON.stringify(json),
  });
  if (!res.ok) throw await toApiError(res);
  if (!res.body) throw new ApiError(0, "Response has no body to stream");
  return res;
}

/** GET /health lives outside the /api/v1 prefix and needs no key. */
export async function checkHealth(baseUrl: string): Promise<boolean> {
  try {
    const res = await fetch(`${baseUrl.replace(/\/+$/, "")}/health`);
    if (!res.ok) return false;
    const body = (await res.json()) as { status?: string };
    return body.status === "ok";
  } catch {
    return false;
  }
}
