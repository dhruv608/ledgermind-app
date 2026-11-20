"use client";

import { useState } from "react";
import { SkeletonRows } from "@/components/common/SkeletonRows";
import { Tabs } from "@/components/ui/tabs";
import { formatCurrency } from "@/lib/formatters";
import { useEtb } from "@/lib/queries/job";
import { cn } from "@/lib/utils";

/**
 * GL scrutiny summary (GL Scrutiny > Summary): the profit and loss and the balance sheet by account,
 * this year beside last year and the variance; an account opens in the Analysis.
 */
const bigChange = (now: number, before: number) =>
  Math.abs(now - before) >= 1000 && (Math.abs(before) < 0.005 || Math.abs(now) < 0.005 || Math.abs(now - before) / Math.abs(before) > 0.5);

export function ScrutinySummary({ engagementId, onOpen, only }: {
  engagementId: string;
  onOpen: (code: number) => void;
  /** One side only, without the switch (the P&L analysis working paper) */
  only?: "PL" | "BS";
}) {
  const q = useEtb(engagementId);
  const [picked, setSide] = useState<"PL" | "BS">("PL");
  const side = only ?? picked;
  if (q.error) return <p className="px-5 py-6 text-sm text-rose-700">{(q.error as Error).message}</p>;
  if (!q.data) return <div className="p-5"><SkeletonRows rows={8} /></div>;
  const rows = q.data.rows.filter((r) => (side === "PL") === r.pl);
  const th = "px-3 py-2 font-semibold";
  const known = Boolean(q.data.last_year_source);
  return (
    <div className="space-y-3 p-4">
      {only ? (
        <p className="text-[11px] text-slate-500">Each {only === "PL" ? "profit and loss" : "balance sheet"} account this year against last year ({known ? `last year from ${q.data.last_year_source}` : "no last year's figures"}). An account opens in GL scrutiny.</p>
      ) : (
        <Tabs label="Summary side" value={side} onChange={setSide}
              items={[{ id: "PL", label: "Profit and loss" }, { id: "BS", label: "Balance sheet" }]}
              actions={<span className="text-[11px] text-slate-500">{known ? `Last year from ${q.data.last_year_source}` : "No last year's figures"}</span>} />
      )}
      <div className="overflow-x-auto rounded-lg border border-slate-200">
        <table className="w-full text-xs">
          <thead className="border-b border-slate-200 bg-slate-50 text-[11px] uppercase tracking-wide text-slate-500">
            <tr>
              <th className={cn(th, "w-16 pl-4 text-left")}>Code</th>
              <th className={cn(th, "text-left")}>Account</th>
              <th className={cn(th, "w-32 text-right")}>This year</th>
              <th className={cn(th, "w-32 text-right")}>Last year</th>
              <th className={cn(th, "w-32 pr-4 text-right")}>Variance</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-slate-100">
            {rows.map((r) => {
              const ly = r.last_year;
              const variance = ly === null ? null : r.final - ly;
              const big = ly !== null && bigChange(r.final, ly);
              return (
                <tr key={r.code} className="cursor-pointer hover:bg-teal-50/40" onClick={() => onOpen(r.code)}>
                  <td className="py-1.5 pl-4 font-mono text-[11px] font-semibold text-teal-800">{String(r.code).padStart(4, "0")}</td>
                  <td className="max-w-xs truncate px-3 py-1.5 font-medium text-slate-900" title={r.accounts.join(" · ")}>{r.name}</td>
                  <td className="whitespace-nowrap px-3 py-1.5 text-right font-mono text-slate-900">{formatCurrency(r.final)}</td>
                  <td className="whitespace-nowrap px-3 py-1.5 text-right font-mono text-slate-500">{ly === null ? "–" : formatCurrency(ly)}</td>
                  <td className={cn("whitespace-nowrap px-3 py-1.5 pr-4 text-right font-mono", big ? "font-semibold text-orange-700" : "text-slate-500")}>
                    {variance === null ? "–" : Math.abs(variance) < 0.005 ? "—" : formatCurrency(variance)}
                  </td>
                </tr>
              );
            })}
          </tbody>
          <tfoot className="border-t-2 border-slate-200 bg-slate-50 font-semibold text-slate-900">
            <tr>
              <td className="py-2 pl-4" colSpan={2}>Total</td>
              <td className="px-3 py-2 text-right font-mono">{formatCurrency(rows.reduce((t, r) => t + r.final, 0))}</td>
              <td className="px-3 py-2 text-right font-mono">{known ? formatCurrency(rows.reduce((t, r) => t + (r.last_year ?? 0), 0)) : "–"}</td>
              <td />
            </tr>
          </tfoot>
        </table>
      </div>
    </div>
  );
}
