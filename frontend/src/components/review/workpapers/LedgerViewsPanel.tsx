"use client";

import { useEffect, useMemo, useState } from "react";
import { Loader2 } from "lucide-react";
import type { LedgerViews } from "@/lib/api";
import { api } from "@/lib/api";
import { CustomSelect } from "@/components/ui/custom-select";
import { cn } from "@/lib/utils";
import { formatCurrency } from "@/lib/formatters";
import { usePagination } from "@/hooks/usePagination";
import { PageControls } from "@/components/common/Pagination";

type View = "original" | "current" | "moved_out" | "moved_in" | "journals";

const VIEWS: { id: View; label: string }[] = [
  { id: "current", label: "Current" },
  { id: "original", label: "Original" },
  { id: "moved_out", label: "Moved out" },
  { id: "moved_in", label: "Moved in" },
  { id: "journals", label: "Journals" },
];

const money = (n: number) => formatCurrency(n);
const day = (d: string | null) => (d ? new Date(d).toLocaleDateString("en-GB") : "");

interface Row { key: string; date: string | null; text: string; detail: string; amount: number; status?: string }

/** One account's ledger in five views (Show Original, Show Current, Reclassified From, Reclassified To, Show
 *  Journal; every column filterable, totals worked out again): the audit trail of what was moved where and by which
 *  journal. */
export function LedgerViewsPanel({ engagementId, codes }: { engagementId: string; codes: { code: number; name: string }[] }) {
  const [code, setCode] = useState<number | null>(codes[0]?.code ?? null);
  const [data, setData] = useState<LedgerViews | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [view, setView] = useState<View>("current");
  const [filters, setFilters] = useState({ date: "", text: "", detail: "", amount: "" });

  useEffect(() => {
    if (code === null) return;
    setData(null);
    setError(null);
    api.getLedgerViews(engagementId, code).then(setData).catch((e) => setError(e.message));
  }, [engagementId, code]);

  const rows: Row[] = useMemo(() => {
    if (!data) return [];
    if (view === "journals") {
      return data.journals.map((j) => ({ key: String(j.id), date: j.date, text: `${j.ref} ${j.description}`,
        detail: `${j.source.toLowerCase()}${j.line_move ? " · moves lines" : ""}`, amount: j.effect, status: j.status }));
    }
    if (view === "moved_out" || view === "moved_in") {
      return data[view].map((m) => ({ key: m.key, date: m.date, text: m.description,
        detail: view === "moved_out" ? `to ${m.to} ${m.to_name} · ${m.how} ${m.journal_ref}${m.remark ? `: ${m.remark}` : ""}`
          : `from ${m.from} ${m.from_name} · ${m.how} ${m.journal_ref}${m.remark ? `: ${m.remark}` : ""}`,
        amount: m.net, status: m.journal_status }));
    }
    return data[view].map((l) => ({ key: l.key, date: l.date, text: l.description, detail: l.note || l.account, amount: l.net }));
  }, [data, view]);

  const shown = rows.filter((r) =>
    (!filters.date || day(r.date).includes(filters.date)) &&
    (!filters.text || r.text.toLowerCase().includes(filters.text.toLowerCase())) &&
    (!filters.detail || r.detail.toLowerCase().includes(filters.detail.toLowerCase())) &&
    (!filters.amount || money(r.amount).replace(/[£,]/g, "").includes(filters.amount.replace(/[£,]/g, ""))));
  const total = shown.reduce((s, r) => s + r.amount, 0);
  const page = usePagination({ items: shown, initialPageSize: 50, resetDependencies: [view, filters, data] });
  const counts: Record<View, number> = data
    ? { current: data.current.length, original: data.original.length, moved_out: data.moved_out.length,
        moved_in: data.moved_in.length, journals: data.journals.length }
    : { current: 0, original: 0, moved_out: 0, moved_in: 0, journals: 0 };

  if (!codes.length) return null;
  const input = (k: keyof typeof filters, label: string, right = false) => (
    <input value={filters[k]} onChange={(e) => setFilters((f) => ({ ...f, [k]: e.target.value }))} placeholder={label}
           aria-label={`Filter by ${label.toLowerCase()}`}
           className={cn("h-7 w-full rounded border border-slate-200 bg-white px-1.5 text-[11px] font-normal normal-case tracking-normal focus:outline-none focus:ring-1 focus:ring-teal-300", right && "text-right")} />
  );

  return (
    <div className="overflow-hidden rounded-xl border border-slate-200 bg-white shadow-2xs">
      <div className="flex flex-wrap items-center justify-between gap-2 border-b border-slate-100 bg-slate-50 px-4 py-2.5 text-xs">
        <span className="font-semibold text-slate-700">Ledger views</span>
        {codes.length > 1 && (
          <CustomSelect size="sm" align="right" value={code ?? ""} onChange={(v) => setCode(Number(v))}
                        buttonClassName="max-w-[20rem]" searchable={codes.length > 8}
                        options={codes.map((c) => ({ value: c.code, label: `${c.code} ${c.name}` }))} />
        )}
      </div>
      {data && (
        <div className="grid grid-cols-2 gap-2 border-b border-slate-100 px-4 py-2.5 text-xs sm:grid-cols-4">
          <Fig label="Original" value={money(data.totals.original)} />
          <Fig label="Approved journals" value={money(data.totals.approved_journals)} />
          <Fig label="Current" value={money(data.totals.current)} strong />
          <Fig label="Journals to decide" value={money(data.totals.to_decide)} muted={!data.totals.to_decide} />
        </div>
      )}
      <div role="tablist" aria-label="Ledger view" className="flex flex-wrap gap-1 border-b border-slate-100 px-3 pt-2">
        {VIEWS.map((v) => (
          <button key={v.id} type="button" role="tab" aria-selected={view === v.id} onClick={() => setView(v.id)}
                  className={cn("-mb-px border-b-2 px-2.5 py-1.5 text-xs font-semibold",
                                view === v.id ? "border-teal-600 text-teal-700" : "border-transparent text-slate-500 hover:text-slate-800")}>
            {v.label}
            <span className="ml-1 rounded-full bg-slate-100 px-1.5 py-px text-[10px] text-slate-600">{counts[v.id]}</span>
          </button>
        ))}
      </div>
      {error ? (
        <p className="px-4 py-3 text-xs text-rose-700">{error}</p>
      ) : !data ? (
        <p className="flex items-center gap-2 px-4 py-3 text-xs text-slate-500"><Loader2 className="h-4 w-4 animate-spin" /> Loading the ledger…</p>
      ) : (
        <div className="max-h-[28rem] overflow-auto">
          <table className="w-full table-fixed text-xs">
            <thead className="sticky top-0 bg-white text-[10.5px] uppercase tracking-wide text-slate-500 shadow-[0_1px_0_#e2e8f0]">
              <tr className="text-left">
                <th className="w-24 px-3 pt-2 font-semibold">Date</th>
                <th className="px-2 pt-2 font-semibold">{view === "journals" ? "Journal" : "Description"}</th>
                <th className="w-[32%] px-2 pt-2 font-semibold">{view === "moved_out" ? "Moved to" : view === "moved_in" ? "Moved from" : view === "journals" ? "Source" : "Account / note"}</th>
                <th className="w-28 px-3 pt-2 text-right font-semibold">Amount</th>
              </tr>
              <tr>
                <th className="px-3 pb-2 pt-1">{input("date", "Date")}</th>
                <th className="px-2 pb-2 pt-1">{input("text", "Text")}</th>
                <th className="px-2 pb-2 pt-1">{input("detail", "Text")}</th>
                <th className="px-3 pb-2 pt-1">{input("amount", "Amount", true)}</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-100">
              {page.paginatedItems.map((r) => (
                <tr key={r.key}>
                  <td className="px-3 py-1.5 tabular-nums text-slate-600">{day(r.date)}</td>
                  <td className="truncate px-2 py-1.5 text-slate-800" title={r.text}>{r.text}</td>
                  <td className="truncate px-2 py-1.5 text-slate-500" title={r.detail}>
                    {r.detail}
                    {r.status && r.status !== "APPROVED" && <span className="ml-1.5 rounded-full bg-sky-100 px-1.5 py-px text-[10px] font-bold text-sky-800">to decide</span>}
                  </td>
                  <td className="px-3 py-1.5 text-right font-mono tabular-nums text-slate-900">{money(r.amount)}</td>
                </tr>
              ))}
              {shown.length === 0 && (
                <tr><td colSpan={4} className="px-3 py-3 text-center text-slate-500">
                  {rows.length ? "No lines match the filters." : view === "moved_out" || view === "moved_in" ? "Nothing moved." : "No lines."}
                </td></tr>
              )}
            </tbody>
            <tfoot>
              <tr className="border-t border-slate-200 bg-slate-50 font-semibold">
                <td colSpan={3} className="px-3 py-2 text-slate-700">{shown.length} line{shown.length === 1 ? "" : "s"}{shown.length !== rows.length ? ` of ${rows.length}` : ""}</td>
                <td className="px-3 py-2 text-right font-mono tabular-nums text-slate-900">{money(total)}</td>
              </tr>
            </tfoot>
          </table>
          <PageControls page={page} itemLabel="lines" sizes={[50, 100, 200]} />
        </div>
      )}
    </div>
  );
}

function Fig({ label, value, strong, muted }: { label: string; value: string; strong?: boolean; muted?: boolean }) {
  return (
    <div>
      <p className="text-[10.5px] text-slate-500">{label}</p>
      <p className={cn("font-mono tabular-nums", strong ? "font-bold text-slate-900" : muted ? "text-slate-400" : "text-slate-800")}>{value}</p>
    </div>
  );
}
