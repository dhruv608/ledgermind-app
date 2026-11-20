"use client";

import { useEffect, useState } from "react";
import { useQueries } from "@tanstack/react-query";
import { ArrowLeft, CheckCircle2, ChevronRight, Paperclip } from "lucide-react";
import { jobKeys, useRollforward } from "@/lib/queries/job";
import { AskLedge } from "@/components/assistant/AskLedge";
import { Fig, FigRow, Ledger, wp, YearT } from "@/components/review/area/WorkpaperParts";
import type { Reconciliation, Reconciliations, Rollforward } from "@/lib/api";
import type { LedgerViewLine } from "@/lib/api/ledgerViews";
import { api } from "@/lib/api";
import { StatementForm } from "@/components/control-accounts/ReconciliationsPanel";
import { Button } from "@/components/ui/button";
import { SkeletonRows } from "@/components/common/SkeletonRows";
import { BankStatementLines } from "@/components/review/workpapers/BankStatementLines";
import { Tabs } from "@/components/ui/tabs";
import { formatCurrency, accountLabel } from "@/lib/formatters";
import { cn } from "@/lib/utils";

/**
 * The bank working paper on screen: Bank Summary, then each account's Detailed / Ledger / Reconciliation. One
 * summary row per bank, card, petty cash and clearing account, this year against last year and the statement; View
 * opens the account's own working paper. The figures are the engine's (the balance sheet's control accounts, the
 * account's year, its ledger lines): the Excel workbook draws the same ones.
 */
type View = "detailed" | "ledger" | "recon";

const { money, th, num } = wp;

export function BankWorkpaper({ engagementId, rows, onRecsUpdated, onAttach, onOpenChange }: {
  engagementId: string;
  rows: Reconciliation[];
  onRecsUpdated?: (next: Reconciliations) => void;
  /** Opens the area's Evidence tab, where the statement is attached */
  onAttach: () => void;
  /** Tells the page when an account's paper is open (its own figures then replace the area's) */
  onOpenChange?: (open: boolean) => void;
}) {
  const [openKey, setOpenKey] = useState<string | null>(null);
  useEffect(() => onOpenChange?.(Boolean(openKey)), [openKey, onOpenChange]);
  useEffect(() => () => onOpenChange?.(false), [onOpenChange]);     // closed when the paper leaves the page
  const [view, setView] = useState<View>("detailed");
  const row = rows.find((r) => r.key === openKey) || null;

  if (row) {
    return (
      <AccountPaper key={row.key} engagementId={engagementId} row={row} view={view} onView={setView}
                    onBack={() => setOpenKey(null)} onRecsUpdated={onRecsUpdated} onAttach={onAttach} />
    );
  }

  const total = (pick: (r: Reconciliation) => number | null) =>
    rows.every((r) => pick(r) !== null) ? rows.reduce((s, r) => s + (pick(r) ?? 0), 0) : null;
  return (
    <div className="overflow-hidden rounded-xl border border-slate-200 bg-white shadow-2xs">
      <div className="border-b border-teal-100 bg-linear-to-r from-teal-50/70 to-white px-4 py-3">
        <h3 className="text-sm font-bold text-teal-900">Bank summary</h3>
        <p className="text-[11px] text-slate-500">Each bank, card, petty cash and payment account at the year end. View opens its working paper.</p>
      </div>
      <table className="w-full table-fixed text-xs">
        <thead className="border-b border-teal-100 bg-teal-50/80 text-[10.5px] uppercase tracking-wide text-teal-800">
          <tr>
            <th className={cn(th, "pl-4 text-left")}>Particular</th>
            <th className={cn(th, "w-32 text-right")}>Current year</th>
            <th className={cn(th, "w-32 text-right")}>Previous year</th>
            <th className={cn(th, "w-32 text-right")}>Per statement</th>
            <th className={cn(th, "w-32 text-right")}>Difference</th>
            <th className="w-20 px-4 py-2" aria-label="Open" />
          </tr>
        </thead>
        <tbody className="divide-y divide-slate-100">
          {rows.map((r) => (
            <tr key={r.key} className="cursor-pointer hover:bg-teal-50/40" onClick={() => { setOpenKey(r.key); setView("detailed"); }}>
              <td className="truncate py-2 pl-4 pr-3 font-medium text-slate-800" title={r.account}>{accountLabel(r.account)}</td>
              <td className={cn(num, "font-semibold text-slate-900")}>{money(r.books)}</td>
              <td className={cn(num, "text-slate-500")}>{money(r.last_year)}</td>
              <td className={cn(num, r.other === null ? "font-sans text-[11px] text-slate-400" : "text-slate-900")}>
                {r.other === null ? "not in yet" : money(r.other)}
              </td>
              <td className="px-3 py-2 text-right">
                {r.status === "MATCHED" ? (
                  <span className="inline-flex items-center gap-1 font-semibold text-emerald-700"><CheckCircle2 className="h-3.5 w-3.5" /> Agrees</span>
                ) : r.status === "DIFFERENCE" && r.difference !== null ? (
                  <span className="inline-flex items-center gap-1 font-mono font-semibold tabular-nums text-rose-700">
                    {money(r.difference)}
                    <AskLedge icon label="Explain with Ledge" question={`Why does ${r.account} differ from the bank statement by ${money(r.difference)} (books ${money(r.books)}, statement ${money(r.other)})? What journal or document would clear it?`} />
                  </span>
                ) : <span className="text-slate-400">-</span>}
              </td>
              <td className="px-4 py-2 text-right">
                <span className="inline-flex items-center font-semibold text-teal-700">View <ChevronRight className="h-3.5 w-3.5" /></span>
              </td>
            </tr>
          ))}
        </tbody>
        <tfoot className="border-t-2 border-teal-200 bg-teal-50/70 font-bold text-teal-900">
          <tr>
            <td className="py-2 pl-4 pr-3">Total</td>
            <td className={num}>{money(total((r) => r.books))}</td>
            <td className={num}>{money(total((r) => r.last_year))}</td>
            <td className={num}>{money(total((r) => r.other))}</td>
            <td className={num}>{(() => { const d = total((r) => r.difference ?? (r.status === "MATCHED" ? 0 : null)); return d === null ? "-" : money(d); })()}</td>
            <td />
          </tr>
        </tfoot>
      </table>
    </div>
  );
}

function AccountPaper({ engagementId, row, view, onView, onBack, onRecsUpdated, onAttach }: {
  engagementId: string;
  row: Reconciliation;
  view: View;
  onView: (v: View) => void;
  onBack: () => void;
  onRecsUpdated?: (next: Reconciliations) => void;
  onAttach: () => void;
}) {
  // From the job's shared store: the account's year at once, its ledger lines only when the Ledger is opened; both
  // kept, so going back and forth asks the server nothing again
  const year = useRollforward(engagementId, row.codes);
  const ledgers = useQueries({
    queries: row.codes.map((c) => ({ queryKey: jobKeys.ledger(engagementId, c), queryFn: () => api.getLedgerViews(engagementId, c), enabled: view === "ledger" })),
  });
  const rf: Rollforward | null = year.data ?? null;
  const lines: LedgerViewLine[] | null = ledgers.every((q) => q.data) ? ledgers.flatMap((q) => q.data!.current) : null;
  const failed = year.error || ledgers.find((q) => q.error)?.error;
  const error = failed instanceof Error ? failed.message : null;

  const tabs = [
    { id: "detailed" as const, label: "Detailed" },
    { id: "ledger" as const, label: "Ledger", count: lines?.length },
    { id: "recon" as const, label: "Reconciliation" },
  ];
  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-center gap-2 text-xs">
        <button type="button" onClick={onBack} className="inline-flex items-center gap-1 font-semibold text-teal-700 hover:text-teal-900">
          <ArrowLeft className="h-3.5 w-3.5" /> Bank summary
        </button>
        <ChevronRight className="h-3.5 w-3.5 text-slate-300" />
        <span className="font-semibold text-slate-800">{accountLabel(row.account)}</span>
        <AskLedge className="ml-auto" question={`Explain the bank working paper for ${row.account}: books ${money(row.books)}, per the statement ${row.other === null ? "not in yet" : money(row.other)}, difference ${row.difference === null ? "not known" : money(row.difference)}, last year ${money(row.last_year)}. What should I check, and what is missing?`} />
      </div>
      <FigRow>
        <Fig label="Per books" value={money(row.books)} />
        <Fig label="Per statement" value={row.other === null ? "Not in yet" : money(row.other)} />
        <Fig label="Difference" value={row.status === "MATCHED" ? "Agrees" : row.difference === null ? "-" : money(row.difference)}
             tone={row.status === "MATCHED" ? "text-emerald-700" : row.difference ? "text-rose-700" : undefined} />
        <Fig label="Previous year" value={money(row.last_year)} />
      </FigRow>
      <Tabs label={`${row.account} working paper`} items={tabs} value={view} onChange={onView} />
      {error && <p className="text-[11px] text-rose-700">{error}</p>}
      {view === "detailed" && (rf ? <YearT rf={rf} /> : !error && <SkeletonRows rows={5} />)}
      {view === "ledger" && (lines && rf ? <Ledger lines={lines} opening={rf.opening} account={row.account} /> : !error && <SkeletonRows rows={8} />)}
      {view === "recon" && (
        <div className="space-y-3">
          {rf ? <Recorded rf={rf} row={row} /> : !error && <SkeletonRows rows={5} />}
          {row.codes[0] !== undefined && <BankStatementLines engagementId={engagementId} code={row.codes[0]} account={row.account} onAttach={onAttach} />}
          <div className="flex flex-wrap items-end justify-between gap-3 rounded-xl border border-slate-200 bg-white px-4 py-3 shadow-2xs">
            {onRecsUpdated ? <StatementForm row={row} engagementId={engagementId} onSaved={onRecsUpdated} /> : <span />}
            <Button variant="outline" size="sm" className="h-8 text-xs" onClick={onAttach}>
              <Paperclip className="mr-1.5 h-3.5 w-3.5" /> Attach the statement
            </Button>
          </div>
        </div>
      )}
    </div>
  );
}

/** The bank reconciliation as recorded: the books' year, then the statement and the difference. */
function Recorded({ rf, row }: { rf: Rollforward; row: Reconciliation }) {
  const receipts = rf.movements.reduce((s, m) => s + m.debit, 0);
  const payments = rf.movements.reduce((s, m) => s + m.credit, 0);
  const lines: { label: string; amount: number | null; strong?: boolean; tone?: string }[] = [
    { label: "Opening balance", amount: rf.opening },
    { label: "Add: receipts", amount: receipts },
    { label: "Less: payments", amount: -payments },
    ...(Math.abs(rf.journals) >= 0.005 ? [{ label: "Journals", amount: rf.journals }] : []),
    { label: "Closing balance per books", amount: rf.closing, strong: true },
    { label: "Balance per bank statement", amount: row.other },
    { label: "Difference", amount: row.other === null ? null : rf.closing - row.other, strong: true,
      tone: row.other !== null && Math.abs(rf.closing - row.other) >= 1 ? "text-rose-700" : "text-emerald-700" },
  ];
  return (
    <div className="overflow-hidden rounded-xl border border-slate-200 bg-white shadow-2xs">
      <table className="w-full text-xs">
        <tbody className="divide-y divide-slate-100">
          {lines.map((l) => (
            <tr key={l.label} className={cn(l.strong && "bg-slate-50/60")}>
              <td className={cn("py-2 pl-4 pr-3 text-slate-700", l.strong && "font-semibold text-slate-900")}>{l.label}</td>
              <td className={cn(num, "w-40 pr-4", l.strong && "font-semibold", l.tone)}>
                {l.amount === null ? <span className="font-sans text-[11px] text-slate-400">statement not in yet</span> : formatCurrency(l.amount)}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
      <p className="border-t border-slate-100 px-4 py-2 text-[11px] text-slate-500">
        Matching line by line (unrecorded, unmatched) needs the statement&apos;s lines; for now the balance is agreed.
      </p>
    </div>
  );
}

