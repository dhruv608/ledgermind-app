// The job workspace's tabs and checklist steps, and the address helpers that pick the open tab and area.
import type { TBRecord } from "@/types/engagement";

// The tabs, in the order the year-end is done
export type TabId = "data" | "queries" | "setup" | "books" | "accounts" | "inputs" | "review" | "journals" | "recs" | "workbook" | "area" | "papers";
export const TAB_IDS: TabId[] = ["data", "queries", "setup", "books", "accounts", "inputs", "review", "journals", "recs", "workbook", "area", "papers"];
// The area the workspace shows (?tab=area&area=payroll)
export const areaFromUrl = (): string | null =>
  typeof window === "undefined" ? null : new URLSearchParams(window.location.search).get("area");
// The workspace checklist on the left: the same sections, grouped as the job is done
// The most used first: the review (all points, journals, the client's queries, then each area); the files and
// details the job starts from; the balance sheet summary and the workbook to finish
// Costs in the wrong account (re-analysis, mispostings): one Coding review item; links to either open it
export const CODING = ["coding", "reanalysis", "mispostings"];
// The screens whose points, journals or figures LM redoes when it checks again: covered while it does
export const REDONE: string[] = ["review", "area", "journals", "papers", "recs", "workbook"];
// The job's five steps, in the order the work is done: set up, the trial balance, the working
// papers, the questions and journals, then finish. Nothing is shown twice: each balance is worked in its working paper
export type Step = { label: string; ids: TabId[]; coding?: boolean; papers?: boolean };
export const CHECKLIST: Step[] = [
  // No separate "VAT & payroll data" step: the VAT returns are typed or uploaded on the VAT area's Evidence
  // tab, the payroll report and registers on their areas' Evidence tabs, last year's WP and next year's ledger on Files
  { label: "1 · Set up", ids: ["data", "setup", "books"] },
  { label: "2 · Trial balance", ids: ["accounts"], coding: true },
  { label: "3 · Working papers", ids: [], papers: true },
  { label: "4 · Queries and journals", ids: ["queries", "journals", "review"] },
  { label: "5 · Finish", ids: ["recs", "workbook"] },
];
// The tab named in the address (?tab=setup), so a refresh or a shared link opens the same tab
export const tabFromUrl = (): TabId | null => {
  if (typeof window === "undefined") return null;
  const t = new URLSearchParams(window.location.search).get("tab") as TabId | null;
  return t && TAB_IDS.includes(t) ? t : null;
};

// An account with a balance or movement whose mapping still needs the accountant (a nil account never does)
export const needsReview = (r: TBRecord) =>
  (r.mapping_status === "NEEDS_REVIEW" || r.mapping_status === "UNMAPPED") &&
  [r.net_amount, r.debit_amount, r.credit_amount].some((v) => Math.abs(Number(v || 0)) >= 0.005);
