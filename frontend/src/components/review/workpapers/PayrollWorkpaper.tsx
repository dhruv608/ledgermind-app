"use client";

import { accountLabel } from "@/lib/formatters";
import { useEffect, useState } from "react";
import { ArrowLeft, CheckCircle2, ChevronRight, Paperclip } from "lucide-react";
import type { PayrollTable, Reconciliation, Reconciliations } from "@/lib/api";
import { StatementForm } from "@/components/control-accounts/ReconciliationsPanel";
import { PayrollMonthsPanel } from "@/components/control-accounts/PayrollMonthsPanel";
import { AskLedge } from "@/components/assistant/AskLedge";
import { Fig, FigRow, Ledger, TAccount, wp, type TLine } from "@/components/review/area/WorkpaperParts";
import { SkeletonRows } from "@/components/common/SkeletonRows";
import { PayrollSummary } from "@/components/review/workpapers/PayrollSummary";
import { wagesSplit } from "@/components/review/workpapers/wagesSplit";
import { Button } from "@/components/ui/button";
import { Tabs } from "@/components/ui/tabs";
import { useLedger, usePayrollMonths, usePayrollSummary } from "@/lib/queries/job";
import { cn } from "@/lib/utils";

/**
 * The payroll working paper on screen (Wages Summary; Wages, PAYE and Pension Payable Detailed; the monthly Wages,
 * PAYE and Pension Reconciliations; Payroll Summary). The summary shows what is owed for pay at the year end and the
 * pay costs against the payroll report; View opens one payable's Detailed (its T), Ledger and Reconciliation (month
 * by month: owed, paid, outstanding). The figures are the engine's payroll by month, the same as the workbook's G6
 * to G8.
 */
type Open = PayrollTable["key"] | "months" | null;
type View = "detailed" | "ledger" | "recon";

const LABEL: Record<PayrollTable["key"], string> = {
  net_wages: "Net wages payable", paye: "PAYE and NI payable", pension: "Pension payable",
};
// The firm code each payable is kept on (its ledger)
const CODE: Record<PayrollTable["key"], number> = { net_wages: 5330, paye: 5320, pension: 5352 };
const { money, th, num } = wp;
const sum = (t: PayrollTable, f: "owed" | "paid" | "allowance") => t.months.reduce((s, m) => s + m[f], 0);
const monthLabel = (iso: string) => new Date(`${iso}T00:00:00`).toLocaleDateString("en-GB", { month: "short", year: "numeric" });

export function PayrollWorkpaper({ engagementId, ties, version, onRecsUpdated, onAttach, onOpenChange }: {
  engagementId: string;
  /** The payroll area's balances (the control accounts) and pay cost checks */
  ties: Reconciliation[];
  /** Changes when the journals do: the figures are asked for again */
  version: string;
  onRecsUpdated?: (next: Reconciliations) => void;
  onAttach: () => void;
  /** Tells the page when an account's paper is open (its own figures then replace the area's) */
  onOpenChange?: (open: boolean) => void;
}) {
  const months = usePayrollMonths(engagementId, version);
  const [open, setOpen] = useState<Open>(null);
  useEffect(() => onOpenChange?.(Boolean(open)), [open, onOpenChange]);
  useEffect(() => () => onOpenChange?.(false), [onOpenChange]);     // closed when the paper leaves the page
  const [view, setView] = useState<View>("detailed");
  const tables = months.data?.tables || [];
  const costs = ties.filter((r) => r.section === "Profit and loss checks");
  const statementOf = (key: PayrollTable["key"]) => ties.find((r) => r.section !== "Profit and loss checks" && r.codes.includes(CODE[key]));

  if (months.error) return <p className="text-[11px] text-rose-700">{months.error.message}</p>;
  if (!months.data) return <SkeletonRows rows={5} />;
  if (open === "months") {
    return (
      <div className="space-y-3">
        <Crumb onBack={() => setOpen(null)} here="Payroll by month" />
        <PayrollMonthsPanel engagementId={engagementId} refreshKey={version} showEmpty />
      </div>
    );
  }
  const table = tables.find((t) => t.key === open);
  if (table) {
    return <PayablePaper engagementId={engagementId} t={table} statement={statementOf(table.key)} view={view} onView={setView}
                         onBack={() => setOpen(null)} onRecsUpdated={onRecsUpdated} onAttach={onAttach} />;
  }

  return (
    <div className="space-y-4">
      <div className="overflow-hidden rounded-xl border border-slate-200 bg-white shadow-2xs">
        <div className="flex flex-wrap items-center justify-between gap-2 border-b border-teal-100 bg-linear-to-r from-teal-50/70 to-white px-4 py-3">
          <div>
            <h3 className="text-sm font-bold text-teal-900">Wages summary</h3>
            <p className="text-[11px] text-slate-500">What the company owes for pay at the year end. View opens each one&apos;s working paper.</p>
          </div>
          <Button variant="outline" size="sm" className="h-8 text-xs" onClick={() => setOpen("months")}>Payroll by month</Button>
        </div>
        {tables.length === 0 ? (
          <p className="px-4 py-3 text-xs text-slate-500">No payroll in the books: no net wages, PAYE / NI or pension owed.</p>
        ) : (
          <table className="w-full table-fixed text-xs">
            <thead className="border-b border-teal-100 bg-teal-50/80 text-[10.5px] uppercase tracking-wide text-teal-800">
              <tr>
                <th className={cn(th, "pl-4 text-left")}>Particular</th>
                <th className={cn(th, "w-32 text-right")}>Current year</th>
                <th className={cn(th, "w-32 text-right")}>Previous year</th>
                <th className={cn(th, "w-36 text-right")}>Per statement</th>
                <th className={cn(th, "w-32 text-right")}>Difference</th>
                <th className="w-20 px-4 py-2" aria-label="Open" />
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-100">
              {tables.map((t) => {
                const st = statementOf(t.key);
                return (
                  <tr key={t.key} className="cursor-pointer hover:bg-teal-50/40" onClick={() => { setOpen(t.key); setView("detailed"); }}>
                    <td className="py-2 pl-4 pr-3 font-medium text-slate-800">
                      {LABEL[t.key]}
                      {t.flags > 0 && <span className="ml-2 rounded-full bg-orange-50 px-1.5 py-px text-[10px] font-bold text-orange-700">{t.flags} month{t.flags === 1 ? "" : "s"} to look at</span>}
                    </td>
                    <td className={cn(num, "font-semibold text-slate-900")}>{money(t.closing)}</td>
                    <td className={cn(num, "text-slate-500")}>{money(t.opening)}</td>
                    <td className={cn(num, !st || st.other === null ? "font-sans text-[11px] text-slate-400" : "text-slate-900")}>
                      {!st || st.other === null ? "not in yet" : money(-st.other)}
                    </td>
                    <td className="px-3 py-2 text-right"><Diff row={st} /></td>
                    <td className="px-4 py-2 text-right"><ViewLink /></td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        )}
      </div>

      <PayrollSummary engagementId={engagementId} />

      {costs.length > 0 && (
        <div className="overflow-hidden rounded-xl border border-slate-200 bg-white shadow-2xs">
          <div className="border-b border-teal-100 bg-linear-to-r from-teal-50/70 to-white px-4 py-3">
            <h3 className="text-sm font-bold text-teal-900">Pay costs against the payroll report</h3>
            <p className="text-[11px] text-slate-500">The costs in the profit and loss account against the payroll report for the year.</p>
          </div>
          <table className="w-full table-fixed text-xs">
            <thead className="border-b border-teal-100 bg-teal-50/80 text-[10.5px] uppercase tracking-wide text-teal-800">
              <tr>
                <th className={cn(th, "pl-4 text-left")}>Particular</th>
                <th className={cn(th, "w-32 text-right")}>Per books</th>
                <th className={cn(th, "w-36 text-right")}>Per payroll report</th>
                <th className={cn(th, "w-32 text-right")}>Difference</th>
                <th className="w-20 px-4 py-2" aria-label="Open" />
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-100">
              {costs.map((r) => (
                <tr key={r.key} className="cursor-pointer hover:bg-teal-50/40" onClick={() => setOpen("months")}>
                  <td className="py-2 pl-4 pr-3 font-medium text-slate-800">{accountLabel(r.account)}</td>
                  <td className={cn(num, "font-semibold text-slate-900")}>{money(r.books)}</td>
                  <td className={cn(num, r.other === null ? "font-sans text-[11px] text-slate-400" : "text-slate-900")}>{r.other === null ? "not in yet" : money(r.other)}</td>
                  <td className="px-3 py-2 text-right"><Diff row={r} /></td>
                  <td className="px-4 py-2 text-right"><ViewLink /></td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}

/** One payable's working paper: its T, its ledger, and month by month against the payroll and the statement */
function PayablePaper({ engagementId, t, statement, view, onView, onBack, onRecsUpdated, onAttach }: {
  engagementId: string;
  t: PayrollTable;
  statement?: Reconciliation;
  view: View;
  onView: (v: View) => void;
  onBack: () => void;
  onRecsUpdated?: (next: Reconciliations) => void;
  onAttach: () => void;
}) {
  // Net wages: the ledger is read for the T too (its payments split employees from directors)
  const ledger = useLedger(engagementId, CODE[t.key], view === "ledger" || t.key === "net_wages");
  const summary = usePayrollSummary(engagementId).data;
  const owed = sum(t, "owed"), paid = sum(t, "paid"), allowance = sum(t, "allowance");
  const side = (n: number) => ({ dr: Math.max(-n, 0), cr: Math.max(n, 0) });        // owed (credit +) to a T line
  const months = `${t.months.length} month${t.months.length === 1 ? "" : "s"}`;
  const paidRef = `${t.months.filter((m) => m.paid).length} payment month${t.months.filter((m) => m.paid).length === 1 ? "" : "s"}`;
  const split = t.key === "net_wages" ? wagesSplit(owed, paid, summary, ledger.data?.current) : null;
  const lines: TLine[] = [
    { label: "Opening balance b/f", ref: "last year's closing", ...side(t.opening) },
    ...(split ? [
      { label: "Employee wages payable", ref: "payroll report: employees", ...side(split.employeeOwed) },
      { label: "Director wages payable", ref: "payroll report: directors", ...side(split.directorOwed) },
      ...(split.otherOwed ? [{ label: "Owed in the books, not on the payroll report", ref: "net pay per the months less the report", ...side(split.otherOwed) }] : []),
    ] : [{ label: "Owed per the payroll", ref: months, ...side(owed) }]),
    ...(t.with_allowance && allowance ? [{ label: "Employment allowance", ref: "set against employer NI", ...side(-allowance) }] : []),
    ...(split ? [
      { label: "Employee wages paid", ref: paidRef, ...side(-split.employeePaid) },
      { label: "Director wages paid", ref: "payments naming a director", ...side(-split.directorPaid) },
    ] : [{ label: "Paid", ref: paidRef, ...side(-paid) }]),
    ...(Math.abs(t.journals) >= 0.005 ? [{ label: "Journals approved", ref: "Journals step", ...side(t.journals) }] : []),
    ...(Math.abs(t.other) >= 0.005 ? [{ label: "Other lines", ref: "not in a payroll month", ...side(t.other) }] : []),
  ];
  const worked = t.opening + owed - allowance - paid + t.journals + t.other;
  const gap = worked - t.closing;
  if (Math.abs(gap) >= 1) lines.push({ label: "Difference to explain", ref: "payroll report against the books", ...side(-gap), tone: "red",
    explain: `On ${LABEL[t.key]}, the payroll and the payments leave ${money(worked)} owed but the books hold ${money(t.closing)}: why the ${money(Math.abs(gap))} difference, and what journal clears it?` });
  const tabs = [
    { id: "detailed" as const, label: "Detailed" },
    { id: "ledger" as const, label: "Ledger", count: ledger.data?.current.length },
    { id: "recon" as const, label: "Reconciliation", count: t.flags || undefined },
  ];
  return (
    <div className="space-y-3">
      <div className="flex items-center gap-2">
        <Crumb onBack={onBack} here={LABEL[t.key]} />
        <AskLedge className="ml-auto" question={`Explain the ${LABEL[t.key]} working paper: opening ${money(t.opening)}, owed per the payroll ${money(owed)}, paid ${money(paid)}${allowance ? `, employment allowance ${money(allowance)}` : ""}, owed at the year end ${money(t.closing)}, ${t.flags} month(s) flagged. What should I check, and what is missing?`} />
      </div>
      <FigRow>
        <Fig label="Owed at the year end" value={money(t.closing)} />
        <Fig label="Per statement" value={!statement || statement.other === null ? "Not in yet" : money(-statement.other)} />
        <Fig label="Difference" value={statement?.status === "MATCHED" ? "Agrees" : statement?.difference == null ? "-" : money(statement.difference)}
             tone={statement?.status === "MATCHED" ? "text-emerald-700" : statement?.difference ? "text-rose-700" : undefined} />
        <Fig label="Previous year" value={money(t.opening)} />
      </FigRow>
      <Tabs label={`${LABEL[t.key]} working paper`} items={tabs} value={view} onChange={onView} />
      {view === "detailed" && (
        <TAccount lines={lines} closing={-t.closing} closingRef="per the trial balance" note={Math.abs(gap) >= 1 ? (
          <span className="text-rose-700">
            The payroll and the payments leave {money(worked)} owed, but the books hold {money(t.closing)}: {money(Math.abs(gap))} to explain (see the points, then agree the balance to the statement).
          </span>
        ) : undefined} />
      )}
      {view === "ledger" && (ledger.data ? <Ledger lines={ledger.data.current} opening={-t.opening} account={LABEL[t.key]} /> : ledger.error
        ? <p className="text-[11px] text-rose-700">{ledger.error.message}</p> : <SkeletonRows rows={8} />)}
      {view === "recon" && (
        <div className="space-y-3">
          <div className="overflow-hidden rounded-xl border border-slate-200 bg-white shadow-2xs">
            <table className="w-full table-fixed text-xs">
              <thead className="border-b border-teal-100 bg-teal-50/80 text-[10.5px] uppercase tracking-wide text-teal-800">
                <tr>
                  <th className={cn(th, "w-28 pl-4 text-left")}>Month</th>
                  <th className={cn(th, "text-right")}>Owed</th>
                  {t.with_allowance && <th className={cn(th, "text-right")}>Allowance</th>}
                  <th className={cn(th, "text-right")}>Paid</th>
                  <th className={cn(th, "text-right")}>Outstanding</th>
                  <th className={cn(th, "w-[32%] text-left")}>Note</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-100">
                {t.months.map((m) => (
                  <tr key={m.month} className={cn(m.note && "bg-orange-50/40")}>
                    <td className="py-1.5 pl-4 text-slate-700">{monthLabel(m.month)}</td>
                    <td className={cn(num, "py-1.5")}>{money(m.owed)}</td>
                    {t.with_allowance && <td className={cn(num, "py-1.5")}>{m.allowance ? money(m.allowance) : ""}</td>}
                    <td className={cn(num, "py-1.5")}>{money(m.paid)}</td>
                    <td className={cn(num, "py-1.5", m.note && "font-semibold text-orange-700")}>{money(m.balance)}</td>
                    <td className="truncate px-3 py-1.5 text-[11px] text-orange-700" title={m.note || ""}>{m.note}</td>
                  </tr>
                ))}
              </tbody>
              <tfoot className="border-t-2 border-teal-200 bg-teal-50/70 font-bold text-teal-900">
                <tr>
                  <td className="py-2 pl-4">Year</td>
                  <td className={num}>{money(owed)}</td>
                  {t.with_allowance && <td className={num}>{money(allowance)}</td>}
                  <td className={num}>{money(paid)}</td>
                  <td className={num}>{money(t.closing)}</td>
                  <td />
                </tr>
              </tfoot>
            </table>
          </div>
          <div className="flex flex-wrap items-end justify-between gap-3 rounded-xl border border-slate-200 bg-white px-4 py-3 shadow-2xs">
            {statement && onRecsUpdated ? <StatementForm row={statement} engagementId={engagementId} onSaved={onRecsUpdated} />
              : <span className="text-[11px] text-slate-500">Agree the year-end balance to the {t.key === "pension" ? "pension provider's" : t.key === "paye" ? "HMRC PAYE" : "payroll"} statement.</span>}
            <Button variant="outline" size="sm" className="h-8 text-xs" onClick={onAttach}>
              <Paperclip className="mr-1.5 h-3.5 w-3.5" /> Attach the statement
            </Button>
          </div>
        </div>
      )}
    </div>
  );
}

function Crumb({ onBack, here }: { onBack: () => void; here: string }) {
  return (
    <div className="flex flex-wrap items-center gap-2 text-xs">
      <button type="button" onClick={onBack} className="inline-flex items-center gap-1 font-semibold text-teal-700 hover:text-teal-900">
        <ArrowLeft className="h-3.5 w-3.5" /> Wages summary
      </button>
      <ChevronRight className="h-3.5 w-3.5 text-slate-300" />
      <span className="font-semibold text-slate-800">{here}</span>
    </div>
  );
}

function Diff({ row }: { row?: Reconciliation }) {
  if (row?.status === "MATCHED") return <span className="inline-flex items-center gap-1 font-semibold text-emerald-700"><CheckCircle2 className="h-3.5 w-3.5" /> Agrees</span>;
  if (row?.status === "DIFFERENCE" && row.difference !== null) return (
    <span className="inline-flex items-center gap-1 font-mono font-semibold tabular-nums text-rose-700">
      {money(row.difference)}
      <AskLedge icon label="Explain with Ledge" question={`Why does ${row.account} differ: books ${money(row.books)}, ${row.compared_with} ${money(row.other)}, difference ${money(row.difference)}? What journal or document would clear it?`} />
    </span>
  );
  return <span className="text-slate-400">-</span>;
}

function ViewLink() {
  return <span className="inline-flex items-center font-semibold text-teal-700">View <ChevronRight className="h-3.5 w-3.5" /></span>;
}
