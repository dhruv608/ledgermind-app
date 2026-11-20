// Debtors (or creditors) by age from the client's aged report, by age box or by invoice.
import { useEffect, useState } from "react";
import { SkeletonRows } from "@/components/common/SkeletonRows";
import { api, DebtorAgeing } from "@/lib/api";
import { cn } from "@/lib/utils";
import { TradeListing } from "@/components/control-accounts/TradeListing";
import { money } from "@/components/control-accounts/reconciliations/shared";

/** Debtors by age, from the client's own aged receivables report: who owes what, and for how long. Old debts (91+
 *  days) are highlighted: the client may never pay them (a question for the client, or a write-off). */
export function DebtorAgeingBox({ engagementId, kind = "AR" }: { engagementId: string; kind?: "AR" | "AP" }) {
  // The same listing for creditors, from the aged payables report
  const w = kind === "AP"
    ? { title: "Creditors by age", who: "Supplier", whos: "suppliers", report: "aged creditors report (aged payables)", none: "No supplier is owed anything over 90 days." }
    : { title: "Debtors by age", who: "Customer", whos: "customers", report: "aged debtors report (aged receivables)", none: "No customer owes anything over 90 days." };
  const [data, setData] = useState<DebtorAgeing | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [oldOnly, setOldOnly] = useState(false);
  const [byOldest, setByOldest] = useState(false);
  // By age (the five boxes) or by invoice (each open invoice, a total per customer)
  const [byInvoice, setByInvoice] = useState(false);
  useEffect(() => {
    (kind === "AP" ? api.getCreditorAgeing(engagementId) : api.getDebtorAgeing(engagementId))
      .then(setData).catch((e) => setError(e.message));
  }, [engagementId, kind]);

  if (error) return <p className="text-[11px] text-rose-700">{error}</p>;
  if (!data) return <SkeletonRows rows={3} />;
  if (!data.report || !data.customers || !data.totals || !data.boxes) {
    return (
      <p className="rounded-md border border-slate-200 bg-slate-50 px-3 py-2 text-[11px] text-slate-600">
        Upload the client&apos;s {w.report} to see {w.title.toLowerCase()}.
      </p>
    );
  }
  const total = data.total || 0;
  let customers = oldOnly ? data.customers.filter((c) => Math.abs(c.boxes[4]) >= 0.005) : data.customers;
  if (byOldest) customers = [...customers].sort((a, b) => b.boxes[4] - a.boxes[4] || b.boxes[3] - a.boxes[3]);
  const off = data.report_total != null && Math.abs((data.report_total || 0) - total) >= 0.02;
  const td = "whitespace-nowrap px-2 py-1 text-right font-mono";
  return (
    <div className="rounded-md border border-slate-200 text-xs">
      <div className="flex flex-wrap items-center gap-2 border-b border-slate-100 bg-slate-50 px-3 py-1.5">
        <p className="text-[11px] font-semibold uppercase tracking-wide text-slate-500">{w.title}</p>
        <p className="mr-auto text-[11px] text-slate-400" title={data.report}>
          From {data.report.length > 40 ? `${data.report.slice(0, 40)}…` : data.report}
          {data.as_at ? ` (${data.as_at.split("-").reverse().join("/")})` : ""}
          {data.method === "dates" ? ", aged by invoice date" : ""}
        </p>
        {(data.listing?.length ?? 0) > 0 && (
          <div className="flex rounded-md border border-slate-200 bg-white p-0.5 text-[11px]">
            {([[false, "By age"], [true, "By invoice"]] as [boolean, string][]).map(([v, label]) => (
              <button key={label} type="button" onClick={() => setByInvoice(v)}
                      className={cn("rounded px-2 py-0.5 font-medium", byInvoice === v ? "bg-teal-50 text-teal-800" : "text-slate-500 hover:text-slate-800")}>
                {label}
              </button>
            ))}
          </div>
        )}
        {!byInvoice && (
          <>
            <label className="flex cursor-pointer items-center gap-1 text-[11px] text-slate-600">
              <input type="checkbox" checked={oldOnly} onChange={() => setOldOnly(!oldOnly)} className="h-3 w-3 accent-teal-700" />
              Only 91+ days
            </label>
            <label className="flex cursor-pointer items-center gap-1 text-[11px] text-slate-600">
              <input type="checkbox" checked={byOldest} onChange={() => setByOldest(!byOldest)} className="h-3 w-3 accent-teal-700" />
              Oldest first
            </label>
          </>
        )}
      </div>
      <div className="max-h-80 overflow-auto">
        {byInvoice && data.listing ? <TradeListing listing={data.listing} who={w.who} /> : (
        <table className="w-full">
          <thead className="sticky top-0 bg-white text-[10px] uppercase tracking-wide text-slate-500">
            <tr>
              <th className="px-3 py-1.5 text-left font-semibold">{w.who}</th>
              <th className="px-2 py-1.5 text-right font-semibold">Total</th>
              {data.boxes.map((b) => (
                <th key={b} className="whitespace-nowrap px-2 py-1.5 text-right font-semibold">{b === "Not due" ? b : `${b} days`}</th>
              ))}
            </tr>
          </thead>
          <tbody className="divide-y divide-slate-100">
            {customers.map((c) => (
              <tr key={c.customer} className={cn(Math.abs(c.boxes[4]) >= 0.005 && "bg-amber-50/60")}>
                <td className="max-w-[16rem] truncate px-3 py-1 text-slate-800" title={c.customer}>
                  {c.customer}
                  {c.total < -0.005 && <span className="ml-1.5 text-[10px] text-rose-700">{kind === "AP" ? "in debit" : "in credit"}</span>}
                </td>
                <td className={cn(td, "font-semibold text-slate-900")}>{money(c.total)}</td>
                {c.boxes.map((v, i) => (
                  <td key={i} className={cn(td, Math.abs(v) < 0.005 ? "text-slate-300" : i === 4 ? "font-semibold text-amber-800" : "text-slate-700")}>
                    {Math.abs(v) < 0.005 ? "-" : money(v)}
                  </td>
                ))}
              </tr>
            ))}
            {customers.length === 0 && (
              <tr>
                <td colSpan={7} className="px-3 py-3 text-center text-slate-400">{w.none}</td>
              </tr>
            )}
          </tbody>
          <tfoot className="sticky bottom-0 border-t-2 border-slate-200 bg-slate-50 font-semibold text-slate-900">
            <tr>
              <td className="px-3 py-1.5">Total ({data.customers.length} {w.whos})</td>
              <td className={td}>{money(total)}</td>
              {data.totals.map((v, i) => (
                <td key={i} className={cn(td, i === 4 && Math.abs(v) >= 0.005 && "text-amber-800")}>{money(v)}</td>
              ))}
            </tr>
            {Math.abs(total) >= 0.005 && (
              <tr className="text-[10px] font-normal text-slate-500">
                <td className="px-3 pb-1.5">Share of the total</td>
                <td />
                {data.totals.map((v, i) => (
                  <td key={i} className="px-2 pb-1.5 text-right">{Math.round((v / total) * 100)}%</td>
                ))}
              </tr>
            )}
          </tfoot>
        </table>
        )}
      </div>
      {off && (
        <p className="border-t border-amber-100 bg-amber-50 px-3 py-1.5 text-[11px] text-amber-800">
          The boxes add up to {money(total)} but the report says {money(data.report_total || 0)}: check the report.
        </p>
      )}
      {(data.undated || 0) >= 0.005 && (
        <p className="border-t border-slate-100 px-3 py-1.5 text-[11px] text-slate-500">
          {money(data.undated || 0)} has no invoice date in the report, so it is not in the boxes.
        </p>
      )}
    </div>
  );
}
