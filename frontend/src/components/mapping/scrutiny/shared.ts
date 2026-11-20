// Shared parts of GL scrutiny: the list filters, the chart code shape for the Move to picker and small line helpers.
import { ScrutinyLine } from "@/lib/api";

export type Area = "ALL" | "PL" | "BS";
export type Show = "ALL" | "FLAGGED" | "OPEN" | "OK" | "MOVED" | "ASKED";

export const PICKER_FILTERS = [
  { id: "pl", label: "P&L" },
  { id: "bs", label: "Balance sheet" },
];

/** A code of the firm chart, for the Move to picker */
export type ChartCode = { std_code: number; std_name: string; category?: string; financial_class?: string; is_extended?: boolean };
export const isChecked = (l: ScrutinyLine) => l.decision?.status === "OK" || l.decision?.status === "MOVED";
export const codeLabel = (code: number | null) => (code === null ? "—" : String(code).padStart(4, "0"));
