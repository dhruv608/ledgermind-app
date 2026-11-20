// One account's ledger in five views: as uploaded, as it is now, lines moved off and onto it, and its journals.
import { API_BASE, fetch } from "./client";

export interface LedgerViewLine {
  key: string;
  date: string | null;
  account: string;
  description: string;
  net: number;
  note?: string;
  /** The software's type ("Invoice", "Bill Payment (Cheque)"), the VAT on the line, the class / tracking label */
  type?: string;
  vat?: number | null;
  label?: string;
}

export interface LedgerMove extends LedgerViewLine {
  from: number | null;
  from_name: string;
  to: number;
  to_name: string;
  how: string;                 // GL scrutiny, Misposting review
  journal_ref: string;
  journal_status: string;      // APPROVED, PROPOSED
  remark?: string;
}

export interface LedgerJournal {
  id: number;
  ref: string;
  description: string;
  effect: number;
  status: string;
  source: string;
  line_move: boolean;
  date: string | null;
}

export interface LedgerViews {
  code: number;
  name: string;
  original: LedgerViewLine[];
  moved_out: LedgerMove[];
  moved_in: LedgerMove[];
  journals: LedgerJournal[];
  current: LedgerViewLine[];
  totals: { original: number; approved_journals: number; current: number; current_lines: number; to_decide: number };
}

/** A contact's documents in the ledger, under a duplicates point: each bill, payment and direct payment */
export interface ContactDocument {
  date: string | null;
  type: string;
  source: string;
  number: string;
  amount: number;
  accounts: string[];
}

export interface ContactLedger {
  contact: string;
  counts: Record<string, number>;
  documents: ContactDocument[];
  more: number;
}

export const ledgerViewsApi = {
  async getPointLedger(engagementId: string, findingId: number): Promise<ContactLedger[]> {
    const res = await fetch(`${API_BASE}/engagements/${engagementId}/point-ledger/${findingId}`);
    if (!res.ok) throw new Error("Could not load the ledger");
    return res.json();
  },

  async getLedgerViews(engagementId: string, code: number): Promise<LedgerViews> {
    const res = await fetch(`${API_BASE}/engagements/${engagementId}/ledger-views?code=${code}`);
    if (!res.ok) throw new Error("Could not load the account's ledger");
    return res.json();
  },
};
