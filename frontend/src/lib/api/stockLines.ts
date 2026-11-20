import { API_BASE, fetch } from "./client";

/** The closing stock line by line */
export interface StockLine {
  code: number | null;
  stock_type: string;
  description: string;
  amount: number;
  impairment: number;
  last_year: number | null;
  note: string;
}
export interface StockLines {
  lines: StockLine[];
  verified_by: "" | "US" | "CLIENT";
  total: number;
  books: number;
  difference: number | null;
}

export const stockLinesApi = {
  async getStockLines(engagementId: string): Promise<StockLines> {
    const res = await fetch(`${API_BASE}/engagements/${engagementId}/stock-lines`);
    if (!res.ok) throw new Error("Could not load the stock lines");
    return res.json();
  },
  async saveStockLines(engagementId: string, lines: StockLine[], verifiedBy: StockLines["verified_by"]): Promise<StockLines> {
    const res = await fetch(`${API_BASE}/engagements/${engagementId}/stock-lines`, {
      method: "PUT", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ lines, verified_by: verifiedBy }),
    });
    if (!res.ok) throw new Error((await res.json().catch(() => ({}))).detail || "Could not save the stock lines");
    return res.json();
  },
};
