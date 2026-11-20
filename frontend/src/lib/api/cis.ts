// CIS: the HMRC figures per tax month and the tests T1-T10.
import { API_BASE, fetch } from "./client";

/** One tax month on the HMRC CIS input screen: what was filed, beside the books on a cash basis */
export interface CisHmrcMonth {
  tax_month: string;
  label: string;
  month_no: number;
  tax_year: string;
  books: { deducted: number | null; suffered: number | null };
  hmrc: Record<string, number | string>;
}

export interface CisHmrcScreen {
  on: boolean;
  sides?: ("suffered" | "deducted")[];
  mode?: "MANUAL" | "NOT_AVAILABLE";
  months?: CisHmrcMonth[];
  year?: Record<string, number | string>;
  books_outside_months?: Record<string, { deducted?: number; suffered?: number }>;
}

/** One CIS test (T1-T10) against HMRC */
export interface CisCheck {
  ref: string;
  name: string;
  status: "PASS" | "FAIL" | "INFO" | "NOT RUN";
  summary: string;
  rows: Record<string, unknown>[];
  query_to: string;
  query: string;
  amount: number;
}

export interface CisChecks {
  on: boolean;
  mode?: string;
  checks?: CisCheck[];
  timing?: { item: string; amount: number; effect: number; lines: Record<string, unknown>[] }[];
}

export const cisApi = {
  async getCisHmrc(engagementId: string): Promise<CisHmrcScreen> {
    const res = await fetch(`${API_BASE}/engagements/${engagementId}/cis/hmrc`);
    if (!res.ok) throw new Error((await res.json().catch(() => ({}))).detail || "Could not load the HMRC CIS figures");
    return res.json();
  },

  async getCisChecks(engagementId: string): Promise<CisChecks> {
    const res = await fetch(`${API_BASE}/engagements/${engagementId}/cis/checks`);
    if (!res.ok) throw new Error((await res.json().catch(() => ({}))).detail || "Could not work out the CIS checks");
    return res.json();
  },

  async saveCisHmrc(engagementId: string, body: { mode?: string; months?: Record<string, Record<string, unknown>>; year?: Record<string, unknown> }): Promise<CisHmrcScreen> {
    const res = await fetch(`${API_BASE}/engagements/${engagementId}/cis/hmrc`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
    if (!res.ok) throw new Error((await res.json().catch(() => ({}))).detail || "Could not save the HMRC CIS figures");
    return res.json();
  },
};
