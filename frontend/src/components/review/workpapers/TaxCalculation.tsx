"use client";

import { SkeletonRows } from "@/components/common/SkeletonRows";
import { wp } from "@/components/review/area/WorkpaperParts";
import { useTaxCalculation } from "@/lib/queries/job";
import { cn } from "@/lib/utils";

/**
 * The tax calculation: profit, the adjustments, capital allowances and the tax, line by line, as the corporation
 * tax computation works it, against the tax charged in the accounts.
 */
const { money, th, num } = wp;
const TOTALS = /^(adjusted profit|trading profits|profits chargeable|corporation tax chargeable|total tax)/i;

export function TaxCalculation({ engagementId }: { engagementId: string }) {
  const q = useTaxCalculation(engagementId);
  if (q.error) return <p className="text-[11px] text-rose-700">{(q.error as Error).message}</p>;
  if (!q.data) return <div className="rounded-xl border border-slate-200 bg-white p-4"><SkeletonRows rows={8} /></div>;
  const t = q.data;
  if (!t.lines.length) return null;
  return (
    <div className="overflow-hidden rounded-xl border border-slate-200 bg-white shadow-2xs">
      <div className="border-b border-teal-100 bg-linear-to-r from-teal-50/70 to-white px-4 py-3">
        <h3 className="text-sm font-bold text-teal-900">Tax calculation</h3>
        <p className="text-[11px] text-slate-500">The corporation tax computation from the accounts after the journals approved in the app; the CT600 box beside each line.</p>
      </div>
      <table className="w-full table-fixed text-xs">
        <thead className="border-b border-teal-100 bg-teal-50/80 text-[10.5px] uppercase tracking-wide text-teal-800">
          <tr>
            <th className={cn(th, "pl-4 text-left")}>Description</th>
            <th className={cn(th, "w-20 text-left")}>Box</th>
            <th className={cn(th, "w-36 pr-4 text-right")}>Amount</th>
          </tr>
        </thead>
        <tbody className="divide-y divide-slate-100">
          {t.lines.map((l, i) => {
            const total = TOTALS.test(l.label);
            return (
              <tr key={`${l.label}-${i}`} className={cn(total && "bg-slate-50/70 font-semibold text-slate-900")}>
                <td className="py-1.5 pl-4 pr-3 text-slate-800" title={l.note || undefined}>{l.label}</td>
                <td className="px-3 py-1.5 text-[11px] text-slate-400">{l.box}</td>
                <td className={cn(num, "py-1.5 pr-4")}>{money(l.amount)}</td>
              </tr>
            );
          })}
        </tbody>
        <tfoot className="border-t-2 border-teal-200 bg-teal-50/70 text-teal-900">
          <tr className="font-bold">
            <td className="py-2 pl-4" colSpan={2}>Tax charged in the accounts</td>
            <td className={cn(num, "pr-4")}>{money(t.tax_in_accounts)}</td>
          </tr>
          <tr>
            <td className="py-1.5 pl-4" colSpan={2}>Difference to the computation</td>
            <td className={cn(num, "pr-4 font-semibold", Math.abs(t.difference) >= 1 ? "text-rose-700" : "text-emerald-700")}>
              {Math.abs(t.difference) >= 1 ? money(t.difference) : "Agrees"}
            </td>
          </tr>
        </tfoot>
      </table>
      {t.capital_allowances.length > 0 && (
        <div className="border-t border-slate-100 px-4 py-2 text-[11px] text-slate-500">
          Capital allowances: {t.capital_allowances.map((c) => `${c.label} ${money(c.amount)}`).join("; ")}.
        </div>
      )}
    </div>
  );
}
