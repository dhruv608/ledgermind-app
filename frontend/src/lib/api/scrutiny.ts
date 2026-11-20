// GL scrutiny (Accounts tab): the ledger one code at a time, each line marked OK or moved by a proposed journal.
import { API_BASE, fetch } from "./client";

/** One code with ledger lines on the scrutiny list ("none": lines whose account has no code) */
export interface ScrutinyAccount {
  code: number | null;
  key: string;
  name: string;
  pl: boolean;
  /** The client's account names the lines came from (first five) */
  accounts: string[];
  lines: number;
  checked: number;
  moved: number;
  /** Lines with a question to the client */
  asked: number;
  /** Flagged lines not checked yet */
  flagged: number;
  total: number;
}

export interface ScrutinyAccounts {
  accounts: ScrutinyAccount[];
  lines: number;
  checked: number;
  flagged: number;
}

/** Why a line is worth reading first: the review's asset, pattern and related party checks, a line on the opposite
 *  side of its account, or a round sum paid once */
export interface ScrutinyFlag {
  kind: "asset" | "unusual" | "related" | "side" | "round";
  label: string;
  text: string;
  /** asset: the additions code the asset words point to */
  suggested_code?: number | null;
}

/** What was decided about a line: OK, or moved by a journal (MOVE_REJECTED: its journal was rejected); null with a
 *  question: only asked about so far */
export interface ScrutinyDecision {
  status: "OK" | "MOVED" | "MOVE_REJECTED" | null;
  /** The question to the client about the line (a query on the Queries tab) */
  question?: string;
  to_code?: number;
  to_name?: string;
  journal_id?: number;
  journal_ref?: string;
  journal_status?: string;
}

export interface ScrutinyLine {
  key: string;
  date: string | null;
  account: string;
  description: string;
  reference: string;
  source: string;
  debit: number;
  credit: number;
  net: number;
  vat: number | null;
  decision: ScrutinyDecision | null;
  flags: ScrutinyFlag[];
}

export interface ScrutinyLines {
  code: number | null;
  key: string;
  name: string;
  lines: ScrutinyLine[];
}

async function post<T>(url: string, body: unknown, failed: string): Promise<T> {
  const res = await fetch(url, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
  if (!res.ok) throw new Error((await res.json().catch(() => ({}))).detail || failed);
  return res.json();
}

export const scrutinyApi = {
  async getScrutinyAccounts(engagementId: string): Promise<ScrutinyAccounts> {
    const res = await fetch(`${API_BASE}/engagements/${engagementId}/scrutiny`);
    if (!res.ok) throw new Error((await res.json().catch(() => ({}))).detail || "Could not read the ledger");
    return res.json();
  },

  async getScrutinyLines(engagementId: string, codeKey: string): Promise<ScrutinyLines> {
    const res = await fetch(`${API_BASE}/engagements/${engagementId}/scrutiny/lines?code=${encodeURIComponent(codeKey)}`);
    if (!res.ok) throw new Error((await res.json().catch(() => ({}))).detail || "Could not read the ledger lines");
    return res.json();
  },

  /** Marks lines OK (ok=false takes the OK off) */
  async checkScrutinyLines(engagementId: string, keys: string[], ok = true): Promise<{ changed: number }> {
    return post(`${API_BASE}/engagements/${engagementId}/scrutiny/check`, { keys, ok }, "Could not save");
  },

  /** Proposes a journal moving one line to another code */
  async moveScrutinyLine(engagementId: string, key: string, toCode: number): Promise<{ journal_id: number; journal_ref: string }> {
    return post(`${API_BASE}/engagements/${engagementId}/scrutiny/move`, { key, to_code: toCode }, "Could not move the line");
  },

  /** Saves a question to the client about one line (a query on the Queries tab); "" takes it off */
  async askScrutinyLine(engagementId: string, key: string, question: string): Promise<{ status: string }> {
    return post(`${API_BASE}/engagements/${engagementId}/scrutiny/ask`, { key, question }, "Could not save the question");
  },

  /** Takes a move back (its journal is deleted while not approved) */
  async undoScrutinyMove(engagementId: string, key: string): Promise<{ status: string }> {
    return post(`${API_BASE}/engagements/${engagementId}/scrutiny/undo-move`, { key }, "Could not undo the move");
  },
};
