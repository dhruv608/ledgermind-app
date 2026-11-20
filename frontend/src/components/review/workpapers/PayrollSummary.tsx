"use client";

import { useState } from "react";
import type { PayrollSummaryFigures, PayrollSummaryTable } from "@/lib/api";
import { SkeletonRows } from "@/components/common/SkeletonRows";
import { Tabs } from "@/components/ui/tabs";
import { wp } from "@/components/review/area/WorkpaperParts";
import { usePayrollSummary } from "@/lib/queries/job";
import { cn } from "@/lib/utils";

/**
 * The Payroll summary: month by month from the payroll reports, Total and, when a director is on the payroll,
 * Employees and Directors apart.
 */
const { money, th, num } = wp;
const COLS: { key: keyof PayrollSummaryFigures; label: string; strong?: boolean }[] = [
  { key: "gross", label: "Gross wages" },
  { key: "paye", label: "PAYE" },
  { key: "ee_ni", label: "Ee's NI" },
  { key: "student_loan", label: "Student loan" },
  { key: "ee_pension", label: "Ee pension" },
  { key: "er_ni", label: "Er's NI" },
  { key: "net", label: "Net wages", strong: true },
  { key: "er_pension", label: "Er's pension" },
  { key: "liability", label: "PAYE liability" },
  { key: "allowance", label: "Employment allowance" },
  { key: "total_liability", label: "Total PAYE liability", strong: true },
  { key: "pension_payable", label: "Pension payable", strong: true },
];
const monthName = (ym: string) => new Date(`${ym}-01T00:00:00`).toLocaleDateString("en-GB", { month: "short", year: "2-digit" });
const day = (iso: string) => new Date(`${iso}T00:00:00`).toLocaleDateString("en-GB");

export function PayrollSummary({ engagementId }: { engagementId: string }) {
  const q = usePayrollSummary(engagementId);
  const [pick, setPick] = useState<PayrollSummaryTable["key"]>("total");
  if (q.error) return <p className="text-[11px] text-rose-700">{(q.error as Error).message}</p>;
  if (!q.data) return <div className="rounded-xl border border-slate-200 bg-white p-4"><SkeletonRows rows={6} /></div>;
  if (!q.data.has_reports) return null;
  const tables = q.data.tables;
  const t = tables.find((x) => x.key === pick) ?? tables[0];
  return (
    <div className="overflow-hidden rounded-xl border border-slate-200 bg-white shadow-2xs">
      <div className="flex flex-wrap items-end justify-between gap-2 border-b border-teal-100 bg-linear-to-r from-teal-50/70 to-white px-4 py-3">
        <div>
          <h3 className="text-sm font-bold text-teal-900">Payroll summary</h3>
          <p className="text-[11px] text-slate-500">
            Month by month from the payroll reports{t.people ? `: ${t.people} ${t.people === 1 ? "person" : "people"}` : ""}.
            {q.data.split && ` ${q.data.split}.`}
          </p>
        </div>
        {tables.length > 1 && (
          <Tabs label="Payroll summary" items={tables.map((x) => ({ id: x.key, label: x.title }))} value={t.key} onChange={setPick} />
        )}
      </div>
      <div className="overflow-x-auto">
        <table className="w-full min-w-[72rem] text-xs">
          <thead className="border-b border-teal-100 bg-teal-50/80 text-[10.5px] uppercase tracking-wide text-teal-800">
            <tr>
              <th className={cn(th, "sticky left-0 w-20 bg-teal-50 pl-4 text-left")}>Month</th>
              <th className={cn(th, "w-24 text-left")}>Pay date</th>
              {COLS.map((c) => <th key={c.key} className={cn(th, "text-right")}>{c.label}</th>)}
            </tr>
          </thead>
          <tbody className="divide-y divide-slate-100">
            {t.months.map((m) => (
              <tr key={m.month}>
                <td className="sticky left-0 bg-white py-1.5 pl-4 pr-3 font-medium text-slate-800">{monthName(m.month)}</td>
                <td className="px-3 py-1.5 text-slate-500">{day(m.pay_date)}</td>
                {COLS.map((c) => (
                  <td key={c.key} className={cn(num, "py-1.5", c.strong && "font-semibold text-slate-900", !m[c.key] && "text-slate-300")}>{money(m[c.key])}</td>
                ))}
              </tr>
            ))}
          </tbody>
          <tfoot className="border-t-2 border-teal-200 bg-teal-50/70 font-bold text-teal-900">
            <tr>
              <td className="sticky left-0 bg-teal-50 py-2 pl-4">Total</td>
              <td />
              {COLS.map((c) => <td key={c.key} className={num}>{money(t.total[c.key])}</td>)}
            </tr>
          </tfoot>
        </table>
      </div>
    </div>
  );
}
