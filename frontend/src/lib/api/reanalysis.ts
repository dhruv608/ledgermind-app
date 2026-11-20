// The re-analysis area: the moves the engine proposes for a job's ledger, and the accountant's decision on each.
import { API_BASE, fetch } from "./client";

export interface ReanalysisLine {
  date: string | null;
  description: string;
  account: string;
  amount: number;
}

/** One merchant's lines that the engine would move from one code to another, for one reason */
export interface ReanalysisGroup {
  key: string;
  merchant: string;
  category: string | null;
  from_code: number;
  from_name: string;
  to_code: number;
  to_name: string;
  reason: string;
  reason_text: string;
  /** propose, journal, accountant query or client query */
  outcome: string;
  band: "High" | "Medium" | "Low";
  confidence: number;
  evidence: Record<string, number>;
  lines: ReanalysisLine[];
  total: number;
  decision: "APPROVED" | "REJECTED" | null;
}

export interface Reanalysis {
  groups: ReanalysisGroup[];
  summary: { moves: number; questions: number; decided: number; unclear_lines: number; lines_read: number };
  version: string;
}

/** One ledger line of a supplier split across accounts */
export interface MispostingLine {
  key: string;
  date: string | null;
  description: string;
  account: string;
  amount: number;
  /** the code it was moved to on this screen, if it was */
  moved_to: number | null;
}

export interface MispostingMove {
  lines: string[];
  to: number;
  remark: string;
  journals: number[];
  at: string;
  total: number;
}

/** A supplier whose lines sit in more than one profit and loss account */
export interface MispostingGroup {
  key: string;
  merchant: string;
  category: string | null;
  recommended: boolean;
  reason: string;
  main_code: number;
  main_name: string;
  accounts: { code: number; name: string; main: boolean; count: number; total: number; lines: MispostingLine[] }[];
  minority_lines: number;
  minority_total: number;
  left: number;
  moves: MispostingMove[];
  ignored: { remark: string; at: string } | null;
  status: "OPEN" | "PART" | "MOVED" | "IGNORED";
}

export interface Mispostings {
  groups: MispostingGroup[];
  summary: { recommended: number; open: number; ignored: number; moved: number; all: number };
}

export interface MispostingDecision {
  merchant_key: string;
  action: "MOVE" | "IGNORE" | "UNDO";
  line_keys?: string[];
  to_code?: number;
  remark?: string;
}

export const reanalysisApi = {
  async getMispostings(engagementId: string): Promise<Mispostings> {
    const res = await fetch(`${API_BASE}/engagements/${engagementId}/mispostings`);
    if (!res.ok) throw new Error((await res.json().catch(() => ({}))).detail || "Could not work out the mispostings");
    return res.json();
  },

  /** Move ticked lines (a remark required), ignore a supplier, or undo; the whole list comes back. */
  async decideMisposting(engagementId: string, decision: MispostingDecision): Promise<Mispostings> {
    const res = await fetch(`${API_BASE}/engagements/${engagementId}/mispostings/decide`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(decision),
    });
    if (!res.ok) throw new Error((await res.json().catch(() => ({}))).detail || "Could not save the decision");
    return res.json();
  },

  async getReanalysis(engagementId: string): Promise<Reanalysis> {
    const res = await fetch(`${API_BASE}/engagements/${engagementId}/reanalysis`);
    if (!res.ok) throw new Error((await res.json().catch(() => ({}))).detail || "Could not work out the re-analysis");
    return res.json();
  },

  async decideReanalysis(engagementId: string, key: string, action: "APPROVE" | "REJECT"): Promise<void> {
    const res = await fetch(`${API_BASE}/engagements/${engagementId}/reanalysis/decide`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ key, action }),
    });
    if (!res.ok) throw new Error((await res.json().catch(() => ({}))).detail || "Could not save the decision");
  },
};
