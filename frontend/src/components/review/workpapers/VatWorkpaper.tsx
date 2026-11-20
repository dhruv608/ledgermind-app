"use client";

import { accountLabel } from "@/lib/formatters";
import { useEffect, useState } from "react";
import { ArrowLeft, CheckCircle2, ChevronRight, Paperclip } from "lucide-react";
import type { Reconciliation, Reconciliations } from "@/lib/api";
import { VatProofBox } from "@/components/control-accounts/ReconciliationsPanel";
import { AskLedge } from "@/components/assistant/AskLedge";
import { Fig, FigRow, Ledger, wp, YearT } from "@/components/review/area/WorkpaperParts";
import { SkeletonRows } from "@/components/common/SkeletonRows";
import { EmptyState } from "@/components/common/EmptyState";
import { SalesReconciliation } from "@/components/review/workpapers/SalesReconciliation";
import { VatHmrcAccount } from "@/components/review/workpapers/VatHmrcAccount";
import { Button } from "@/components/ui/button";
import { Tabs } from "@/components/ui/tabs";
import { useLedger, useRollforward, useVatPaid, useVatReturns } from "@/lib/queries/job";
import { cn } from "@/lib/utils";

/**
 * The VAT working paper on screen (VAT Summary by quarter, VAT Detailed, VAT Ledger and the VAT reconciliation).
 * The summary shows each return (output VAT, input VAT, owed, paid, outstanding) and the VAT account against the
 * reconciliation; View opens the account's Detailed (its year from the books), Ledger and Reconciliation (the VAT
 * proof). The figures are the engine's: the returns as read or typed, the payments matched to them, the proof.
 */
type View = "detailed" | "ledger" | "recon";
const { money, th, num } = wp;
const day = (iso?: string | null) => {
  if (!iso) return "";
  const d = new Date(`${iso.slice(0, 10)}T00:00:00`);
  return isNaN(d.getTime()) ? iso : d.toLocaleDateString("en-GB", { day: "numeric", month: "short", year: "numeric" });
};

export function VatWorkpaper({ engagementId, ties, version, onRecsUpdated, onAttach, onOpenChange, onTypeReturns }: {
  engagementId: string;
  /** The VAT area's balances: the VAT account, with its proof */
  ties: Reconciliation[];
  /** Changes when the journals do: the figures are asked for again */
  version: string;
  onRecsUpdated?: (next: Reconciliations) => void;
  onAttach: () => void;
  /** Tells the page when an account's paper is open (its own figures then replace the area's) */
  onOpenChange?: (open: boolean) => void;
  /** No returns in: where they are typed box by box */
  onTypeReturns?: () => void;
}) {
  const returns = useVatReturns(engagementId, version);
  const paid = useVatPaid(engagementId, version);
  const [openKey, setOpenKey] = useState<string | null>(null);
  useEffect(() => onOpenChange?.(Boolean(openKey)), [openKey, onOpenChange]);
  useEffect(() => () => onOpenChange?.(false), [onOpenChange]);     // closed when the paper leaves the page
  const [view, setView] = useState<View>("detailed");
  const accounts = ties.filter((r) => r.section !== "Profit and loss checks");
  const open = accounts.find((r) => r.key === openKey);
  if (open) {
    return <VatAccountPaper engagementId={engagementId} row={open} view={view} onView={setView} onBack={() => setOpenKey(null)}
                            onRecsUpdated={onRecsUpdated} onAttach={onAttach} />;
  }

  const paidBy = new Map((paid.data?.returns || []).map((r) => [r.period_end?.slice(0, 10), r]));
  const list = [...(returns.data || [])].sort((a, b) => (a.period_end || "").localeCompare(b.period_end || ""));
  const rows = list.map((r) => {
    const p = paidBy.get(r.period_end?.slice(0, 10) || "");
    return { r, output: r.box1_vat_due_sales + r.box2_vat_due_acquisitions, input: r.box4_vat_reclaimed, owed: r.box5_net_vat, paid: p?.paid ?? null, unpaid: p?.unpaid ?? null, note: p?.note, paidOn: p?.paid_on ?? [] };
  });
  const total = (f: (x: (typeof rows)[number]) => number | null) => rows.every((x) => f(x) !== null) ? rows.reduce((s, x) => s + (f(x) ?? 0), 0) : null;

  return (
    <div className="space-y-4">
      <div className="overflow-hidden rounded-xl border border-slate-200 bg-white shadow-2xs">
        <div className="border-b border-teal-100 bg-linear-to-r from-teal-50/70 to-white px-4 py-3">
          <h3 className="text-sm font-bold text-teal-900">VAT summary</h3>
          <p className="text-[11px] text-slate-500">Each return for the year: output VAT, input VAT, what was owed, paid and left unpaid.</p>
        </div>
        {paid.error && (
          <p className="flex items-center justify-between gap-2 border-b border-rose-100 bg-rose-50 px-4 py-1.5 text-[11px] text-rose-700">
            The VAT payments could not be loaded, so Paid shows as not known.
            <button type="button" className="font-semibold underline" onClick={() => paid.refetch()}>Try again</button>
          </p>
        )}
        {returns.isLoading ? <div className="p-4"><SkeletonRows rows={4} /></div> : rows.length === 0 ? (
          <EmptyState art="upload" className="rounded-none border-0 shadow-none" title="No VAT returns in yet"
                      description="Add the returns as a document, or type them box by box."
                      action={onTypeReturns ? { label: "Type the returns", onClick: onTypeReturns, variant: "outline" } : undefined} />
        ) : (
          <table className="w-full table-fixed text-xs">
            <thead className="border-b border-teal-100 bg-teal-50/80 text-[10.5px] uppercase tracking-wide text-teal-800">
              <tr>
                <th className={cn(th, "pl-4 text-left")}>Period to</th>
                <th className={cn(th, "text-right")}>Output VAT</th>
                <th className={cn(th, "text-right")}>Input VAT</th>
                <th className={cn(th, "text-right")}>Owed (box 5)</th>
                <th className={cn(th, "text-right")}>Paid</th>
                <th className={cn(th, "text-right")}>Outstanding</th>
                <th className={cn(th, "w-28 text-left")}>Date paid</th>
                <th className={cn(th, "w-[20%] text-left")}>Note</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-100">
              {rows.map(({ r, output, input, owed, paid: p, unpaid, note, paidOn }) => (
                <tr key={r.id}>
                  <td className="py-2 pl-4 pr-3 text-slate-800">{day(r.period_end) || r.period_label}</td>
                  <td className={num}>{money(output)}</td>
                  <td className={num}>{money(input)}</td>
                  <td className={cn(num, "font-semibold text-slate-900")}>{money(owed)}</td>
                  <td className={num}>{p === null ? <span className="font-sans text-[11px] text-slate-400">not known</span> : money(p)}</td>
                  <td className={cn(num, unpaid && Math.abs(unpaid) >= 1 && "font-semibold text-orange-700")}>{unpaid === null ? "-" : money(unpaid)}</td>
                  <td className="truncate px-3 py-2 text-slate-600" title={paidOn.join(", ")}>{paidOn.join(", ") || "-"}</td>
                  <td className="truncate px-3 py-2 text-[11px] text-slate-500" title={note || ""}>{note}</td>
                </tr>
              ))}
            </tbody>
            <tfoot className="border-t-2 border-teal-200 bg-teal-50/70 font-bold text-teal-900">
              <tr>
                <td className="py-2 pl-4">Year</td>
                <td className={num}>{money(total((x) => x.output))}</td>
                <td className={num}>{money(total((x) => x.input))}</td>
                <td className={num}>{money(total((x) => x.owed))}</td>
                <td className={num}>{money(total((x) => x.paid))}</td>
                <td className={num}>{money(total((x) => x.unpaid))}</td>
                <td /><td />
              </tr>
            </tfoot>
          </table>
        )}
      </div>

      <VatHmrcAccount lines={paid.data?.hmrc ?? []} />

      <SalesReconciliation engagementId={engagementId} />

      {accounts.length > 0 && (
        <div className="overflow-hidden rounded-xl border border-slate-200 bg-white shadow-2xs">
          <div className="border-b border-teal-100 bg-linear-to-r from-teal-50/70 to-white px-4 py-3">
            <h3 className="text-sm font-bold text-teal-900">VAT account</h3>
            <p className="text-[11px] text-slate-500">The VAT owed in the books against the VAT reconciliation. View opens its working paper.</p>
          </div>
          <table className="w-full table-fixed text-xs">
            <thead className="border-b border-teal-100 bg-teal-50/80 text-[10.5px] uppercase tracking-wide text-teal-800">
              <tr>
                <th className={cn(th, "pl-4 text-left")}>Particular</th>
                <th className={cn(th, "w-32 text-right")}>Current year</th>
                <th className={cn(th, "w-32 text-right")}>Previous year</th>
                <th className={cn(th, "w-36 text-right")}>Per reconciliation</th>
                <th className={cn(th, "w-32 text-right")}>Difference</th>
                <th className="w-20 px-4 py-2" aria-label="Open" />
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-100">
              {accounts.map((r) => (
                <tr key={r.key} className="cursor-pointer hover:bg-teal-50/40" onClick={() => { setOpenKey(r.key); setView("detailed"); }}>
                  <td className="truncate py-2 pl-4 pr-3 font-medium text-slate-800" title={r.account}>{accountLabel(r.account)}</td>
                  <td className={cn(num, "font-semibold text-slate-900")}>{money(r.books)}</td>
                  <td className={cn(num, "text-slate-500")}>{money(r.last_year)}</td>
                  <td className={cn(num, r.other === null ? "font-sans text-[11px] text-slate-400" : "text-slate-900")}>{r.other === null ? "not in yet" : money(r.other)}</td>
                  <td className="px-3 py-2 text-right">
                    {r.status === "MATCHED" ? <span className="inline-flex items-center gap-1 font-semibold text-emerald-700"><CheckCircle2 className="h-3.5 w-3.5" /> Agrees</span>
                      : r.status === "DIFFERENCE" && r.difference !== null ? (
                        <span className="inline-flex items-center gap-1 font-mono font-semibold tabular-nums text-rose-700">
                          {money(r.difference)}
                          <AskLedge icon label="Explain with Ledge" question={`Why does the VAT account differ from the VAT reconciliation by ${money(r.difference)} (books ${money(r.books)}, reconciliation ${money(r.other)})? What journal would clear it?`} />
                        </span>
                      )
                      : <span className="text-slate-400">-</span>}
                  </td>
                  <td className="px-4 py-2 text-right"><span className="inline-flex items-center font-semibold text-teal-700">View <ChevronRight className="h-3.5 w-3.5" /></span></td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}

/** The VAT account's working paper: its year from the books, its ledger, and the VAT reconciliation (the proof) */
function VatAccountPaper({ engagementId, row, view, onView, onBack, onRecsUpdated, onAttach }: {
  engagementId: string;
  row: Reconciliation;
  view: View;
  onView: (v: View) => void;
  onBack: () => void;
  onRecsUpdated?: (next: Reconciliations) => void;
  onAttach: () => void;
}) {
  const year = useRollforward(engagementId, row.codes);
  const ledger = useLedger(engagementId, row.codes[0], view === "ledger" && row.codes.length > 0);
  const tabs = [
    { id: "detailed" as const, label: "Detailed" },
    { id: "ledger" as const, label: "Ledger", count: ledger.data?.current.length },
    { id: "recon" as const, label: "Reconciliation" },
  ];
  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-center gap-2 text-xs">
        <button type="button" onClick={onBack} className="inline-flex items-center gap-1 font-semibold text-teal-700 hover:text-teal-900">
          <ArrowLeft className="h-3.5 w-3.5" /> VAT summary
        </button>
        <ChevronRight className="h-3.5 w-3.5 text-slate-300" />
        <span className="font-semibold text-slate-800">{accountLabel(row.account)}</span>
        <AskLedge className="ml-auto" question={`Explain the VAT working paper: VAT account per books ${money(row.books)}, per the VAT reconciliation ${row.other === null ? "not worked out" : money(row.other)}, difference ${row.difference === null ? "none known" : money(row.difference)}, last year ${money(row.last_year)}. What should I check, and what is missing?`} />
      </div>
      <FigRow>
        <Fig label="Per books" value={money(row.books)} />
        <Fig label="Per reconciliation" value={row.other === null ? "Not in yet" : money(row.other)} />
        <Fig label="Difference" value={row.status === "MATCHED" ? "Agrees" : row.difference === null ? "-" : money(row.difference)}
             tone={row.status === "MATCHED" ? "text-emerald-700" : row.difference ? "text-rose-700" : undefined} />
        <Fig label="Previous year" value={money(row.last_year)} />
      </FigRow>
      <Tabs label={`${row.account} working paper`} items={tabs} value={view} onChange={onView} />
      {view === "detailed" && (year.data ? <YearT rf={year.data} /> : year.error
        ? <p className="text-[11px] text-rose-700">{year.error.message}</p> : <SkeletonRows rows={5} />)}
      {view === "ledger" && (ledger.data ? <Ledger lines={ledger.data.current} opening={year.data?.opening ?? 0} account={row.account} /> : ledger.error
        ? <p className="text-[11px] text-rose-700">{ledger.error.message}</p> : <SkeletonRows rows={8} />)}
      {view === "recon" && (
        <div className="space-y-3">
          {row.proof ? <VatProofBox proof={row.proof} engagementId={engagementId} onSaved={(next) => onRecsUpdated?.(next)} />
            : <p className="rounded-xl border border-slate-200 bg-white px-4 py-3 text-xs text-slate-500">No VAT reconciliation yet: it is worked out once the returns are in.</p>}
          <div className="flex justify-end">
            <Button variant="outline" size="sm" className="h-8 text-xs" onClick={onAttach}>
              <Paperclip className="mr-1.5 h-3.5 w-3.5" /> Attach the VAT returns or HMRC statement
            </Button>
          </div>
        </div>
      )}
    </div>
  );
}
