// The Opening balances area (M1): each balance's opening in the books against last year's closing, and why.
import { API_BASE, fetch } from "./client";

export interface OpeningRow {
  code: number;
  name: string;
  books: number;
  last_year: number;
  difference: number;
  cause: string;
}

export interface OpeningBalances {
  /** False when there is nothing to compare with (no last year's figures) */
  compared: boolean;
  source: string;
  rows: OpeningRow[];
  books_bf?: number;
  last_year_bf?: number;
  gap?: number;
  explained?: number;
}

export const openingApi = {
  async getOpeningBalances(engagementId: string): Promise<OpeningBalances> {
    const res = await fetch(`${API_BASE}/engagements/${engagementId}/opening-balances`);
    if (!res.ok) throw new Error((await res.json().catch(() => ({}))).detail || "Could not compare the opening balances");
    return res.json();
  },
};
