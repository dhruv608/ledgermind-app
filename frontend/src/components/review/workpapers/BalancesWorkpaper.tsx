"use client";

import { accountLabel } from "@/lib/formatters";
import { useEffect, useState } from "react";
import { useQueries } from "@tanstack/react-query";
import { ArrowLeft, CheckCircle2, ChevronRight, Paperclip } from "lucide-react";
import type { Reconciliation, Reconciliations } from "@/lib/api";
import { api } from "@/lib/api";
import { AgreeForm, byHand, DebtorAgeingBox, StatementForm } from "@/components/control-accounts/ReconciliationsPanel";
import { AskLedge } from "@/components/assistant/AskLedge";
import { Fig, FigRow, Ledger, wp, YearT } from "@/components/review/area/WorkpaperParts";
import { SkeletonRows } from "@/components/common/SkeletonRows";
import { TradeAdjustments } from "@/components/review/workpapers/TradeAdjustments";
import { Button } from "@/components/ui/button";
import { Tabs } from "@/components/ui/tabs";
import { jobKeys, useRollforward } from "@/lib/queries/job";
import { cn } from "@/lib/utils";

/**
 * A balance sheet area's working paper on screen (Debtors and Creditors summaries, each balance's Detailed, Listing,
 * Ledger; Other debtors / Other creditors). The summary shows each balance in its section (trade, other ...) this
 * year against last year and the document; View opens the balance's Detailed (its year from the books), Ledger and
 * Reconciliation (the aged listing for trade balances, or the document it is agreed to). Used by Debtors and
 * Creditors, and the other balance sheet areas.
 */
type View = "detailed" | "ledger" | "recon";
export interface BalanceGroup {
  title: string;
  listing?: "AR" | "AP";
  list: Reconciliation[];
  /** Its heading shows even when it is the only group (each loan by name) */
  always?: boolean;
}
const { money, th, num } = wp;

export function BalancesWorkpaper({ engagementId, title, intro, groups, onRecsUpdated, onAttach, onOpenChange }: {
  engagementId: string;
  /** The summary's name ("Debtors summary") */
  title: string;
  intro: string;
  groups: BalanceGroup[];
  onRecsUpdated?: (next: Reconciliations) => void;
  onAttach: () => void;
  /** Tells the page when an account's paper is open (its own figures then replace the area's) */
  onOpenChange?: (open: boolean) => void;
}) {
  const [openKey, setOpenKey] = useState<string | null>(null);
  useEffect(() => onOpenChange?.(Boolean(openKey)), [openKey, onOpenChange]);
  useEffect(() => () => onOpenChange?.(false), [onOpenChange]);     // closed when the paper leaves the page
  const [view, setView] = useState<View>("detailed");
  // Search and sort A-Z (a heading sorts by it; again, the other way)
  const [q, setQ] = useState("");
  const [sort, setSort] = useState<{ by: "name" | "cy" | "py"; desc: boolean } | null>(null);
  const all = groups.flatMap((g) => g.list.map((row) => ({ row, listing: g.listing })));
  const open = all.find((x) => x.row.key === openKey);
  if (open) {
    return <BalancePaper engagementId={engagementId} row={open.row} listing={open.listing} back={title} view={view} onView={setView}
                         onBack={() => setOpenKey(null)} onRecsUpdated={onRecsUpdated} onAttach={onAttach} />;
  }
  const total = (list: Reconciliation[], pick: (r: Reconciliation) => number | null) =>
    list.length && list.every((r) => pick(r) !== null) ? list.reduce((s, r) => s + (pick(r) ?? 0), 0) : null;
  const rows = all.map((x) => x.row);
  const showSearch = rows.length > 8;
  const order = (list: Reconciliation[]) => {
    const found = q ? list.filter((r) => r.account.toLowerCase().includes(q.toLowerCase())) : list;
    if (!sort) return found;
    const val = (r: Reconciliation) => (sort.by === "name" ? r.account.toLowerCase() : sort.by === "cy" ? r.books : r.last_year ?? 0);
    return [...found].sort((a, b) => (val(a) < val(b) ? -1 : val(a) > val(b) ? 1 : 0) * (sort.desc ? -1 : 1));
  };
  const head = (by: "name" | "cy" | "py", label: string, cls: string) => (
    <th className={cls} aria-sort={sort?.by === by ? (sort.desc ? "descending" : "ascending") : undefined}>
      <button type="button" className="inline-flex items-center gap-0.5 uppercase hover:text-teal-950"
              onClick={() => setSort(sort?.by === by ? { by, desc: !sort.desc } : { by, desc: by !== "name" })}>
        {label}{sort?.by === by ? (sort.desc ? " ↓" : " ↑") : ""}
      </button>
    </th>
  );

  return (
    <div className="overflow-hidden rounded-xl border border-slate-200 bg-white shadow-2xs">
      <div className="flex flex-wrap items-end justify-between gap-2 border-b border-teal-100 bg-linear-to-r from-teal-50/70 to-white px-4 py-3">
        <div>
          <h3 className="text-sm font-bold text-teal-900">{title}</h3>
          <p className="text-[11px] text-slate-500">{intro}</p>
        </div>
        {showSearch && (
          <input aria-label="Search the balances" value={q} onChange={(e) => setQ(e.target.value)} placeholder="Search"
                 className="h-7 w-44 rounded-md border border-slate-300 bg-white px-2 text-xs focus:outline-none focus:ring-2 focus:ring-teal-200" />
        )}
      </div>
      <table className="w-full table-fixed text-xs">
        <thead className="border-b border-teal-100 bg-teal-50/80 text-[10.5px] uppercase tracking-wide text-teal-800">
          <tr>
            {head("name", "Particular", cn(th, "pl-4 text-left"))}
            {head("cy", "Current year", cn(th, "w-32 text-right"))}
            {head("py", "Previous year", cn(th, "w-32 text-right"))}
            <th className={cn(th, "w-36 text-right")}>Per document</th>
            <th className={cn(th, "w-36 text-right")}>Difference</th>
            <th className="w-20 px-4 py-2" aria-label="Open" />
          </tr>
        </thead>
        {groups.filter((g) => order(g.list).length > 0).map((g) => (
          <tbody key={g.title || "all"} className="divide-y divide-slate-100">
            {g.title && (g.always || groups.filter((x) => x.list.length > 0).length > 1) && (
              <tr><td colSpan={6} className="bg-slate-50/70 px-4 py-1.5 text-[10.5px] font-semibold uppercase tracking-wide text-slate-500">{g.title}</td></tr>
            )}
            {order(g.list).map((r) => (
              <tr key={r.key} className="cursor-pointer hover:bg-teal-50/40" onClick={() => { setOpenKey(r.key); setView("detailed"); }}>
                <td className="truncate py-2 pl-4 pr-3 font-medium text-slate-800" title={r.account}>
                  {/* Under its group's heading, the row without the group's name again (a loan's "Less than 1 year") */}
                  {g.title && r.account.startsWith(`${g.title}: `) ? r.account.slice(g.title.length + 2) : accountLabel(r.account)}
                </td>
                <td className={cn(num, "font-semibold text-slate-900")}>{money(r.books)}</td>
                <td className={cn(num, "text-slate-500")}>{money(r.last_year)}</td>
                <td className={cn(num, r.ticked ? "font-sans text-[11px] text-emerald-700" : r.other === null ? "font-sans text-[11px] text-slate-400" : "text-slate-900")}>
                  {r.ticked ? "agreed" : r.other === null ? "not in yet" : money(r.other)}
                </td>
                <td className="px-3 py-2 text-right">
                  {r.status === "MATCHED" ? <span className="inline-flex items-center gap-1 font-semibold text-emerald-700"><CheckCircle2 className="h-3.5 w-3.5" /> Agrees</span>
                    : r.status === "DIFFERENCE" && r.difference !== null ? (
                      <span className="inline-flex items-center gap-1 font-mono font-semibold tabular-nums text-rose-700">
                        {money(r.difference)}
                        <AskLedge icon label="Explain with Ledge" question={`Why does ${r.account} differ from ${r.compared_with.toLowerCase()} by ${money(r.difference)} (books ${money(r.books)}, document ${money(r.other)})? What journal or document would clear it?`} />
                      </span>
                    ) : <span className="text-slate-400">-</span>}
                </td>
                <td className="px-4 py-2 text-right"><span className="inline-flex items-center font-semibold text-teal-700">View <ChevronRight className="h-3.5 w-3.5" /></span></td>
              </tr>
            ))}
          </tbody>
        ))}
        <tfoot className="border-t-2 border-teal-200 bg-teal-50/70 font-bold text-teal-900">
          <tr>
            <td className="py-2 pl-4 pr-3">Total</td>
            <td className={num}>{money(total(rows, (r) => r.books))}</td>
            <td className={num}>{money(total(rows, (r) => r.last_year))}</td>
            <td /><td /><td />
          </tr>
        </tfoot>
      </table>
    </div>
  );
}

/** One balance's working paper: its year from the books, its ledger, and what it is agreed to */
function BalancePaper({ engagementId, row, listing, back, view, onView, onBack, onRecsUpdated, onAttach }: {
  engagementId: string;
  row: Reconciliation;
  listing?: "AR" | "AP";
  back: string;
  view: View;
  onView: (v: View) => void;
  onBack: () => void;
  onRecsUpdated?: (next: Reconciliations) => void;
  onAttach: () => void;
}) {
  const year = useRollforward(engagementId, row.codes);
  const ledgers = useQueries({
    queries: row.codes.map((c) => ({ queryKey: jobKeys.ledger(engagementId, c), queryFn: () => api.getLedgerViews(engagementId, c), enabled: view === "ledger" })),
  });
  const lines = ledgers.every((q) => q.data) ? ledgers.flatMap((q) => q.data!.current) : null;
  const failed = year.error || ledgers.find((q) => q.error)?.error;
  // The aged listing for the trade balance (the whole trade code: the listing is the customers' or suppliers' total)
  const trade = listing && (row.key === "ar" || row.key === "ap" || row.codes.every((c) => c === (listing === "AR" ? 4400 : 5200)));
  const tabs = [
    { id: "detailed" as const, label: "Detailed" },
    { id: "ledger" as const, label: "Ledger", count: lines?.length },
    { id: "recon" as const, label: trade ? "Listing and reconciliation" : "Reconciliation" },
  ];
  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-center gap-2 text-xs">
        <button type="button" onClick={onBack} className="inline-flex items-center gap-1 font-semibold text-teal-700 hover:text-teal-900">
          <ArrowLeft className="h-3.5 w-3.5" /> {back}
        </button>
        <ChevronRight className="h-3.5 w-3.5 text-slate-300" />
        <span className="font-semibold text-slate-800">{accountLabel(row.account)}</span>
        <AskLedge className="ml-auto" question={`Explain the working paper for ${row.account}: books ${money(row.books)}, ${row.compared_with.toLowerCase()} ${row.ticked ? "ticked as agreed" : row.other === null ? "not in yet" : money(row.other)}, difference ${row.difference === null ? "not known" : money(row.difference)}, last year ${money(row.last_year)}. What should I check, and what is missing?`} />
      </div>
      <FigRow>
        <Fig label="Per books" value={money(row.books)} />
        <Fig label={row.compared_with} value={row.ticked ? "Agreed" : row.other === null ? "Not in yet" : money(row.other)} />
        <Fig label="Difference" value={row.status === "MATCHED" ? "Agrees" : row.difference === null ? "-" : money(row.difference)}
             tone={row.status === "MATCHED" ? "text-emerald-700" : row.difference ? "text-rose-700" : undefined} />
        <Fig label="Previous year" value={money(row.last_year)} />
      </FigRow>
      <Tabs label={`${row.account} working paper`} items={tabs} value={view} onChange={onView} />
      {failed instanceof Error && <p className="text-[11px] text-rose-700">{failed.message}</p>}
      {view === "detailed" && (row.codes.length === 0 ? <p className="text-xs text-slate-500">No account code on this balance.</p>
        : year.data ? <YearT rf={year.data} /> : !failed && <SkeletonRows rows={5} />)}
      {/* Trade debtors / creditors: the Adjustments block under the T */}
      {view === "detailed" && trade && <TradeAdjustments engagementId={engagementId} side={listing === "AR" ? "customer" : "supplier"} />}
      {view === "ledger" && (lines ? <Ledger lines={lines} opening={year.data?.opening ?? 0} account={row.account} /> : !failed && <SkeletonRows rows={8} />)}
      {view === "recon" && (
        <div className="space-y-3">
          {trade && <DebtorAgeingBox engagementId={engagementId} kind={listing} />}
          <div className="flex flex-wrap items-end justify-between gap-3 rounded-xl border border-slate-200 bg-white px-4 py-3 shadow-2xs">
            {onRecsUpdated && row.key.startsWith("bank:") ? <StatementForm row={row} engagementId={engagementId} onSaved={onRecsUpdated} />
              : onRecsUpdated && byHand(row.key) ? <AgreeForm row={row} engagementId={engagementId} onSaved={onRecsUpdated} />
              : <span className="text-[11px] text-slate-500">{row.note || `Agreed to: ${row.compared_with.toLowerCase()}.`}</span>}
            <Button variant="outline" size="sm" className="h-8 text-xs" onClick={onAttach}>
              <Paperclip className="mr-1.5 h-3.5 w-3.5" /> Attach the document
            </Button>
          </div>
        </div>
      )}
    </div>
  );
}
