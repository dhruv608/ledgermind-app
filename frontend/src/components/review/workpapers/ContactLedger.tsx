"use client";

import { useEffect, useMemo, useState } from "react";
import { api, type ContactLedger as Ledger } from "@/lib/api";
import { SkeletonRows } from "@/components/common/SkeletonRows";
import { PageControls } from "@/components/common/Pagination";
import { usePagination } from "@/hooks/usePagination";
import { formatCurrency } from "@/lib/formatters";
import { cn } from "@/lib/utils";

// How each kind of document reads in the list: a bill and a direct payment to the same supplier are what to compare
const TYPE_STYLE: Record<string, string> = {
  bill: "bg-teal-50 text-teal-800 ring-teal-200",
  invoice: "bg-teal-50 text-teal-800 ring-teal-200",
  "paid a bill": "bg-slate-100 text-slate-600 ring-slate-200",
  "receipt for an invoice": "bg-slate-100 text-slate-600 ring-slate-200",
  "direct payment": "bg-amber-50 text-amber-800 ring-amber-200",
  "direct receipt": "bg-amber-50 text-amber-800 ring-amber-200",
};
const day = (d: string | null) => (d ? new Date(d).toLocaleDateString("en-GB") : "");

/** The ledger of the contacts a duplicates point is about (where the bill and the direct payment are, so it is
 *  easy to decide): each document by date, its type, number, the accounts it went to and its amount. */
export function ContactLedger({ engagementId, findingId }: { engagementId: string; findingId: number }) {
  const [data, setData] = useState<Ledger[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [contact, setContact] = useState(0);
  const [type, setType] = useState("all");

  useEffect(() => {
    api.getPointLedger(engagementId, findingId).then(setData).catch((e) => setError(e.message));
  }, [engagementId, findingId]);

  const ledger = data?.[contact];
  const rows = useMemo(() => (ledger?.documents || []).filter((d) => type === "all" || d.type === type), [ledger, type]);
  const page = usePagination({ items: rows, initialPageSize: 25, resetDependencies: [contact, type] });

  if (error) return <p className="text-[11px] text-rose-700">{error}</p>;
  if (!data) return <SkeletonRows rows={3} />;
  if (!data.length || !ledger) return <p className="text-[11px] text-slate-500">No ledger lines found for this point.</p>;

  return (
    <div className="overflow-hidden rounded-lg border border-slate-200 text-xs">
      {data.length > 1 && (
        <div className="flex flex-wrap gap-1 border-b border-slate-100 bg-slate-50 px-3 py-2">
          {data.map((c, i) => (
            <button key={c.contact} type="button" onClick={() => { setContact(i); setType("all"); }}
                    className={cn("rounded-md px-2 py-0.5 font-medium transition-colors",
                                  i === contact ? "bg-teal-600 text-white" : "text-slate-600 hover:bg-teal-50 hover:text-teal-800")}>
              {c.contact}
            </button>
          ))}
        </div>
      )}
      <div className="flex flex-wrap items-center gap-1 border-b border-slate-100 px-3 py-2">
        <span className="mr-1 font-semibold text-slate-700">{ledger.contact}</span>
        {[["all", ledger.documents.length + ledger.more] as const, ...Object.entries(ledger.counts)].map(([t, n]) => (
          <button key={t} type="button" onClick={() => setType(t)}
                  className={cn("rounded-full px-2 py-0.5 text-[11px] font-medium transition-colors",
                                type === t ? "bg-teal-50 text-teal-800 ring-1 ring-inset ring-teal-200" : "text-slate-500 hover:bg-teal-50/60 hover:text-teal-800")}>
            {t === "all" ? "All" : t.charAt(0).toUpperCase() + t.slice(1)} {n}
          </button>
        ))}
      </div>
      <table className="w-full table-fixed">
        <thead className="bg-slate-50 text-[10.5px] uppercase tracking-wide text-slate-500">
          <tr className="text-left">
            <th className="w-24 px-3 py-1.5 font-semibold">Date</th>
            <th className="w-32 px-2 py-1.5 font-semibold">Type</th>
            <th className="w-28 px-2 py-1.5 font-semibold">Number</th>
            <th className="px-2 py-1.5 font-semibold">Accounts</th>
            <th className="w-24 px-3 py-1.5 text-right font-semibold">Amount</th>
          </tr>
        </thead>
        <tbody className="divide-y divide-slate-100">
          {page.paginatedItems.map((d, i) => (
            <tr key={`${d.date}-${d.number}-${d.source}-${i}`} className="transition-colors hover:bg-teal-50/40">
              <td className="px-3 py-1.5 tabular-nums text-slate-600">{day(d.date)}</td>
              <td className="px-2 py-1.5">
                <span title={d.source}
                      className={cn("rounded-full px-2 py-px text-[10.5px] font-semibold ring-1 ring-inset", TYPE_STYLE[d.type] || "bg-slate-50 text-slate-600 ring-slate-200")}>
                  {d.type}
                </span>
              </td>
              <td className="truncate px-2 py-1.5 font-mono text-[11px] text-slate-500" title={d.number}>{d.number}</td>
              <td className="truncate px-2 py-1.5 text-slate-600" title={d.accounts.join(", ")}>{d.accounts.join(", ")}</td>
              <td className="px-3 py-1.5 text-right font-mono tabular-nums text-slate-900">{formatCurrency(d.amount)}</td>
            </tr>
          ))}
        </tbody>
      </table>
      <PageControls page={page} itemLabel="lines" sizes={[25, 50, 100]} />
    </div>
  );
}
