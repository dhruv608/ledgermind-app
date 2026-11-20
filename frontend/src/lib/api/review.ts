// The review: points, journals, capital allowance choices.
import type { AuditFinding, ProposedJournal, ManualJournalLineInput } from "@/types/engagement";
import { API_BASE, SetupGapsError, fetch } from "./client";

/** One addition this year: the app's suggested capital allowance and the accountant's choice. */
export interface CapitalAllowanceAsset {
  key: string;
  group: string;
  description: string;
  cost: number;
  when: string | null;
  suggested: string;
  choice: string;
}

export interface CapitalAllowances {
  assets: CapitalAllowanceAsset[];
  treatments: Record<string, string>;
  allowances: { label: string; amount: number }[];
  crosses_april_2026: boolean;
  main_rate_rule: string;
}

export const reviewApi = {
  async getAuditFindings(engagementId: string): Promise<AuditFinding[]> {
    const res = await fetch(`${API_BASE}/audit/${engagementId}`);
    if (!res.ok) throw new Error("Failed to load audit findings");
    const data = await res.json();
    return data.findings || [];
  },

  async clearAuditFinding(findingId: number, note?: string): Promise<void> {
    const res = await fetch(`${API_BASE}/audit/${findingId}/clear`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ note: note || null }),
    });
    if (!res.ok) throw new Error((await res.json().catch(() => ({}))).detail || "The point could not be cleared. Try again.");
  },

  async getCapitalAllowances(engagementId: string): Promise<CapitalAllowances> {
    const res = await fetch(`${API_BASE}/engagements/${engagementId}/capital-allowances`);
    if (!res.ok) throw new Error("Failed to load the capital allowances");
    return res.json();
  },

  async saveCapitalAllowances(engagementId: string, choices: Record<string, string>, mainRateRule?: string): Promise<CapitalAllowances> {
    const res = await fetch(`${API_BASE}/engagements/${engagementId}/capital-allowances`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ choices, main_rate_rule: mainRateRule ?? null }),
    });
    if (!res.ok) throw new Error("Failed to save the capital allowance choices");
    return res.json();
  },

  async runSequentialReview(engagementId: string): Promise<any> {
    const res = await fetch(`${API_BASE}/audit/${engagementId}/run-sequential`, {
      method: "POST",
    });
    if (res.status === 409) {
      const err = await res.json().catch(() => null);
      throw new SetupGapsError(err?.detail?.message || "Finish the client setup first", err?.detail?.gaps || []);
    }
    if (!res.ok) throw new Error("Failed to run sequential statutory review");
    return res.json();
  },

  async getProposedJournals(engagementId: string): Promise<ProposedJournal[]> {
    const res = await fetch(`${API_BASE}/audit/${engagementId}/journals`);
    if (!res.ok) return [];
    return res.json();
  },

  async actOnJournal(journalId: number, action: "APPROVE" | "REJECT"): Promise<any> {
    const res = await fetch(`${API_BASE}/audit/journals/${journalId}/action`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ journal_id: journalId, action }),
    });
    if (!res.ok) throw new Error((await res.json().catch(() => ({}))).detail || "The journal could not be saved. Try again.");
    return res.json();
  },

  /** An accrual or prepayment the app proposed, with the accountant's amount: saved as their own line, the proposal replaced */
  async editJournalAsLine(journalId: number, amount: number, description: string): Promise<any> {
    const res = await fetch(`${API_BASE}/audit/journals/${journalId}/edit-as-line`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ amount, description }),
    });
    if (!res.ok) throw new Error((await res.json().catch(() => ({}))).detail || "Not saved");
    return res.json();
  },

  /** Sign-offs on the job's points: {finding id: [{role, initials, signed_at}]} */
  async getSignoffs(engagementId: string): Promise<Record<string, PointSignoff[]>> {
    const res = await fetch(`${API_BASE}/audit/${engagementId}/signoffs`);
    if (!res.ok) return {};
    return res.json();
  },

  async signOffPoint(engagementId: string, findingId: number, role: SignoffRole, clear = false): Promise<Record<string, PointSignoff[]>> {
    const res = await fetch(`${API_BASE}/audit/${engagementId}/signoffs`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ finding_id: findingId, role, clear }),
    });
    if (!res.ok) throw new Error((await res.json().catch(() => ({}))).detail || "Could not save the sign-off");
    return res.json();
  },

  /** Sign-offs on whole areas: {area: [{role, initials, signed_at, fingerprint}]} */
  async getAreaSignoffs(engagementId: string): Promise<Record<string, AreaSignoff[]>> {
    const res = await fetch(`${API_BASE}/audit/${engagementId}/area-signoffs`);
    if (!res.ok) return {};
    return res.json();
  },

  /** Sign an area off in a role (in order: preparer, reviewer, partner), or take it off; every area's come back. */
  async signOffArea(engagementId: string, area: string, role: SignoffRole, clear = false, fingerprint = ""): Promise<Record<string, AreaSignoff[]>> {
    const res = await fetch(`${API_BASE}/audit/${engagementId}/area-signoffs`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ area, role, clear, fingerprint }),
    });
    if (!res.ok) throw new Error((await res.json().catch(() => ({}))).detail || "Could not save the sign-off");
    return res.json();
  },

  async createManualJournal(engagementId: string, description: string, lines: ManualJournalLineInput[]): Promise<ProposedJournal> {
    const res = await fetch(`${API_BASE}/audit/${engagementId}/journals`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ description, lines }),
    });
    if (!res.ok) {
      const err = await res.json().catch(() => null);
      throw new Error(err?.detail || "Failed to save journal");
    }
    return res.json();
  },

  async updateManualJournal(journalId: number, description: string, lines: ManualJournalLineInput[]): Promise<ProposedJournal> {
    const res = await fetch(`${API_BASE}/audit/journals/${journalId}`, {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ description, lines }),
    });
    if (!res.ok) {
      const err = await res.json().catch(() => null);
      throw new Error(err?.detail || "Failed to save journal");
    }
    return res.json();
  },

  async deleteJournal(journalId: number): Promise<void> {
    const res = await fetch(`${API_BASE}/audit/journals/${journalId}`, { method: "DELETE" });
    if (!res.ok) {
      const err = await res.json().catch(() => null);
      throw new Error(err?.detail || "Failed to delete journal");
    }
  },

  /** Save the review points as a PDF report or an Excel list (include: all, open, screen or screen_open). */
  async downloadReview(engagementId: string, opts: { format: "pdf" | "xlsx"; include: string; stage?: string; severity?: string }): Promise<void> {
    const q = new URLSearchParams({ format: opts.format, include: opts.include, stage: opts.stage || "", severity: opts.severity || "" });
    const res = await fetch(`${API_BASE}/audit/${engagementId}/export?${q}`);
    if (!res.ok) throw new Error("Could not make the download");
    const name = /filename="([^"]+)"/.exec(res.headers.get("Content-Disposition") || "")?.[1] || `Review points.${opts.format}`;
    const url = URL.createObjectURL(await res.blob());
    const a = Object.assign(document.createElement("a"), { href: url, download: name });
    document.body.appendChild(a);
    a.click();
    a.remove();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
  },
};

export type SignoffRole = "PREPARER" | "REVIEWER" | "PARTNER";
export interface PointSignoff { role: SignoffRole; initials: string | null; signed_at: string | null }
/** A whole area's sign-off; fingerprint: the area's points when it was signed */
export interface AreaSignoff extends PointSignoff { fingerprint: string | null }
