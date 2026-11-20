"use client";

import { Fragment, useCallback, useEffect, useState } from "react";
import { AlertTriangle, ArrowRight, CheckCircle2, ChevronDown, CircleDashed, RefreshCw } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { CustomSelect } from "@/components/ui/custom-select";
import { StatusChip } from "@/components/ui/status-chip";
import { SkeletonRows } from "@/components/common/SkeletonRows";
import { api, Reconciliations } from "@/lib/api";
import { accountLabel } from "@/lib/formatters";
import { text } from "@/lib/ui";
import { cn } from "@/lib/utils";
import { money, STATUS, type StatusFilter } from "@/components/control-accounts/reconciliations/shared";
import { RowDetail } from "@/components/control-accounts/reconciliations/RowDetail";

export { byHand } from "@/components/control-accounts/reconciliations/shared";
export { AgreeForm, StatementForm } from "@/components/control-accounts/reconciliations/EntryForms";
export { RollforwardBox } from "@/components/control-accounts/reconciliations/RollforwardBox";
export { DebtorAgeingBox } from "@/components/control-accounts/reconciliations/DebtorAgeingBox";
export { VatProofBox } from "@/components/control-accounts/reconciliations/VatProofBox";

/** The balance sheet: every account in the books, section by section as the balance sheet reads, against what it is
 * agreed to (bank statement, VAT returns, aged lists, asset register, last year's reserves, or a document the
 * accountant ticks), with last year beside it, so problems are found before the workbook. */
export function ReconciliationsPanel({
  engagementId,
  onOpenLedger,
  onGoTo,
  onSaved,
  onLoaded,
  onOpenScrutiny,
  areaFor,
  onOpenArea,
}: {
  engagementId: string;
  /** The figures each time they are worked out (the tab's count) */
  onLoaded?: (data: Reconciliations) => void;
  /** Opens the ledger lines of the account with this firm code */
  onOpenLedger: (code: number) => void;
  /** Opens GL scrutiny (Accounts tab) on this firm code */
  onOpenScrutiny?: (code: number) => void;
  onGoTo: (tab: "inputs" | "review") => void;
  onSaved?: () => void;
  /** The area page (key) an account's codes belong to, if any; and opening it: the account's reconciliation, points,
   *  transactions, queries and notes */
  areaFor?: (codes: number[]) => string | null;
  onOpenArea?: (key: string, evidence?: boolean) => void;
}) {
  const [data, setData] = useState<Reconciliations | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [status, setStatus] = useState<StatusFilter>("ALL");
  const [section, setSection] = useState("");
  const [open, setOpen] = useState<string | null>(null);

  // A new job shows the loading state at once (set during render, not in the effect below)
  const [loadedFor, setLoadedFor] = useState(engagementId);
  if (engagementId !== loadedFor) {
    setLoadedFor(engagementId);
    setLoading(true);
    setError(null);
  }

  const fetchFigures = useCallback(
    () =>
      api
        .getReconciliations(engagementId)
        .then((next) => {
          setData(next);
          onLoaded?.(next);
        })
        .catch((e) => setError(e instanceof Error ? e.message : "Could not work out the balance sheet"))
        .finally(() => setLoading(false)),
    [engagementId, onLoaded],
  );

  const load = useCallback(() => {
    setLoading(true);
    setError(null);
    return fetchFigures();
  }, [fetchFigures]);

  useEffect(() => {
    fetchFigures();
  }, [fetchFigures]);

  const rows = (data?.rows ?? []).filter((r) => (status === "ALL" || r.status === status) && (!section || r.section === section));
  const sections = (data?.sections ?? []).filter((s) => rows.some((r) => r.section === s));
  const pct = data && data.value_total > 0 ? Math.round((data.value_agreed / data.value_total) * 100) : 0;
  const cards: { id: StatusFilter; label: string; value: number; tone: string }[] = data
    ? [
        { id: "DIFFERENCE", label: "Difference", value: data.differences, tone: "text-rose-700" },
        { id: "NEEDS_INPUT", label: "To agree", value: data.needs_input, tone: "text-slate-700" },
        { id: "MATCHED", label: "Agreed", value: data.matched, tone: "text-emerald-700" },
      ]
    : [];
  const saved = (next: Reconciliations) => {
    setData(next);
    onLoaded?.(next);
    onSaved?.();
  };

  return (
    <div className="space-y-4">
      <Card className="px-4 py-3">
        <div className="flex items-start justify-between gap-3">
          <div className="flex min-w-0 flex-1 items-start gap-3">
            {/* The top bar names the screen: only the help line here */}
            <div>
              <p className={text.meta}>
                The summary: every balance sheet account against what it agrees to, with last year beside it. Open an
                account&apos;s page for its reconciliation, points and transactions; type a statement figure here.
              </p>
            </div>
          </div>
          <Button variant="outline" size="sm" className="h-8 w-8 p-0" onClick={load} disabled={loading}
                  title="Work the balances out again (after a change elsewhere)" aria-label="Work the balances out again">
            <RefreshCw className={cn("h-3.5 w-3.5", loading && "animate-spin")} />
          </Button>
        </div>

        {data && (
          <div className="mt-4 grid grid-cols-1 gap-3 sm:grid-cols-4">
            <button
              type="button"
              onClick={() => setStatus("ALL")}
              className={cn(
                "rounded-lg border px-3 py-2.5 text-left transition hover:border-slate-300",
                status === "ALL" ? "border-teal-600 bg-teal-50/40" : "border-slate-200 bg-slate-50/60",
              )}
            >
              <span className="block text-[11px] text-slate-500">Agreed by value</span>
              <span className="block text-xl font-semibold text-slate-900">{pct}%</span>
              <span className="mt-1 block h-1.5 overflow-hidden rounded-full bg-slate-200">
                <span className="block h-full rounded-full bg-emerald-500" style={{ width: `${pct}%` }} />
              </span>
              <span className="mt-1 block font-mono text-[11px] text-slate-500">
                {money(data.value_agreed)} of {money(data.value_total)}
              </span>
            </button>
            {cards.map((c) => (
              <button
                key={c.id}
                type="button"
                onClick={() => setStatus(c.id)}
                className={cn(
                  "rounded-lg border px-3 py-2.5 text-left transition hover:border-slate-300",
                  status === c.id ? "border-teal-600 bg-teal-50/40" : "border-slate-200 bg-slate-50/60",
                )}
              >
                <span className="block text-[11px] text-slate-500">{c.label}</span>
                <span className={cn("block text-xl font-semibold", c.tone)}>{c.value}</span>
              </button>
            ))}
          </div>
        )}
      </Card>

      <Card>
        <div className="flex flex-wrap items-center gap-2 border-b border-slate-100 px-5 py-3">
          {(["ALL", "DIFFERENCE", "NEEDS_INPUT", "MATCHED"] as StatusFilter[]).map((s) => (
            <Button key={s} size="sm" variant={status === s ? "secondary" : "ghost"} onClick={() => setStatus(s)} className="h-7 text-xs">
              {s === "ALL" ? "All" : STATUS[s].label}
            </Button>
          ))}
          <div className="ml-auto w-48">
            <CustomSelect
              size="sm"
              fullWidth
              value={section}
              options={[{ value: "", label: "All sections" }, ...(data?.sections ?? []).map((a) => ({ value: a, label: a }))]}
              onChange={setSection}
            />
          </div>
        </div>

        {loading && !data ? (
          <SkeletonRows rows={6} columns={5} label="Working out the balance sheet" />
        ) : error ? (
          <div className="flex flex-wrap items-center justify-between gap-3 px-5 py-6 text-xs text-rose-700">
            <span>{error}</span>
            <Button variant="outline" size="sm" onClick={load}>Try again</Button>
          </div>
        ) : rows.length === 0 ? (
          <p className="px-5 py-8 text-center text-xs text-slate-500">
            {data?.rows.length ? "No accounts match these filters." : "No balance sheet accounts with a balance yet. Upload the accounts first."}
          </p>
        ) : (
          <table className="w-full text-xs sm:table-fixed">
            <thead className="border-b border-teal-100 bg-teal-50/80 text-[11px] uppercase tracking-wide text-teal-800">
              <tr>
                <th className="px-3 py-2 text-left font-semibold sm:px-5">Account</th>
                <th className="hidden w-32 px-3 py-2 text-right font-semibold sm:table-cell">This year</th>
                <th className="hidden w-28 px-3 py-2 text-right font-semibold lg:table-cell">Last year</th>
                <th className="hidden w-52 px-3 py-2 text-left font-semibold md:table-cell">Agreed to</th>
                <th className="w-24 px-2 py-2 text-right font-semibold sm:w-32 sm:px-3">Difference</th>
                <th className="w-28 px-2 py-2 text-left font-semibold sm:w-32 sm:px-3">Status</th>
                <th className="w-7 px-1 py-2 sm:w-10 sm:px-3" />
              </tr>
            </thead>
            <tbody>
              {sections.map((s) => (
                <Fragment key={s}>
                  <tr className="border-t border-slate-200 bg-slate-50/60">
                    <td colSpan={7} className="px-3 pb-1.5 pt-3 text-[11px] font-semibold uppercase tracking-wide text-slate-600 sm:px-5">
                      {s}
                    </td>
                  </tr>
                  {rows.filter((r) => r.section === s).map((r) => (
                    <Fragment key={r.key}>
                      <tr
                        onClick={() => setOpen(open === r.key ? null : r.key)}
                        className={cn("cursor-pointer border-t border-slate-100 transition-colors hover:bg-teal-50/40", open === r.key && "bg-teal-50/60")}
                      >
                        <td className="px-3 py-2.5 sm:px-5">
                          <span className="block font-medium text-slate-800 sm:truncate" title={r.account}>{accountLabel(r.account)}</span>
                        </td>
                        <td className="hidden whitespace-nowrap px-3 py-2.5 text-right font-mono sm:table-cell">{money(r.books)}</td>
                        <td className="hidden whitespace-nowrap px-3 py-2.5 text-right font-mono text-slate-500 lg:table-cell">{money(r.last_year)}</td>
                        <td className="hidden truncate px-3 py-2.5 text-slate-600 md:table-cell" title={r.compared_with}>
                          {r.other === null || r.ticked ? (
                            <span className="text-slate-400">{r.compared_with}</span>
                          ) : (
                            <>
                              <span className="font-mono text-slate-800">{money(r.other)}</span>
                              <span className="block truncate text-[11px] text-slate-400">{r.compared_with}</span>
                            </>
                          )}
                        </td>
                        <td className={cn("whitespace-nowrap px-2 py-2.5 text-right font-mono sm:px-3", r.status === "DIFFERENCE" && "font-semibold text-rose-700")}>
                          {money(r.difference)}
                        </td>
                        <td className="px-2 py-2.5 sm:px-3">
                          <StatusChip
                            tone={STATUS[r.status].tone}
                            icon={r.status === "MATCHED" ? CheckCircle2 : r.status === "DIFFERENCE" ? AlertTriangle : CircleDashed}
                            title={r.ticked ? "Ticked by the accountant" : undefined}
                          >
                            {r.ticked ? "Agreed (ticked)" : STATUS[r.status].label}
                          </StatusChip>
                        </td>
                        <td className="px-1 py-2.5 text-slate-400 sm:px-3">
                          <span className="flex items-center justify-end gap-1">
                            {onOpenArea && areaFor?.(r.codes) && (
                              <button type="button" title="Open this account's page" aria-label={`Open the ${r.account} page`}
                                      onClick={(e) => { e.stopPropagation(); onOpenArea(areaFor(r.codes)!); }}
                                      className="rounded p-0.5 text-teal-700 hover:bg-teal-50">
                                <ArrowRight className="h-4 w-4" />
                              </button>
                            )}
                            <ChevronDown className={cn("h-4 w-4 transition", open === r.key && "rotate-180")} />
                          </span>
                        </td>
                      </tr>
                      {open === r.key && (
                        <tr className="bg-slate-50/70">
                          <td colSpan={7} className="px-3 pb-4 pt-1 sm:px-5">
                            <RowDetail
                              row={r}
                              engagementId={engagementId}
                              onOpenLedger={onOpenLedger}
                              onOpenScrutiny={onOpenScrutiny}
                              onGoTo={onGoTo}
                              onOpenArea={onOpenArea}
                              onSaved={saved}
                            />
                          </td>
                        </tr>
                      )}
                    </Fragment>
                  ))}
                </Fragment>
              ))}
            </tbody>
          </table>
        )}
      </Card>
    </div>
  );
}
