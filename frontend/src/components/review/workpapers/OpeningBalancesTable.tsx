"use client";

import { useEffect, useState } from "react";
import { CheckCircle2 } from "lucide-react";
import { api } from "@/lib/api";
import type { OpeningBalances } from "@/lib/api";
import { SkeletonRows } from "@/components/common/SkeletonRows";
import { cn } from "@/lib/utils";
import { formatCurrency } from "@/lib/formatters";

const signed = (n: number) => formatCurrency(n);

/** M1: each balance's opening in the books v last year's closing, the difference and its cause, with the reserve
 * brought forward at the foot (the differences together explain it, or not). */
export function OpeningBalancesTable({ engagementId, refreshKey }: { engagementId: string; refreshKey?: unknown }) {
  const [data, setData] = useState<OpeningBalances | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [all, setAll] = useState(false);

  // Another job or a refresh: clear the old error at once (during render); the effect below loads
  const [loadedFor, setLoadedFor] = useState<[string, unknown]>([engagementId, refreshKey]);
  if (loadedFor[0] !== engagementId || loadedFor[1] !== refreshKey) {
    setLoadedFor([engagementId, refreshKey]);
    setError(null);
  }
  useEffect(() => {
    api.getOpeningBalances(engagementId).then(setData).catch((e) => setError(e.message));
  }, [engagementId, refreshKey]);

  if (error) return <p className="rounded-xl border border-rose-200 bg-white px-4 py-3 text-xs text-rose-700">{error}</p>;
  if (!data) {
    return (
      <div className="overflow-hidden rounded-xl border border-slate-200 bg-white">
        <SkeletonRows rows={4} columns={4} label="Comparing with last year" />
      </div>
    );
  }
  if (!data.compared) {
    return (
      <p className="rounded-xl border border-slate-200 bg-white px-4 py-3 text-xs text-slate-600">
        No last year&apos;s figures to compare with. Upload last year&apos;s final working paper or closing TB on the Files tab.
      </p>
    );
  }
  const differ = data.rows.filter((r) => Math.abs(r.difference) >= 1);
  const shown = all ? data.rows : differ;
  const gap = data.gap ?? 0;
  return (
    <div className="overflow-hidden rounded-xl border border-slate-200 bg-white shadow-2xs">
      <div className="flex flex-wrap items-center justify-between gap-2 border-b border-slate-100 px-4 py-2.5">
        <p className="text-xs text-slate-600">
          Opening per the books v last year&apos;s closing ({data.source}): {differ.length} of {data.rows.length} differ
        </p>
        <button type="button" onClick={() => setAll(!all)} className="text-[11px] font-medium text-teal-700 hover:underline">
          {all ? "Show only the differences" : "Show every balance"}
        </button>
      </div>
      <table className="w-full table-fixed text-xs">
        <thead className="border-b border-slate-200 bg-slate-50 text-[10.5px] uppercase tracking-wide text-slate-500">
          <tr className="text-left">
            <th className="px-4 py-2 font-semibold">Balance</th>
            <th className="w-32 px-3 py-2 text-right font-semibold">Books opening</th>
            <th className="w-32 px-3 py-2 text-right font-semibold">Last year</th>
            <th className="w-28 px-3 py-2 text-right font-semibold">Difference</th>
            <th className="w-[26%] px-4 py-2 font-semibold">Why</th>
          </tr>
        </thead>
        <tbody className="divide-y divide-slate-100">
          {shown.map((r) => (
            <tr key={r.code + r.name}>
              <td className="truncate px-4 py-2 font-medium text-slate-800" title={r.name}>{r.name}</td>
              <td className="px-3 py-2 text-right font-mono tabular-nums text-slate-900">{signed(r.books)}</td>
              <td className="px-3 py-2 text-right font-mono tabular-nums text-slate-900">{signed(r.last_year)}</td>
              <td className={cn("px-3 py-2 text-right font-mono tabular-nums", Math.abs(r.difference) >= 1 ? "font-semibold text-rose-700" : "text-slate-400")}>
                {Math.abs(r.difference) >= 1 ? signed(r.difference) : "-"}
              </td>
              <td className="px-4 py-2 text-[11px] text-slate-600">
                {r.cause === "Agrees" ? (
                  <span className="inline-flex items-center gap-1 font-semibold text-emerald-700"><CheckCircle2 className="h-3.5 w-3.5" /> Agrees</span>
                ) : r.cause}
              </td>
            </tr>
          ))}
          {shown.length === 0 && (
            <tr><td colSpan={5} className="px-4 py-4 text-center text-slate-500">Every balance opens at last year&apos;s figure.</td></tr>
          )}
        </tbody>
        <tfoot className="border-t-2 border-slate-200 bg-slate-50 text-slate-900">
          <tr>
            <td className="px-4 py-2 font-semibold">Profit and loss reserve brought forward</td>
            <td className="px-3 py-2 text-right font-mono font-semibold tabular-nums">{signed(-(data.books_bf ?? 0))}</td>
            <td className="px-3 py-2 text-right font-mono font-semibold tabular-nums">{signed(-(data.last_year_bf ?? 0))}</td>
            <td className={cn("px-3 py-2 text-right font-mono font-semibold tabular-nums", Math.abs(gap) >= 1 ? "text-rose-700" : "text-emerald-700")}>
              {Math.abs(gap) >= 1 ? signed(-gap) : "Agrees"}
            </td>
            <td className="px-4 py-2 text-[11px] text-slate-600">
              {Math.abs(gap) < 1 ? "" : Math.abs(gap - (data.explained ?? 0)) < 1 ? "Explained by the balances above" : `${signed(Math.abs(gap - (data.explained ?? 0)))} not explained`}
            </td>
          </tr>
        </tfoot>
      </table>
    </div>
  );
}
