"use client";

import { DocumentsTable } from "@/components/documents/documents-table";
import { UploadDropzone } from "@/components/documents/upload-dropzone";

export default function DocumentsPage() {
  return (
    <div className="mx-auto w-full max-w-5xl space-y-6 p-6">
      <div>
        <h1 className="text-lg font-semibold tracking-tight">Documents</h1>
        <p className="text-sm text-muted-foreground">
          The corpus behind every answer. Upload files and watch them move through parsing, chunking
          and embedding.
        </p>
      </div>
      <UploadDropzone />
      <DocumentsTable />
    </div>
  );
}
