"use client";

import { SkeletonRows } from "@/components/common/SkeletonRows";
import { formatCurrency } from "@/lib/formatters";
import { useProposedJournals } from "@/lib/queries/job";
import { cn } from "@/lib/utils";
import type { ProposedJournal } from "@/types/engagement";

/**
 * GL scrutiny error report (GL Scrutiny > Error report): the journals that correct one account, each
 * as "Adjustment 1, 2 ..." with its lines (date, reference, description, debit, credit).
 */
const legs = (j: ProposedJournal) => j.lines?.length
  ? j.lines.map((l) => ({ code: l.account_code, name: l.account_name || "", debit: l.debit || 0, credit: l.credit || 0 }))
  : [{ code: j.debit_code, name: j.debit_name, debit: j.amount, credit: 0 }, { code: j.credit_code, name: j.credit_name, debit: 0, credit: j.amount }];
const STATUS = { PROPOSED: "to decide", APPROVED: "approved", REJECTED: "rejected" } as const;

export function ScrutinyErrorReport({ engagementId, code, name }: { engagementId: string; code: number | null; name: string }) {
  const q = useProposedJournals(engagementId);
  if (code === null) return <p className="px-5 py-6 text-sm text-slate-500">Pick an account with a code on the left.</p>;
  if (q.error) return <p className="px-5 py-6 text-sm text-rose-700">{(q.error as Error).message}</p>;
  if (!q.data) return <div className="p-5"><SkeletonRows rows={5} /></div>;
  const touching = q.data.filter((j) => j.status !== "REJECTED" && legs(j).some((l) => l.code === code));
  const th = "px-3 py-1.5 font-semibold";
  return (
    <div className="space-y-3 p-4">
      <p className="text-xs text-slate-600">
        <span className="font-mono font-semibold text-teal-800">{String(code).padStart(4, "0")}</span> {name}:{" "}
        {touching.length ? `${touching.length} adjustment${touching.length === 1 ? "" : "s"} to this account.` : "no adjustments to this account."}
      </p>
      {touching.map((j, i) => (
        <div key={j.id} className="overflow-hidden rounded-lg border border-slate-200">
          <div className="flex flex-wrap items-center gap-2 border-b border-slate-100 bg-slate-50 px-3 py-1.5 text-xs">
            <span className="font-semibold text-slate-900">Adjustment {i + 1}</span>
            <span className="font-mono text-[11px] text-teal-800">{j.journal_ref}</span>
            <span className="truncate text-slate-600" title={j.description}>{j.description}</span>
            <span className={cn("ml-auto rounded-full px-1.5 py-px text-[10px] font-semibold",
                                j.status === "APPROVED" ? "bg-emerald-50 text-emerald-700" : "bg-amber-50 text-amber-700")}>{STATUS[j.status]}</span>
          </div>
          <table className="w-full table-fixed text-xs">
            <thead className="text-[10.5px] uppercase tracking-wide text-slate-500">
              <tr>
                <th className={cn(th, "w-24 pl-3 text-left")}>Date</th>
                <th className={cn(th, "text-left")}>Account</th>
                <th className={cn(th, "w-28 text-right")}>Debit</th>
                <th className={cn(th, "w-28 pr-3 text-right")}>Credit</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-100">
              {legs(j).map((l, k) => (
                <tr key={k} className={cn(l.code === code && "bg-teal-50/40")}>
                  <td className="py-1.5 pl-3 text-slate-500">{(j.posted_at || j.created_at || "").slice(0, 10).split("-").reverse().join("/") || "-"}</td>
                  <td className="truncate px-3 py-1.5 text-slate-800"><span className="font-mono text-[11px] text-teal-800">{l.code}</span> {l.name}</td>
                  <td className="px-3 py-1.5 text-right font-mono">{l.debit ? formatCurrency(l.debit) : ""}</td>
                  <td className="px-3 py-1.5 pr-3 text-right font-mono">{l.credit ? formatCurrency(l.credit) : ""}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ))}
    </div>
  );
}
