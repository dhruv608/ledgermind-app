// The Data check: is everything the working papers need in the client's files, and was it read.
import { API_BASE, fetch } from "./client";

export type DataCheckStatus = "OK" | "WARNING" | "STOP";

/** What to do about an item (the Data check tab's button for it) */
export type DataCheckAction =
  | "" | "upload_last_year_tb" | "first_year" | "reupload_tb" | "upload_gl" | "upload_far" | "upload_payroll"
  | "enter_vat" | "upload_aged" | "enter_bank" | "reupload_bank" | "confirm_vat" | "loan_statement" | "add_properties";

export interface DataCheckItem {
  key: string;
  label: string;
  status: DataCheckStatus;
  detail: string;
  action: DataCheckAction;
}

export interface DataCheck {
  ready: boolean;          // no STOP item: the workbook can be built
  stops: number;
  warnings: number;
  first_year: boolean;
  items: DataCheckItem[];
  added?: number;          // after last year's TB is added: how many opening balances came in
  how?: string;
}

async function detail(res: Response, fallback: string): Promise<string> {
  const body = await res.json().catch(() => ({}));
  return typeof body.detail === "string" ? body.detail : fallback;
}

export const dataCheckApi = {
  async getDataCheck(engagementId: string): Promise<DataCheck> {
    const res = await fetch(`${API_BASE}/engagements/${engagementId}/data-check`);
    if (!res.ok) throw new Error(await detail(res, "Could not check the client's data"));
    return res.json();
  },

  /** 'First year of trading' ticked or cleared: no opening balances to bring in. */
  async setFirstYear(engagementId: string, firstYear: boolean): Promise<DataCheck> {
    const res = await fetch(`${API_BASE}/engagements/${engagementId}/data-check/first-year`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ first_year: firstYear }),
    });
    if (!res.ok) throw new Error(await detail(res, "Could not save first year of trading"));
    return res.json();
  },

  /** Last year's closing TB, added inside the client: the opening balances. */
  async uploadLastYearTb(engagementId: string, file: File): Promise<DataCheck> {
    const form = new FormData();
    form.append("file", file);
    const res = await fetch(`${API_BASE}/engagements/${engagementId}/data-check/last-year-tb`, { method: "POST", body: form });
    if (!res.ok) throw new Error(await detail(res, "Last year's TB could not be used"));
    return res.json();
  },
};
