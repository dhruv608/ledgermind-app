"use client";

import { useState } from "react";
import { CalendarRange } from "lucide-react";
import type { PayrollMonths, PayrollTable } from "@/lib/api";
import { usePayrollMonths } from "@/lib/queries/job";
import { formatCurrency } from "@/lib/formatters";
import { cn } from "@/lib/utils";
import { Card } from "@/components/ui/card";
import { SectionHeader } from "@/components/ui/section-header";
import { SkeletonRows } from "@/components/common/SkeletonRows";

const money = (v: number) => (Math.abs(v) < 0.005 ? "-" : formatCurrency(v, { accountingStyle: true }));
const monthLabel = (iso: string) =>
  new Date(`${iso}T00:00:00`).toLocaleDateString("en-GB", { month: "short", year: "numeric" });
const OWED: Record<PayrollTable["key"], string> = {
  net_wages: "Net pay posted",
  paye: "PAYE / NI owed",
  pension: "Pension owed",
};

/** Payroll by month (the Net wages and payroll area page, under its reconciliation, like the VAT proof on VAT): net wages, PAYE / NI and pension owed, paid and unpaid each month, and the
 *  payroll cost against what was owed out. The same figures as the workbook's G6, G6.2, G7 and G8. */
export function PayrollMonthsPanel({ engagementId, refreshKey, showEmpty }: {
  engagementId: string; refreshKey?: string;
  /** Say so in a line when the books have no payroll (on the area page, so its tab is never blank) */
  showEmpty?: boolean;
}) {
  // From the job's shared store (the payroll working paper asks for the same figures)
  const months = usePayrollMonths(engagementId, refreshKey);
  const data: PayrollMonths | null = months.data ?? null;
  const error = months.error ? months.error.message : null;
  const [picked, setView] = useState<string>("");
  const view = picked || data?.tables[0]?.key || "";

  if (data && data.tables.length === 0) {      // no payroll in the books
    return showEmpty ? (
      <p className="rounded-xl border border-slate-200 bg-white px-4 py-3 text-[13px] text-slate-500">
        No payroll in the books: no wages, PAYE / NI or pension to reconcile month by month.
      </p>
    ) : null;
  }
  const flags = (data?.tables.reduce((t, x) => t + x.flags, 0) || 0) + (data?.summary?.flags || 0);
  const views = [
    ...(data?.tables || []).map((t) => ({ id: t.key as string, label: t.title, flags: t.flags })),
    ...(data?.summary ? [{ id: "summary", label: "Cost v owed out", flags: data.summary.flags }] : []),
  ];
  const table = data?.tables.find((t) => t.key === view);

  return (
    <Card className="overflow-hidden">
      <div className="space-y-3 p-5">
        <SectionHeader
          icon={CalendarRange}
          title="Payroll by month"
          description="What was owed each month to staff, HMRC and the pension scheme, what was paid and what is left."
        />
        {data && (
          <p className={cn("text-xs", flags ? "font-medium text-amber-700" : "text-emerald-700")}>
            {flags ? `${flags} month${flags === 1 ? "" : "s"} to look at` : "Every month looks right"}
          </p>
        )}
        {views.length > 0 && (
          <div className="flex w-fit flex-wrap rounded-lg border border-slate-200 bg-white p-0.5 text-xs">
            {views.map((v) => (
              <button
                key={v.id}
                type="button"
                onClick={() => setView(v.id)}
                className={cn("rounded-md px-3 py-1 font-medium", view === v.id ? "bg-teal-50 text-teal-800" : "text-slate-500 hover:text-slate-800")}
              >
                {v.label}
                {v.flags > 0 && <span className="ml-1.5 rounded-full bg-amber-100 px-1.5 text-[10px] text-amber-800">{v.flags}</span>}
              </button>
            ))}
          </div>
        )}
      </div>
      {error ? (
        <p className="border-t border-slate-100 px-5 py-6 text-sm text-rose-700">{error}</p>
      ) : !data ? (
        <div className="border-t border-slate-100 p-5">
          <SkeletonRows rows={6} />
        </div>
      ) : view === "summary" && data.summary ? (
        <SummaryTable summary={data.summary} />
      ) : table ? (
        <ControlTable t={table} />
      ) : null}
    </Card>
  );
}

function ControlTable({ t }: { t: PayrollTable }) {
  const th = "px-3 py-2 font-semibold";
  const td = "whitespace-nowrap px-3 py-1.5 text-right font-mono";
  const cols = t.with_allowance ? 6 : 5;
  return (
    <div className="overflow-x-auto border-t border-slate-100">
      <table className="w-full text-xs">
        <thead className="border-b border-slate-200 bg-slate-50 text-[11px] uppercase tracking-wide text-slate-500">
          <tr className="text-left">
            <th className={cn(th, "pl-5")}>Month</th>
            <th className={cn(th, "text-right")}>{OWED[t.key]}</th>
            {t.with_allowance && <th className={cn(th, "text-right")}>Employment allowance</th>}
            <th className={cn(th, "text-right")}>Paid / cleared</th>
            <th className={cn(th, "text-right")}>Balance at month end</th>
            <th className={cn(th, "pr-5")}>Note</th>
          </tr>
        </thead>
        <tbody className="divide-y divide-slate-100">
          <tr className="text-slate-500">
            <td className="py-1.5 pl-5">Brought forward</td>
            <td colSpan={cols - 3} />
            <td className={td}>{money(t.opening)}</td>
            <td />
          </tr>
          {t.months.map((m) => (
            <tr key={m.month} className={cn(m.note && "bg-amber-50/60")}>
              <td className="py-1.5 pl-5 font-medium text-slate-800">{monthLabel(m.month)}</td>
              <td className={td}>{money(m.owed)}</td>
              {t.with_allowance && <td className={td}>{money(m.allowance)}</td>}
              <td className={td}>{money(m.paid)}</td>
              <td className={cn(td, "font-semibold text-slate-900")}>{money(m.balance)}</td>
              <td className="px-3 pr-5 text-[11px] font-medium text-amber-800">{m.note || ""}</td>
            </tr>
          ))}
          {Math.abs(t.other) >= 0.005 && (
            <tr className="bg-amber-50/60">
              <td className="py-1.5 pl-5 text-slate-700">Other entries</td>
              <td className={td}>{t.other > 0 ? money(t.other) : ""}</td>
              {t.with_allowance && <td />}
              <td className={td}>{t.other < 0 ? money(-t.other) : ""}</td>
              <td />
              <td className="px-3 pr-5 text-[11px] font-medium text-amber-800">
                Not in the twelve months: other dates or opening lines. Check them in the ledger.
              </td>
            </tr>
          )}
          {(Math.abs(t.journals) >= 0.005 || Math.abs(t.allowance_journal) >= 0.005) && (
            <tr>
              <td className="py-1.5 pl-5 text-slate-700">Journals approved in the app</td>
              <td colSpan={cols - 3} />
              <td className={td}>{money(t.journals)}</td>
              <td />
            </tr>
          )}
        </tbody>
        <tfoot className="border-t-2 border-slate-200 bg-slate-50 font-semibold text-slate-900">
          <tr>
            <td className="py-2 pl-5">Still owed at the year end</td>
            <td colSpan={cols - 3} />
            <td className={td}>{money(t.closing)}</td>
            <td className="px-3 pr-5 text-[11px] font-normal text-slate-500">
              {t.closing < -0.005 ? "Negative: paid more than was owed" : ""}
            </td>
          </tr>
        </tfoot>
      </table>
    </div>
  );
}

function SummaryTable({ summary }: { summary: NonNullable<PayrollMonths["summary"]> }) {
  const th = "whitespace-nowrap px-2 py-2 text-right font-semibold";
  const td = "whitespace-nowrap px-2 py-1.5 text-right font-mono";
  return (
    <div className="border-t border-slate-100">
      <p className="px-5 py-2 text-[11px] text-slate-500">
        Each month the payroll cost should equal what is owed out (net pay, PAYE / NI and pension). A difference usually
        means a payroll journal is missing, doubled or posted to another account.
        {!summary.has_net_wages && " This client has no net wages account (wages paid straight from the bank), so the months cannot be checked this way."}
      </p>
      <div className="overflow-x-auto">
        <table className="w-full text-xs">
          <thead className="border-y border-slate-200 bg-slate-50 text-[11px] uppercase tracking-wide text-slate-500">
            <tr>
              <th className="px-2 py-2 pl-5 text-left font-semibold">Month</th>
              {summary.cost_names.map((n) => (
                <th key={n} className={th}>{n}</th>
              ))}
              <th className={th}>Total cost</th>
              <th className={th}>Net pay</th>
              <th className={th}>PAYE / NI</th>
              <th className={th}>Pension</th>
              <th className={th}>Total owed out</th>
              <th className={th}>Paid via DLA</th>
              <th className={cn(th, "pr-5")}>Unexplained</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-slate-100">
            {summary.months.map((m) => {
              const off = m.unexplained !== null && Math.abs(m.unexplained) >= 1;
              return (
                <tr key={m.month} className={cn(off && "bg-amber-50/60")}>
                  <td className="whitespace-nowrap py-1.5 pl-5 font-medium text-slate-800">{monthLabel(m.month)}</td>
                  {m.costs.map((c, i) => (
                    <td key={i} className={td}>{money(c)}</td>
                  ))}
                  <td className={cn(td, "font-semibold")}>{money(m.total_cost)}</td>
                  <td className={td}>{money(m.net_pay)}</td>
                  <td className={td}>{money(m.paye)}</td>
                  <td className={td}>{money(m.pension)}</td>
                  <td className={cn(td, "font-semibold")}>{money(m.total_owed)}</td>
                  <td className={td}>{money(m.via_dla)}</td>
                  <td className={cn(td, "pr-5", off ? "font-semibold text-amber-800" : "text-slate-400")}>
                    {m.unexplained === null ? "n/a" : money(m.unexplained)}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </div>
  );
}
