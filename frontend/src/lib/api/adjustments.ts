// Accruals and prepayments line by line: this year's (booked at the year end) and last year's (reversed this year).
import { API_BASE, fetch } from "./client";

export interface AdjustmentLine {
  id?: number;
  kind: "ACCRUAL" | "PREPAYMENT";
  description: string;
  cost_code: number;
  cost_name?: string;
  amount: number;
  /** The invoice behind it (the Prepayments screen): number, date, amount and the period it covers */
  invoice_number?: string | null;
  invoice_date?: string | null;
  invoice_amount?: number | null;
  period_from?: string | null;
  period_to?: string | null;
}

export interface Adjustments {
  this_year: AdjustmentLine[];
  last_year: AdjustmentLine[];
  /** 'last year in the app' (read only here), 'entered', or '' */
  last_year_source: string;
  last_year_editable: boolean;
  in_books: { accruals: number; prepayments: number };
}

export const adjustmentsApi = {
  async getAdjustments(engagementId: string): Promise<Adjustments> {
    const res = await fetch(`${API_BASE}/engagements/${engagementId}/adjustments`);
    if (!res.ok) throw new Error((await res.json().catch(() => ({}))).detail || "Could not read the accruals and prepayments");
    return res.json();
  },

  async saveAdjustments(engagementId: string, thisYear: AdjustmentLine[], lastYear: AdjustmentLine[] | null): Promise<Adjustments> {
    const strip = (l: AdjustmentLine) => ({ kind: l.kind, description: l.description, cost_code: l.cost_code, amount: l.amount });
    const res = await fetch(`${API_BASE}/engagements/${engagementId}/adjustments`, {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ this_year: thisYear.map(strip), last_year: lastYear ? lastYear.map(strip) : null }),
    });
    if (!res.ok) throw new Error((await res.json().catch(() => ({}))).detail || "Not saved");
    return res.json();
  },
};
