"use client";

import { useEffect, useMemo, useState } from "react";
import { toast } from "@/lib/notify";
import { Loader2, Plus, Trash2 } from "lucide-react";
import { api } from "@/lib/api";
import type { AdjustmentLine, Adjustments } from "@/lib/api";
import { Button } from "@/components/ui/button";
import { CustomSelect } from "@/components/ui/custom-select";
import { SkeletonRows } from "@/components/common/SkeletonRows";
import { cn } from "@/lib/utils";
import { formatCurrency } from "@/lib/formatters";
import { PrepaymentInvoice } from "@/components/review/workpapers/PrepaymentInvoice";

type ChartCode = { std_code: number; std_name: string; category?: string; financial_class?: string; is_extended?: boolean };

const KINDS = [
  { value: "ACCRUAL", label: "Accrual" },
  { value: "PREPAYMENT", label: "Prepayment" },
];
const inputClass =
  "w-full rounded-md border border-slate-300 bg-white px-2 py-1 text-xs text-slate-800 focus:outline-none focus:ring-2 focus:ring-teal-200";
const money = (n: number) => formatCurrency(n);
const blank = (kind: AdjustmentLine["kind"] = "ACCRUAL"): AdjustmentLine => ({ kind, description: "", cost_code: 0, amount: 0 });

/** Accruals and prepayments line by line: last year's lines are entered once and carried forward. Last year's
 * lines are reversed to their cost this year; this year's are booked at the year end. When last year's client is in
 * the app its lines are used and shown read only. Saving runs the checks again, which propose the journals. With a
 * kind, only that kind's lines show (prepayments and accruals are separate working papers); the other kind's lines
 * are kept as they are when saving. */
export function AdjustmentsPanel({ engagementId, onSaved, kind, yearEnd }: {
  engagementId: string;
  onSaved?: () => void;
  kind?: AdjustmentLine["kind"];
  /** The year end (yyyy-mm-dd): a prepayment's part after it is worked out from its invoice period */
  yearEnd?: string;
}) {
  const [data, setData] = useState<Adjustments | null>(null);
  const [lastYear, setLastYear] = useState<AdjustmentLine[]>([]);
  const [thisYear, setThisYear] = useState<AdjustmentLine[]>([]);
  const [chart, setChart] = useState<ChartCode[]>([]);
  const [dirty, setDirty] = useState(false);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const show = (d: Adjustments) => {
    setData(d);
    setLastYear(d.last_year);
    setThisYear(d.this_year);
    setDirty(false);
  };
  useEffect(() => {
    api.getAdjustments(engagementId).then(show).catch((e) => setError(e.message));
    api.getMasterCOA().then((c) => setChart(c as ChartCode[])).catch(() => setChart([]));
  }, [engagementId]);

  // Costs only: an accrual or prepayment is reversed to, or taken from, a profit and loss account
  const costOptions = useMemo(
    () => chart.filter((c) => c.financial_class === "Profit and Loss" && !c.is_extended)
      .map((c) => ({ value: String(c.std_code), label: `${String(c.std_code).padStart(4, "0")} ${c.std_name}`, description: c.category })),
    [chart],
  );

  const valid = (l: AdjustmentLine) => l.cost_code > 0 && l.amount > 0;
  // The lines shown: one kind's, or all
  const mine = (l: AdjustmentLine) => !kind || l.kind === kind;
  const word = kind === "PREPAYMENT" ? "Prepayments" : kind === "ACCRUAL" ? "Accruals" : "Accruals and prepayments";
  const save = async () => {
    const bad = [...lastYear, ...thisYear].filter((l) => !valid(l));
    if (bad.length) {
      toast.error("Each line needs a cost account and an amount");
      return;
    }
    setSaving(true);
    try {
      show(await api.saveAdjustments(engagementId, thisYear, data?.last_year_editable ? lastYear : null));
      await api.startChecks(engagementId).catch(() => undefined);
      toast.success(`${word} saved`, { description: "The checks run again and propose the journals." });
      onSaved?.();
    } catch (e: any) {
      toast.error(e.message);
    } finally {
      setSaving(false);
    }
  };

  if (error) return <p className="rounded-xl border border-rose-200 bg-white px-4 py-3 text-xs text-rose-700">{error}</p>;
  if (!data) {
    return (
      <div className="overflow-hidden rounded-xl border border-slate-200 bg-white">
        <SkeletonRows rows={3} columns={4} label={`Reading the ${word.toLowerCase()}`} />
      </div>
    );
  }

  const table = (title: string, help: string, all: AdjustmentLine[], set: (l: AdjustmentLine[]) => void, editable: boolean) => {
    // Each shown line with its place in the whole list, so an edit or a removal leaves the other kind's lines alone
    const shown = all.map((l, at) => ({ l, at })).filter(({ l }) => mine(l));
    const change = (at: number, patch: Partial<AdjustmentLine>) => {
      set(all.map((l, j) => (j === at ? { ...l, ...patch } : l)));
      setDirty(true);
    };
    const total = (k: string) => all.filter((l) => l.kind === k).reduce((t, l) => t + (l.amount || 0), 0);
    return (
      <div className="border-t border-slate-100">
        <div className="flex flex-wrap items-baseline justify-between gap-2 px-4 pt-3">
          <p className="text-xs font-semibold text-slate-800">{title}</p>
          <p className="text-[11px] text-slate-500">
            {kind ? `Total ${money(total(kind))}` : `Accruals ${money(total("ACCRUAL"))} · Prepayments ${money(total("PREPAYMENT"))}`}
          </p>
        </div>
        <p className="px-4 pt-0.5 text-[11px] text-slate-500">{help}</p>
        <table className="mt-2 w-full table-fixed text-xs">
          {shown.length > 0 && (
            <thead className="bg-slate-50 text-[10.5px] uppercase tracking-wide text-slate-500">
              <tr className="text-left">
                {!kind && <th className="w-32 px-4 py-1.5 font-semibold">Type</th>}
                <th className={cn("py-1.5 font-semibold", kind ? "px-4" : "px-2")}>What it is for</th>
                <th className="w-[34%] px-2 py-1.5 font-semibold">Cost account</th>
                <th className="w-28 px-2 py-1.5 text-right font-semibold">Amount</th>
                {editable && <th className="w-10" />}
              </tr>
            </thead>
          )}
          <tbody className="divide-y divide-slate-100">
            {shown.map(({ l, at: i }) => [
              <tr key={i}>
                {!kind && (
                  <td className="px-4 py-1">
                    {editable ? (
                      <CustomSelect fullWidth size="sm" value={l.kind} options={KINDS}
                                    onChange={(v) => change(i, { kind: v as AdjustmentLine["kind"] })} />
                    ) : KINDS.find((k) => k.value === l.kind)?.label}
                  </td>
                )}
                <td className={cn("py-1", kind ? "px-4" : "px-2")}>
                  {editable ? (
                    <input value={l.description} placeholder="e.g. Electricity for March" className={inputClass}
                           onChange={(e) => change(i, { description: e.target.value })} />
                  ) : l.description}
                </td>
                <td className="px-2 py-1">
                  {editable ? (
                    <CustomSelect fullWidth size="sm" searchable searchPlaceholder="Type a code or name"
                                  value={l.cost_code ? String(l.cost_code) : ""} placeholder="Pick the cost…" options={costOptions}
                                  onChange={(v) => change(i, { cost_code: parseInt(String(v ?? "0"), 10) || 0 })} />
                  ) : `${String(l.cost_code).padStart(4, "0")} ${l.cost_name || ""}`}
                </td>
                <td className="px-2 py-1 text-right">
                  {editable ? (
                    <input type="number" min={0} step="any" value={l.amount || ""} placeholder="0.00"
                           className={cn(inputClass, "text-right")}
                           onChange={(e) => change(i, { amount: parseFloat(e.target.value) || 0 })} />
                  ) : <span className="font-mono tabular-nums">{money(l.amount)}</span>}
                </td>
                {editable && (
                  <td className="py-1 pr-3 text-right">
                    <button type="button" aria-label="Remove the line" title="Remove the line"
                            onClick={() => { set(all.filter((_, j) => j !== i)); setDirty(true); }}
                            className="rounded p-1 text-slate-400 hover:bg-rose-50 hover:text-rose-600">
                      <Trash2 className="h-3.5 w-3.5" />
                    </button>
                  </td>
                )}
              </tr>,
              // A prepayment's invoice under it: number, date, amount, the period, and the part after the year end
              l.kind === "PREPAYMENT" && (editable || l.invoice_amount || l.invoice_number) ? (
                <tr key={`${i}-invoice`} className="border-t-0">
                  <td colSpan={(kind ? 3 : 4) + (editable ? 1 : 0)} className="px-4 pb-2 pt-0">
                    <PrepaymentInvoice line={l} yearEnd={yearEnd} editable={editable} onChange={(patch) => change(i, patch)} />
                  </td>
                </tr>
              ) : null,
            ])}
          </tbody>
        </table>
        {editable && (
          <button type="button" onClick={() => { set([...all, blank(kind)]); setDirty(true); }}
                  className="mx-4 my-2 inline-flex items-center gap-1 text-[11px] font-medium text-teal-700 hover:underline">
            <Plus className="h-3.5 w-3.5" /> Add a line
          </button>
        )}
        {!editable && <div className="h-2" />}
      </div>
    );
  };

  return (
    <div className="overflow-hidden rounded-xl border border-slate-200 bg-white shadow-2xs">
      <div className="flex flex-wrap items-start justify-between gap-3 px-4 py-3">
        <div>
          <p className="text-xs font-bold text-slate-900">{word}, line by line</p>
          <p className="mt-0.5 text-[11px] text-slate-500">
            {kind === "PREPAYMENT" ? `The books hold prepayments ${money(data.in_books.prepayments)}.`
              : kind === "ACCRUAL" ? `The books hold accruals ${money(data.in_books.accruals)}.`
              : `The books hold accruals ${money(data.in_books.accruals)} and prepayments ${money(data.in_books.prepayments)}.`}
            Enter last year&apos;s once; next year they come forward by themselves.
          </p>
        </div>
        <Button type="button" variant="primary" size="sm" className="h-7 px-3 text-xs" onClick={save} disabled={!dirty || saving}>
          {saving && <Loader2 className="mr-1 h-3.5 w-3.5 animate-spin" />} Save
        </Button>
      </div>
      {table(
        "Last year's",
        data.last_year_editable
          ? `From last year's ${word.toLowerCase()} schedule (ask the client or last year's accountant): each is reversed to its cost this year.`
          : "From last year's job in the app: each is reversed to its cost this year.",
        lastYear, setLastYear, data.last_year_editable,
      )}
      {table("This year's", kind === "PREPAYMENT" ? "Payments made this year that cover next year."
               : kind === "ACCRUAL" ? "Bills for this year that came after the year end, or costs of this year not billed yet."
               : "Bills for this year that came after the year end (accruals), and payments covering next year (prepayments).",
             thisYear, setThisYear, true)}
    </div>
  );
}
