// An area page's Evidence tab: the documents behind the area's balance, kept for the reviewer and, where the app has
// a reader (VAT returns, payroll report, fixed asset register, loans register), read into the checks.
import { API_BASE, fetch } from "./client";

export interface EvidenceDoc {
  id: number | null;          // null: read on the VAT & payroll tab, the file not kept
  filename: string;
  size: number;
  read_as: string | null;     // what the checks read it as (VAT_100 ...), null: kept only
  records: number;
  at: string | null;
  kept: boolean;
}

export type EvidenceByArea = Record<string, EvidenceDoc[]>;

async function detail(res: Response, fallback: string): Promise<string> {
  const body = await res.json().catch(() => ({}));
  return typeof body.detail === "string" ? body.detail : fallback;
}

export const evidenceApi = {
  async getEvidence(engagementId: string): Promise<EvidenceByArea> {
    const res = await fetch(`${API_BASE}/engagements/${engagementId}/evidence`);
    if (!res.ok) throw new Error(await detail(res, "Could not load the documents"));
    return res.json();
  },

  /** Upload to an area; every area's documents come back. */
  async addEvidence(engagementId: string, area: string, files: File[]): Promise<EvidenceByArea> {
    const form = new FormData();
    files.forEach((f) => form.append("files", f));
    const res = await fetch(`${API_BASE}/engagements/${engagementId}/evidence/${area}`, { method: "POST", body: form });
    if (!res.ok) throw new Error(await detail(res, "Could not upload the document"));
    return res.json();
  },

  async removeEvidence(engagementId: string, evidenceId: number): Promise<EvidenceByArea> {
    const res = await fetch(`${API_BASE}/engagements/${engagementId}/evidence/${evidenceId}`, { method: "DELETE" });
    if (!res.ok) throw new Error(await detail(res, "Could not remove the document"));
    return res.json();
  },

  /** The kept file, downloaded to this computer. */
  async openEvidence(engagementId: string, doc: EvidenceDoc): Promise<void> {
    const res = await fetch(`${API_BASE}/engagements/${engagementId}/evidence/file/${doc.id}`);
    if (!res.ok) throw new Error(await detail(res, "Could not open the document"));
    const url = URL.createObjectURL(await res.blob());
    const a = document.createElement("a");
    a.href = url;
    a.download = doc.filename;
    a.click();
    setTimeout(() => URL.revokeObjectURL(url), 2000);
  },
};
