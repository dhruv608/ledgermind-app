// VAT returns and supplementary schedules (VAT & payroll tab).
import type { SupplementaryDocument, SupplementaryData, VAT100Record, VatReturnInput } from "@/types/engagement";
import { API_BASE, fetch } from "./client";

export const inputsApi = {
  async getVatReturns(engagementId: string): Promise<VAT100Record[]> {
    const res = await fetch(`${API_BASE}/engagements/${engagementId}/vat-returns`);
    if (!res.ok) throw new Error("Failed to load VAT returns");
    return res.json();
  },

  /** Each return's amount owed, paid against it and still unpaid, matched as on G9 (source "": no payments known) */
  async getVatReturnsPaid(engagementId: string): Promise<{
    source: "summary" | "ledger" | "";
    /** opening: last year's return picked from the payments (no last-year return entered), with its note */
    returns: { period_end: string; owed: number; paid: number | null; unpaid: number | null; opening?: boolean; note?: string; paid_on?: string[] }[];
    /** The HMRC VAT account: payments to / from HMRC (earlier: last year's returns paid this year), charges (not VAT) */
    hmrc?: { date: string | null; description: string; amount: number; kind: "payment" | "earlier" | "charge" }[];
  }> {
    const res = await fetch(`${API_BASE}/engagements/${engagementId}/vat-returns/paid`);
    if (!res.ok) throw new Error("Failed to load the VAT payments");
    return res.json();
  },

  async saveVatReturns(engagementId: string, returns: VatReturnInput[]): Promise<VAT100Record[]> {
    const res = await fetch(`${API_BASE}/engagements/${engagementId}/vat-returns`, {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ returns }),
    });
    if (!res.ok) {
      const err = await res.json().catch(() => null);
      throw new Error(typeof err?.detail === "string" ? err.detail : "Failed to save VAT returns");
    }
    return res.json();
  },

  async uploadSupplementaryDocuments(engagementId: string, files: File[], docType?: string): Promise<any> {
    const formData = new FormData();
    files.forEach((f) => formData.append("files", f));
    if (docType) formData.append("doc_type", docType);

    const res = await fetch(`${API_BASE}/engagements/${engagementId}/supplementary-upload`, {
      method: "POST",
      body: formData,
    });
    if (!res.ok) throw new Error("Failed to upload supplementary documents");
    return res.json();
  },

  async getSupplementaryDocuments(engagementId: string): Promise<SupplementaryDocument[]> {
    const res = await fetch(`${API_BASE}/engagements/${engagementId}/supplementary-docs`);
    if (!res.ok) return [];
    return res.json();
  },

  async getSupplementaryData(engagementId: string): Promise<SupplementaryData> {
    const res = await fetch(`${API_BASE}/engagements/${engagementId}/supplementary-data`);
    if (!res.ok) return { vat_records: [], fixed_asset_records: [], payroll_records: [] };
    return res.json();
  },
};
