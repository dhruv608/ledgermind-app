"use client";

import { useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "@/lib/api";
import type { AreaNote, PointSignoff } from "@/lib/api";
import type { EvidenceByArea } from "@/lib/api/evidence";

/**
 * One job's data in the shared store: each piece has one key, is asked for once and shared by every screen that shows
 * it. After an action, the screen writes the server's answer into the store (setData) or marks the piece stale
 * (invalidate), so only what changed is asked for again.
 */
export const jobKeys = {
  all: (id: string) => ["job", id] as const,
  signoffs: (id: string) => ["job", id, "signoffs"] as const,
  notes: (id: string) => ["job", id, "notes"] as const,
  rollforward: (id: string, codes: number[]) => ["job", id, "rollforward", codes.join(",")] as const,
  fixedAssets: (id: string) => ["job", id, "rollforward", "fixed-assets"] as const,
  assetRegister: (id: string) => ["job", id, "asset-register"] as const,
  customPapers: (id: string) => ["job", id, "custom-papers"] as const,
  jobDetails: (id: string) => ["job", id, "job-details"] as const,
  stockLines: (id: string) => ["job", id, "stock-lines"] as const,
  etb: (id: string) => ["job", id, "rollforward", "etb"] as const,
  journals: (id: string) => ["job", id, "rollforward", "journals"] as const,
  taxCalculation: (id: string) => ["job", id, "rollforward", "tax-calculation"] as const,
  reserves: (id: string) => ["job", id, "rollforward", "reserves"] as const,
  salesRec: (id: string) => ["job", id, "rollforward", "sales-reconciliation"] as const,
  payrollSummary: (id: string) => ["job", id, "payroll-summary"] as const,
  bankStatement: (id: string, code: number) => ["job", id, "rollforward", "bank-statement", code] as const,
  tradeAdjustments: (id: string, side: string) => ["job", id, "rollforward", "trade-adjustments", side] as const,
  ledger: (id: string, code: number) => ["job", id, "ledger", code] as const,
  evidence: (id: string) => ["job", id, "evidence"] as const,
};

/** Net wages, PAYE / NI and pension month by month, and the pay costs against the payroll report. version: changes
 *  when the journals do, so the figures follow an approved journal. */
export function usePayrollMonths(id: string, version = "") {
  return useQuery({ queryKey: [...jobKeys.all(id), "payroll-months", version], queryFn: () => api.getPayrollMonths(id) });
}

/** The VAT returns (boxes 1 to 9 by period) and what was paid against each */
export function useVatReturns(id: string, version = "") {
  return useQuery({ queryKey: [...jobKeys.all(id), "vat-returns", version], queryFn: () => api.getVatReturns(id) });
}
export function useVatPaid(id: string, version = "") {
  return useQuery({ queryKey: [...jobKeys.all(id), "vat-paid", version], queryFn: () => api.getVatReturnsPaid(id) });
}

/** The documents kept with each area (Evidence tabs, Add document) */
export function useEvidence(id: string) {
  return useQuery({ queryKey: jobKeys.evidence(id), queryFn: () => api.getEvidence(id) });
}

/** The sign-offs on each review point (prepared, reviewed, approved), keyed by the point's id */
export function useSignoffs(id: string) {
  return useQuery({ queryKey: jobKeys.signoffs(id), queryFn: () => api.getSignoffs(id) });
}

/** The notes on the job's areas and points */
export function useNotes(id: string) {
  return useQuery({ queryKey: jobKeys.notes(id), queryFn: () => api.getNotes(id) });
}

/** One balance sheet account's year: opening, this year's lines by type, journals, closing */
export function useRollforward(id: string, codes: number[], enabled = true) {
  return useQuery({ queryKey: jobKeys.rollforward(id, codes), queryFn: () => api.getRollforward(id, codes), enabled: enabled && codes.length > 0 });
}

/** The fixed assets by class (cost, depreciation, NBV); refreshed with the roll-forwards when figures change */
export function useFixedAssetSchedule(id: string) {
  return useQuery({ queryKey: jobKeys.fixedAssets(id), queryFn: () => api.getFixedAssetSchedule(id) });
}

/** The Adjustments block under the trade debtors / creditors T */
export function useTradeAdjustments(id: string, side: "customer" | "supplier", enabled = true) {
  return useQuery({ queryKey: jobKeys.tradeAdjustments(id, side), queryFn: () => api.getTradeAdjustments(id, side), enabled });
}

/** Sales per the VAT returns to sales in the P&L */
export function useSalesReconciliation(id: string) {
  return useQuery({ queryKey: jobKeys.salesRec(id), queryFn: () => api.getSalesReconciliation(id) });
}

/** The payroll month by month from the payroll reports (they change only when a report is added) */
export function usePayrollSummary(id: string) {
  return useQuery({ queryKey: jobKeys.payrollSummary(id), queryFn: () => api.getPayrollSummary(id) });
}

/** A bank account's statement lines against its ledger */
export function useBankStatement(id: string, code: number, enabled = true) {
  return useQuery({ queryKey: jobKeys.bankStatement(id, code), queryFn: () => api.getBankStatement(id, code), enabled });
}

/** The asset register asset by asset */
export function useAssetRegister(id: string) {
  return useQuery({ queryKey: jobKeys.assetRegister(id), queryFn: () => api.getAssetRegister(id) });
}

/** The corporation tax computation line by line */
export function useTaxCalculation(id: string) {
  return useQuery({ queryKey: jobKeys.taxCalculation(id), queryFn: () => api.getTaxCalculation(id) });
}

/** Retained earnings this year and last */
export function useReserves(id: string) {
  return useQuery({ queryKey: jobKeys.reserves(id), queryFn: () => api.getReserves(id) });
}

/** The working papers the accountant added (every area's) */
export function useCustomPapers(id: string) {
  return useQuery({ queryKey: jobKeys.customPapers(id), queryFn: () => api.getCustomPapers(id) });
}

/** The extended trial balance by code (this year, journals, last year) */
export function useEtb(id: string) {
  return useQuery({ queryKey: jobKeys.etb(id), queryFn: () => api.getEtb(id) });
}

/** Every journal of the job (proposed, approved, rejected) */
export function useProposedJournals(id: string) {
  return useQuery({ queryKey: jobKeys.journals(id), queryFn: () => api.getProposedJournals(id) });
}

/** The job's own details: pack dates, job dates, who works on it */
export function useJobDetails(id: string) {
  return useQuery({ queryKey: jobKeys.jobDetails(id), queryFn: () => api.getJobDetails(id) });
}

/** The closing stock line by line */
export function useStockLines(id: string) {
  return useQuery({ queryKey: jobKeys.stockLines(id), queryFn: () => api.getStockLines(id) });
}

/** Every ledger line on one firm code, as it is now */
export function useLedger(id: string, code: number, enabled = true) {
  return useQuery({ queryKey: jobKeys.ledger(id, code), queryFn: () => api.getLedgerViews(id, code), enabled });
}

/** Writes an action's answer into the store, or marks a piece to ask for again */
export function useJobStore(id: string) {
  const qc = useQueryClient();
  return {
    setSignoffs: (next: Record<string, PointSignoff[]>) => qc.setQueryData(jobKeys.signoffs(id), next),
    setNotes: (next: AreaNote[]) => qc.setQueryData(jobKeys.notes(id), next),
    setEvidence: (next: EvidenceByArea) => qc.setQueryData(jobKeys.evidence(id), next),
    /** Journals or the books changed: the figures worked out from them are asked for again when next shown */
    figuresChanged: () => {
      qc.invalidateQueries({ queryKey: [...jobKeys.all(id), "rollforward"] });
      qc.invalidateQueries({ queryKey: [...jobKeys.all(id), "ledger"] });
    },
    refresh: (part: "signoffs" | "notes") => qc.invalidateQueries({ queryKey: jobKeys[part](id) }),
  };
}
