"use client";

import { useMemo, useState } from "react";
import { Loader2 } from "lucide-react";
import { toast } from "@/lib/notify";
import type { CustomPaper } from "@/lib/api";
import { api } from "@/lib/api";
import { Button } from "@/components/ui/button";
import { Fig, FigRow, wp } from "@/components/review/area/WorkpaperParts";
import { atYearEnd, schedule, type LoanTerms } from "@/components/review/workpapers/added/loanSchedule";
import { cn } from "@/lib/utils";

/** A loan schedule paper: the terms, the year-end split, then each month. */
const { money, th, num } = wp;
const field = "w-full rounded-md border border-slate-300 bg-white px-2 py-1 text-xs text-slate-800 focus:outline-none focus:ring-2 focus:ring-teal-200";
const read = (note: string): LoanTerms => {
  try {
    const t = JSON.parse(note || "{}");
    return { amount: Number(t.amount) || 0, rate: Number(t.rate) || 0, months: Number(t.months) || 0, start: t.start || "" };
  } catch {
    return { amount: 0, rate: 0, months: 0, start: "" };
  }
};
const day = (iso: string) => iso.split("-").reverse().join("/");

export function LoanScheduleView({ engagementId, paper, onSaved, yearEnd }: {
  engagementId: string;
  paper: CustomPaper;
  onSaved: () => void;
  yearEnd?: string;
}) {
  const [t, setT] = useState<LoanTerms>(read(paper.note));
  const [saving, setSaving] = useState(false);
  const rows = useMemo(() => schedule(t), [t]);
  const year = yearEnd && rows.length ? atYearEnd(rows, t.amount, yearEnd) : null;
  const dirty = JSON.stringify(t) !== JSON.stringify(read(paper.note));
  const save = async () => {
    setSaving(true);
    try {
      await api.updateCustomPaper(engagementId, paper.id, { note: JSON.stringify(t) });
      onSaved();
    } catch (e) {
      toast.error((e as Error).message);
    } finally {
      setSaving(false);
    }
  };
  const input = (k: keyof LoanTerms, label: string, type: "number" | "date" = "number") => (
    <label className="block space-y-1">
      <span className="text-[11px] font-semibold text-slate-600">{label}</span>
      <input type={type} step="any" value={t[k] || ""} className={cn(field, type === "number" && "text-right")}
             onChange={(e) => setT({ ...t, [k]: type === "number" ? parseFloat(e.target.value) || 0 : e.target.value })} />
    </label>
  );
  return (
    <div className="space-y-3">
      <div className="grid items-end gap-3 sm:grid-cols-5">
        {input("amount", "Loan amount (£)")}
        {input("rate", "Interest rate (% a year)")}
        {input("months", "Term (months)")}
        {input("start", "Start date", "date")}
        <Button variant="primary" size="sm" className="h-8 text-xs" disabled={!dirty || saving} onClick={save}>
          {saving && <Loader2 className="mr-1.5 h-3.5 w-3.5 animate-spin" />} Save
        </Button>
      </div>
      {year && (
        <FigRow>
          <Fig label="Interest for the year" value={money(year.interest)} />
          <Fig label="Balance at the year end" value={money(year.closing)} />
          <Fig label="Due within one year" value={money(year.withinYear)} />
          <Fig label="Due after one year" value={money(year.afterYear)} />
        </FigRow>
      )}
      {rows.length > 0 ? (
        <div className="max-h-80 overflow-auto rounded-lg border border-slate-200 bg-white">
          <table className="w-full text-xs">
            <thead className="sticky top-0 border-b border-teal-100 bg-teal-50 text-[10.5px] uppercase tracking-wide text-teal-800">
              <tr>
                <th className={cn(th, "pl-3 text-left")}>Date</th>
                <th className={cn(th, "text-right")}>Opening</th>
                <th className={cn(th, "text-right")}>Instalment</th>
                <th className={cn(th, "text-right")}>Interest</th>
                <th className={cn(th, "text-right")}>Principal</th>
                <th className={cn(th, "pr-3 text-right")}>Closing</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-100">
              {rows.map((r) => (
                <tr key={r.date} className={cn(yearEnd && r.date <= yearEnd && r.date > `${Number(yearEnd.slice(0, 4)) - 1}${yearEnd.slice(4)}` && "bg-teal-50/40")}>
                  <td className="py-1 pl-3 text-slate-600">{day(r.date)}</td>
                  <td className={num}>{money(r.opening)}</td>
                  <td className={num}>{money(r.instalment)}</td>
                  <td className={num}>{money(r.interest)}</td>
                  <td className={num}>{money(r.principal)}</td>
                  <td className={cn(num, "pr-3")}>{money(r.closing)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : (
        <p className="text-xs text-slate-500">Enter the loan amount, the rate, the term and the start date to see the schedule.</p>
      )}
    </div>
  );
}
