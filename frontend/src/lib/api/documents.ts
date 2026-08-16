import { apiFetch } from "@/lib/api/client";
import type {
  ChunkListOut,
  DocumentListOut,
  DocumentOut,
  DocumentUploadOut,
  UUID,
} from "@/lib/api/types";

export async function uploadDocument(file: File): Promise<DocumentUploadOut> {
  const form = new FormData();
  form.append("file", file);
  return apiFetch<DocumentUploadOut>("/documents", { method: "POST", body: form });
}

export async function listDocuments(): Promise<DocumentListOut> {
  return apiFetch<DocumentListOut>("/documents");
}

export async function getDocument(id: UUID): Promise<DocumentOut> {
  return apiFetch<DocumentOut>(`/documents/${id}`);
}

export async function listChunks(id: UUID, limit = 50): Promise<ChunkListOut> {
  return apiFetch<ChunkListOut>(`/documents/${id}/chunks?limit=${limit}`);
}

export async function deleteDocument(id: UUID): Promise<void> {
  await apiFetch<undefined>(`/documents/${id}`, { method: "DELETE" });
}
