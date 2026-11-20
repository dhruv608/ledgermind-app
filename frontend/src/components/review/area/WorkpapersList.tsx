"use client";

import { useState } from "react";
import { CheckCircle2, ChevronRight } from "lucide-react";
import type { AreaSignoff, Reconciliation } from "@/lib/api";
import type { Area } from "@/lib/areas";
import { areaKeyOfCode } from "@/lib/areas";
import { formatCurrency } from "@/lib/formatters";
import { cn } from "@/lib/utils";

export type PaperTone = "stop" | "needs" | "fix" | "wait" | "done";
const TONE: Record<PaperTone, string> = {
  stop: "bg-rose-50 text-rose-700", needs: "bg-orange-50 text-orange-700", fix: "bg-sky-50 text-sky-700",
  wait: "bg-slate-100 text-slate-600", done: "bg-emerald-50 text-emerald-700",
};
const DOT: Record<PaperTone, string> = {
  stop: "bg-rose-500", needs: "bg-orange-400", fix: "bg-sky-500", wait: "bg-slate-300", done: "bg-emerald-500",
};
const ROLES = [["PREPARER", "Prepared"], ["REVIEWER", "Reviewed"], ["PARTNER", "Approved"]] as const;
type Filter = "all" | "open" | "differ" | "done";

/**
 * All the working papers of the job: each one's balances this year and last year, where it stands and its
 * sign-off; a row opens it. Built from what the page already holds (the balances, the points, the sign-offs):
 * nothing more is asked of the server.
 */
export function WorkpapersList({ papers, status, rows, signoffs, onOpen }: {
  papers: Area[];
  status: (key: string) => { text: string; tone: PaperTone };
  /** The balance sheet balances (the control accounts) */
  rows: Reconciliation[];
  signoffs: Record<string, AreaSignoff[]>;
  onOpen: (key: string) => void;
}) {
  const [filter, setFilter] = useState<Filter>("all");
  const balances = (key: string) => rows.filter((r) => r.section !== "Profit and loss checks" && r.codes.some((c) => areaKeyOfCode(c) === key));
  const sum = (list: Reconciliation[], pick: (r: Reconciliation) => number | null) =>
    list.length && list.every((r) => pick(r) !== null) ? list.reduce((s, r) => s + (pick(r) ?? 0), 0) : null;
  const signedBy = (key: string) => new Set((signoffs[key] || []).map((s) => s.role));
  const kinds: Record<Filter, (key: string) => boolean> = {
    all: () => true,
    open: (k) => ["needs", "fix"].includes(status(k).tone),
    differ: (k) => status(k).tone === "stop",
    done: (k) => status(k).tone === "done",
  };
  const done = papers.filter((a) => status(a.key).tone === "done").length;
  const approved = papers.filter((a) => signedBy(a.key).has("PARTNER")).length;
  const shown = papers.filter((a) => kinds[filter](a.key));

  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div className="min-w-[14rem] flex-1">
          <p className="text-[11px] font-semibold text-slate-600">{done} of {papers.length} done · {approved} signed off</p>
          <div className="mt-1.5 h-1 max-w-sm overflow-hidden rounded-full bg-slate-100">
            <div className="h-full rounded-full bg-teal-500 transition-all" style={{ width: `${papers.length ? (100 * done) / papers.length : 0}%` }} />
          </div>
        </div>
        <div className="inline-flex rounded-lg border border-slate-200 bg-white p-0.5 text-[11px] font-medium">
          {([["all", "All"], ["open", "To look at"], ["differ", "Differences"], ["done", "Done"]] as const).map(([k, label]) => (
            <button key={k} type="button" onClick={() => setFilter(k)}
                    className={cn("rounded-md px-2.5 py-1 transition-colors",
                                  filter === k ? "bg-teal-50 text-teal-800" : "text-slate-600 hover:bg-teal-50/60 hover:text-teal-800")}>
              {label} <span className="tabular-nums text-slate-400">{papers.filter((a) => kinds[k](a.key)).length}</span>
            </button>
          ))}
        </div>
      </div>

      <div className="overflow-hidden rounded-xl border border-slate-200 bg-white shadow-2xs">
        <table className="w-full text-xs">
          <thead className="border-b border-teal-100 bg-teal-50/80 text-[10.5px] uppercase tracking-wide text-teal-800">
            <tr>
              <th className="px-4 py-2 text-left font-semibold">Working paper</th>
              <th className="w-36 px-3 py-2 text-right font-semibold">Current year</th>
              <th className="w-36 px-3 py-2 text-right font-semibold">Previous year</th>
              <th className="w-40 px-3 py-2 text-left font-semibold">Status</th>
              <th className="px-3 py-2 text-left font-semibold">Sign-off</th>
              <th className="w-16 px-4 py-2" aria-label="Open" />
            </tr>
          </thead>
          <tbody className="divide-y divide-slate-100">
            {shown.map((a) => {
              const st = status(a.key);
              const list = balances(a.key);
              const signed = signedBy(a.key);
              return (
                <tr key={a.key} className="cursor-pointer hover:bg-teal-50/40" onClick={() => onOpen(a.key)}>
                  <td className="px-4 py-2.5 font-semibold text-slate-800">
                    <span className={cn("mr-2 inline-block h-2 w-2 rounded-full align-middle", DOT[st.tone])} />{a.label}
                  </td>
                  <td className="px-3 py-2.5 text-right font-mono tabular-nums text-slate-900">{list.length ? formatCurrency(sum(list, (r) => r.books) ?? 0) : "-"}</td>
                  <td className="px-3 py-2.5 text-right font-mono tabular-nums text-slate-500">{(() => { const v = sum(list, (r) => r.last_year); return v === null ? "-" : formatCurrency(v); })()}</td>
                  <td className="px-3 py-2.5">
                    <span className={cn("inline-flex items-center gap-1 whitespace-nowrap rounded-full px-2 py-0.5 text-[10.5px] font-bold", TONE[st.tone])}>
                      {st.tone === "done" && <CheckCircle2 className="h-3 w-3" />}{st.text}
                    </span>
                  </td>
                  <td className="px-3 py-2.5">
                    <span className="flex gap-1">
                      {ROLES.map(([role, label]) => (
                        <span key={role} title={label}
                              className={cn("rounded-full px-1.5 py-px text-[10px] font-semibold",
                                            signed.has(role) ? "bg-teal-50 text-teal-700" : "bg-slate-50 text-slate-300")}>{label}</span>
                      ))}
                    </span>
                  </td>
                  <td className="px-4 py-2.5 text-right"><ChevronRight className="ml-auto h-4 w-4 text-teal-600" /></td>
                </tr>
              );
            })}
            {shown.length === 0 && (
              <tr><td colSpan={6} className="px-4 py-4 text-center text-xs text-slate-500">No working papers of this kind.</td></tr>
            )}
          </tbody>
        </table>
      </div>
      <p className="text-[11px] text-slate-500">
        Status comes from the work itself: points to look at, a difference to clear, journals ready, or done. Signed off when prepared, reviewed and approved.
      </p>
    </div>
  );
}
