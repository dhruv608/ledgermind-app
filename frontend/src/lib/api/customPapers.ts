import { API_BASE, fetch } from "./client";

/** A working paper the accountant added to an area (Add New Workpaper / Add New Reconciliation) */
export type CustomPaperKind = "DETAILED" | "SUPPORTING" | "RECONCILIATION" | "LOAN_SCHEDULE";
export interface CustomPaperLine { side: "DEBIT" | "CREDIT"; label: string; amount: number }
export interface CustomPaper {
  id: number;
  area: string;
  kind: CustomPaperKind;
  name: string;
  codes: number[];
  note: string;
  lines: CustomPaperLine[];
  debit: number;
  credit: number;
  difference: number;
  updated_at: string | null;
}
export type CustomPaperIn = { area: string; kind: CustomPaperKind; name: string; codes?: number[]; note?: string; lines?: CustomPaperLine[] };

async function ok<T>(res: Response, fallback: string): Promise<T> {
  if (!res.ok) throw new Error((await res.json().catch(() => ({}))).detail || fallback);
  return res.json();
}
const json = (method: string, body: unknown) => ({ method, headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });

export const customPapersApi = {
  async getCustomPapers(engagementId: string): Promise<CustomPaper[]> {
    return ok(await fetch(`${API_BASE}/engagements/${engagementId}/custom-papers`), "Could not load the added working papers");
  },
  async addCustomPaper(engagementId: string, body: CustomPaperIn): Promise<CustomPaper> {
    return ok(await fetch(`${API_BASE}/engagements/${engagementId}/custom-papers`, json("POST", body)), "Could not add the working paper");
  },
  async updateCustomPaper(engagementId: string, id: number, body: Partial<CustomPaperIn>): Promise<CustomPaper> {
    return ok(await fetch(`${API_BASE}/engagements/${engagementId}/custom-papers/${id}`, json("PUT", body)), "Could not save the working paper");
  },
  async deleteCustomPaper(engagementId: string, id: number): Promise<{ ok: boolean }> {
    return ok(await fetch(`${API_BASE}/engagements/${engagementId}/custom-papers/${id}`, { method: "DELETE" }), "Could not remove the working paper");
  },
};
