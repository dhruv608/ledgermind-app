"use client";

import type { AdjustmentLine } from "@/lib/api";
import { formatCurrency } from "@/lib/formatters";
import { cn } from "@/lib/utils";

/**
 * The invoice behind a prepayment (invoice number and date, the period it covers): with the invoice amount and the
 * period, the part after the year end is worked out by days, and can be used as the line's amount.
 */
const field = "w-full rounded-md border border-slate-300 bg-white px-2 py-1 text-[11px] text-slate-800 focus:outline-none focus:ring-2 focus:ring-teal-200";
const days = (a: string, b: string) => Math.round((Date.parse(`${b}T00:00:00Z`) - Date.parse(`${a}T00:00:00Z`)) / 86400000);

/** The part of the invoice for the days after the year end (null: not enough to work it out) */
export function prepaidPart(l: AdjustmentLine, yearEnd?: string): { amount: number; after: number; total: number } | null {
  if (!yearEnd || !l.invoice_amount || !l.period_from || !l.period_to) return null;
  const total = days(l.period_from, l.period_to) + 1;
  if (total <= 0) return null;
  const after = Math.max(0, Math.min(total, days(yearEnd, l.period_to)));
  return { amount: Math.round((l.invoice_amount * after) / total * 100) / 100, after, total };
}

export function PrepaymentInvoice({ line: l, yearEnd, editable, onChange }: {
  line: AdjustmentLine;
  yearEnd?: string;
  editable: boolean;
  onChange: (patch: Partial<AdjustmentLine>) => void;
}) {
  const part = prepaidPart(l, yearEnd);
  const input = (k: keyof AdjustmentLine, label: string, type: "text" | "date" | "number") => (
    <label className="block min-w-0 space-y-0.5">
      <span className="text-[10px] text-slate-400">{label}</span>
      {editable ? (
        <input type={type} step="any" value={(l[k] as string | number | null | undefined) ?? ""} className={cn(field, type === "number" && "text-right")}
               onChange={(e) => onChange({ [k]: type === "number" ? (e.target.value === "" ? null : parseFloat(e.target.value)) : e.target.value || null })} />
      ) : <span className="block text-[11px] text-slate-600">{(l[k] as string | number | null | undefined) ?? "-"}</span>}
    </label>
  );
  return (
    <div className="grid items-end gap-2 sm:grid-cols-[1fr_1fr_1fr_1fr_1fr_auto]">
      {input("invoice_number", "Invoice number", "text")}
      {input("invoice_date", "Invoice date", "date")}
      {input("invoice_amount", "Invoice amount", "number")}
      {input("period_from", "Period from", "date")}
      {input("period_to", "Period to", "date")}
      <div className="pb-1 text-[11px] text-slate-600">
        {part ? (
          <>
            {part.after} of {part.total} days after the year end: <span className="font-semibold">{formatCurrency(part.amount)}</span>
            {editable && Math.abs(part.amount - (l.amount || 0)) >= 0.005 && (
              <button type="button" className="ml-1.5 font-semibold text-teal-700 hover:underline" onClick={() => onChange({ amount: part.amount })}>Use</button>
            )}
          </>
        ) : <span className="text-slate-400">Invoice amount and period work out the prepaid part</span>}
      </div>
    </div>
  );
}
