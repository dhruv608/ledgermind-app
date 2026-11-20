"use client";

import { Fragment } from "react";
import type { DebtorAgeing } from "@/lib/api";
import { formatCurrency } from "@/lib/formatters";

/**
 * The trade debtors / creditors listing: each invoice or bill still open at the year end, by customer or supplier,
 * with a total for each and a grand total.
 */
const day = (iso: string | null) => (iso ? iso.split("-").reverse().join("/") : "-");

export function TradeListing({ listing, who }: { listing: NonNullable<DebtorAgeing["listing"]>; who: string }) {
  const td = "whitespace-nowrap px-2 py-1";
  const total = listing.reduce((t, c) => t + c.total, 0);
  const anyDue = listing.some((c) => c.items.some((i) => i.due));
  const anyType = listing.some((c) => c.items.some((i) => i.type));
  if (!listing.length) return <p className="px-3 py-3 text-center text-[11px] text-slate-400">The report lists no open invoices.</p>;
  return (
    <table className="w-full">
      <thead className="sticky top-0 bg-white text-[10px] uppercase tracking-wide text-slate-500">
        <tr>
          <th className="px-3 py-1.5 text-left font-semibold">{who}</th>
          <th className="px-2 py-1.5 text-left font-semibold">Date</th>
          {anyType && <th className="px-2 py-1.5 text-left font-semibold">Type</th>}
          <th className="px-2 py-1.5 text-left font-semibold">Number</th>
          {anyDue && <th className="px-2 py-1.5 text-left font-semibold">Due date</th>}
          <th className="px-2 py-1.5 text-right font-semibold">Outstanding</th>
        </tr>
      </thead>
      <tbody>
        {listing.map((c) => (
          <Fragment key={c.customer}>
            {c.items.map((i, k) => (
              <tr key={k} className="border-t border-slate-50">
                <td className="max-w-[14rem] truncate px-3 py-1 text-slate-800" title={c.customer}>{k === 0 ? c.customer : ""}</td>
                <td className={`${td} text-slate-600`}>{day(i.date)}</td>
                {anyType && <td className={`${td} text-slate-500`}>{i.type || "-"}</td>}
                <td className={`${td} text-slate-600`}>{i.number || "-"}</td>
                {anyDue && <td className={`${td} text-slate-500`}>{day(i.due)}</td>}
                <td className={`${td} text-right font-mono text-slate-800`}>{formatCurrency(i.amount)}</td>
              </tr>
            ))}
            {c.items.length > 1 && (
              <tr className="bg-slate-50/70 text-[11px] font-semibold text-slate-700">
                <td className="px-3 py-1" colSpan={2 + (anyType ? 1 : 0) + 1 + (anyDue ? 1 : 0)}>Total for {c.customer}</td>
                <td className={`${td} text-right font-mono`}>{formatCurrency(c.total)}</td>
              </tr>
            )}
          </Fragment>
        ))}
      </tbody>
      <tfoot className="sticky bottom-0 border-t-2 border-slate-200 bg-slate-50 font-semibold text-slate-900">
        <tr>
          <td className="px-3 py-1.5" colSpan={2 + (anyType ? 1 : 0) + 1 + (anyDue ? 1 : 0)}>Total</td>
          <td className={`${td} text-right font-mono`}>{formatCurrency(total)}</td>
        </tr>
      </tfoot>
    </table>
  );
}
