"use client";

import { AskLedge } from "@/components/assistant/AskLedge";
import { SkeletonRows } from "@/components/common/SkeletonRows";
import { wp } from "@/components/review/area/WorkpaperParts";
import { useSalesReconciliation } from "@/lib/queries/job";
import { cn } from "@/lib/utils";

/**
 * Sales per the VAT returns to sales in the P&L (the VAT sales reconciliation): Box 6 for the year, the
 * cash-accounting debtors, the approved journals, and the unidentified difference left to explain.
 */
const { money, th, num } = wp;

export function SalesReconciliation({ engagementId }: { engagementId: string }) {
  const q = useSalesReconciliation(engagementId);
  if (q.error) return <p className="text-[11px] text-rose-700">{(q.error as Error).message}</p>;
  if (!q.data) return <div className="rounded-xl border border-slate-200 bg-white p-4"><SkeletonRows rows={5} /></div>;
  const s = q.data;
  const gap = s.lines.find((l) => l.key === "unidentified")?.amount ?? 0;
  const pl = s.lines.find((l) => l.key === "pl")?.amount ?? 0;
  return (
    <div className="overflow-hidden rounded-xl border border-slate-200 bg-white shadow-2xs">
      <div className="border-b border-teal-100 bg-linear-to-r from-teal-50/70 to-white px-4 py-3">
        <h3 className="text-sm font-bold text-teal-900">Sales reconciliation</h3>
        <p className="text-[11px] text-slate-500">
          Sales per the VAT returns to sales in the profit and loss account
          {s.basis === "CASH" ? " (cash accounting: the debtors at each end are the timing difference)" : ""}.
          {s.flat_rate && " Flat rate scheme: Box 6 includes VAT, so the difference is not a true one."}
        </p>
      </div>
      {!s.ready && <p className="border-b border-slate-100 bg-amber-50/60 px-4 py-2 text-[11px] text-amber-800">{s.why_not}.</p>}
      <table className="w-full table-fixed text-xs">
        <thead className="border-b border-teal-100 bg-teal-50/80 text-[10.5px] uppercase tracking-wide text-teal-800">
          <tr>
            <th className={cn(th, "pl-4 text-left")}>Description</th>
            <th className={cn(th, "w-[42%] text-left")}>Ref</th>
            <th className={cn(th, "w-36 pr-4 text-right")}>Amount</th>
          </tr>
        </thead>
        <tbody className="divide-y divide-slate-100">
          {s.lines.map((l) => {
            const red = l.key === "unidentified" && s.ready && Math.abs(l.amount) >= 1;
            const strong = l.key === "pl";
            return (
              <tr key={l.key} className={cn(strong && "border-t-2 border-teal-200 bg-teal-50/70 font-bold text-teal-900")}>
                <td className={cn("py-2 pl-4 pr-3", red ? "font-semibold text-rose-700" : !strong && "text-slate-800")}>{l.label}</td>
                <td className="truncate px-3 py-2 text-[11px] font-normal text-slate-500" title={l.note}>{l.note}</td>
                <td className={cn(num, "pr-4", red && "font-semibold text-rose-700", !strong && l.amount === 0 && "text-slate-300")}>
                  <span className="inline-flex items-center justify-end gap-1">
                    {money(l.amount)}
                    {red && <AskLedge icon label="Explain with Ledge" question={`Sales per the VAT returns and sales in the P&L (${money(pl)}) differ by ${money(gap)} after the debtors and journals. What usually explains this (zero-rated, exempt or outside-the-scope income, sales in other income, cut-off), and what should I check?`} />}
                  </span>
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}
