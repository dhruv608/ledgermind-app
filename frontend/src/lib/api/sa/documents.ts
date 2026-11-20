// The documents on a return: upload and read, check, show and remove.
import { API_BASE, fetch } from "../client";
import { detail } from "./detail";
import type { SaDocument } from "./types";

export const saDocumentsApi = {
  async listSaDocuments(jobId: string): Promise<SaDocument[]> {
    const res = await fetch(`${API_BASE}/sa/jobs/${jobId}/documents`);
    if (!res.ok) throw new Error(await detail(res, "Could not load the documents"));
    return res.json();
  },

  /** Send files (zips are unpacked); the return's whole document list comes back. */
  // The files are read in the background (a scan can take minutes when the AI service is slow): the upload answers at
  // once, then this asks every few seconds until the reading is done and returns the job's documents
  async uploadSaDocuments(jobId: string, files: File[]): Promise<SaDocument[]> {
    const form = new FormData();
    files.forEach((f) => form.append("files", f));
    const res = await fetch(`${API_BASE}/sa/jobs/${jobId}/documents?background=true`, { method: "POST", body: form });
    if (!res.ok) throw new Error(await detail(res, "Could not read the documents"));
    const { reading_id } = await res.json();
    let misses = 0;
    for (;;) {
      await new Promise((r) => setTimeout(r, 3000));
      let r: Response;
      try {
        r = await fetch(`${API_BASE}/sa/jobs/${jobId}/reading/${reading_id}`);
      } catch {
        if (++misses > 20) throw new Error("Lost touch with the server while reading: refresh to see the documents.");
        continue;                                  // a moment offline (a restart): ask again
      }
      if (!r.ok) {
        if (r.status >= 500 && ++misses <= 20) continue;
        throw new Error(await detail(r, "Could not read the documents"));
      }
      const s = await r.json();
      if (s.done) {
        if (s.error) throw new Error(s.error);
        return s.documents;
      }
    }
  },

  async deleteSaDocument(jobId: string, docId: number): Promise<SaDocument[]> {
    const res = await fetch(`${API_BASE}/sa/jobs/${jobId}/documents/${docId}`, { method: "DELETE" });
    if (!res.ok) throw new Error(await detail(res, "Could not remove the document"));
    return res.json();
  },

  /** The document itself (PDF or picture), to show beside what was read. */
  saDocumentUrl(jobId: string, docId: number): string {
    return `${API_BASE}/sa/jobs/${jobId}/documents/${docId}/file`;
  },

  /** A person's check of a document: figures as corrected, and marked read. */
  async reviewSaDocument(jobId: string, docId: number, fields: Record<string, string | number | null> | null, confirm = true): Promise<SaDocument> {
    const res = await fetch(`${API_BASE}/sa/jobs/${jobId}/documents/${docId}`, {
      method: "PATCH", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ fields, confirm }),
    });
    if (!res.ok) throw new Error(await detail(res, "Could not save the check"));
    return res.json();
  },
};
