// Shared parts of the balance sheet summary: status labels, the money format, reading a typed amount, and which
// rows the accountant agrees by hand.
import type { ChipTone } from "@/components/ui/status-chip";
import { Reconciliation } from "@/lib/api";
import { formatCurrency } from "@/lib/formatters";

export type StatusFilter = "ALL" | Reconciliation["status"];

// "To agree" is grey, not amber: most balance sheet accounts start there, and the page should not look broken
export const STATUS: Record<Reconciliation["status"], { label: string; tone: ChipTone }> = {
  MATCHED: { label: "Agreed", tone: "success" },
  DIFFERENCE: { label: "Difference", tone: "danger" },
  NEEDS_INPUT: { label: "To agree", tone: "neutral" },
};

export const money = (v: number | null) => (v === null ? "-" : formatCurrency(v, { accountingStyle: true }));

/** "1,234.56", "-1234.56" or "(1,234.56)" as a number; null when it is not one */
export function parseAmount(text: string): number | null {
  const t = text.trim().replace(/[£,\s]/g, "");
  if (!t) return null;
  const negative = /^\(.*\)$/.test(t);
  const n = Number(negative ? t.slice(1, -1) : t);
  return Number.isFinite(n) ? (negative ? -n : n) : null;
}

/** A row the accountant agrees by hand: a figure typed from its document, or a tick that it agrees */
export const byHand = (key: string) => key === "reserves" || key.startsWith("code:") || key.startsWith("far:");
