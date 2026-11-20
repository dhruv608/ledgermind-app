"use client";

import { useEffect, useMemo, useState } from "react";
import { Table2 } from "lucide-react";
import { api, Etb, EtbRow } from "@/lib/api";
import { cn } from "@/lib/utils";
import { Card } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { SectionHeader } from "@/components/ui/section-header";
import { SkeletonRows } from "@/components/common/SkeletonRows";
import { formatCurrency } from "@/lib/formatters";
import { usePagination } from "@/hooks/usePagination";
import { PageControls } from "@/components/common/Pagination";

type Area = "ALL" | "PL" | "BS";
type View = "etb" | "ttb" | "compare";

// The ETB: each figure in a debit or a credit column. The opening is last year's balance
// (balance sheet accounts only: the profit and loss starts at nil); the closing goes to the P&L or balance sheet column
const opening = (r: EtbRow) => (r.pl ? 0 : r.last_year ?? 0);
const COLS: { key: string; label: string; of: (r: EtbRow) => number | null }[] = [
  { key: "opening", label: "Opening balance", of: opening },
  { key: "tb", label: "Trial balance", of: (r) => r.tb },
  { key: "journals", label: "Journals", of: (r) => r.journals },
  { key: "pl", label: "Profit and loss", of: (r) => (r.pl ? r.final : null) },
  { key: "bs", label: "Balance sheet", of: (r) => (r.pl ? null : r.final) },
];
// The TTB: this year's trial balance, last year's, and the year's movement between them
// (the profit and loss starts at nil, so its movement is this year's figure)
const TTB_COLS: typeof COLS = [
  { key: "cy", label: "Trial balance this year", of: (r) => r.tb },
  { key: "py", label: "Trial balance last year", of: (r) => r.last_year },
  { key: "mv", label: "TTB movement", of: (r) => (r.pl ? r.tb : r.tb - (r.last_year ?? 0)) },
];
const dr = (v: number | null) => (v !== null && v > 0.004 ? v : 0);
const cr = (v: number | null) => (v !== null && v < -0.004 ? -v : 0);

// A change worth a look: over 50% and £1,000, or an account that is new or gone (as on the client accounts view)
const bigChange = (now: number, before: number) =>
  Math.abs(now - before) >= 1000 && (Math.abs(before) < 0.005 || Math.abs(now) < 0.005 || Math.abs(now - before) / Math.abs(before) > 0.5);

/** The extended trial balance by firm code: the TB, the journals approved in the app and the final balance (as on the
 *  workbook's B1-ETB sheet), with last year's final balance and the change. */
export function EtbTable({ engagementId, refreshKey }: { engagementId: string; refreshKey?: string }) {
  const [etb, setEtb] = useState<Etb | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [search, setSearch] = useState("");
  const [area, setArea] = useState<Area>("ALL");
  const [journalsOnly, setJournalsOnly] = useState(false);
  const [view, setView] = useState<View>("etb");

  // Another job or a refresh: clear the old error at once (during render), then load
  const [loadedFor, setLoadedFor] = useState(`${engagementId}|${refreshKey}`);
  if (`${engagementId}|${refreshKey}` !== loadedFor) {
    setLoadedFor(`${engagementId}|${refreshKey}`);
    setError(null);
  }
  useEffect(() => {
    api.getEtb(engagementId).then(setEtb).catch((e) => setError(e.message));
  }, [engagementId, refreshKey]);

  const rows = useMemo(() => {
    const q = search.trim().toLowerCase();
    return (etb?.rows || []).filter(
      (r) =>
        (area === "ALL" || (area === "PL") === r.pl) &&
        (!journalsOnly || Math.abs(r.journals) >= 0.005) &&
        (!q || String(r.code).includes(q) || r.name.toLowerCase().includes(q) || r.accounts.some((a) => a.toLowerCase().includes(q))),
    );
  }, [etb, search, area, journalsOnly]);
  const page = usePagination({ items: rows, initialPageSize: 50, resetDependencies: [search, area, journalsOnly, etb] });
  const withJournals = (etb?.rows || []).filter((r) => Math.abs(r.journals) >= 0.005).length;
  const hasLastYear = Boolean(etb?.last_year_source);
  const sum = (k: "tb" | "journals" | "final") => rows.reduce((t, r) => t + r[k], 0);
  const th = "px-3 py-2.5 font-semibold";

  return (
    <Card className="overflow-hidden">
      <div className="space-y-3 p-5">
        <SectionHeader
          icon={Table2}
          title="Extended trial balance"
          description="Per account code: the trial balance, the journals approved in the app and the final balance, as on the workbook's ETB sheet."
        />
        <div className="flex flex-wrap items-center gap-2">
          <Input
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            placeholder="Search a code or account"
            className="h-8 w-56 text-xs"
          />
          <div className="flex rounded-lg border border-slate-200 bg-white p-0.5 text-xs">
            {(["ALL", "PL", "BS"] as Area[]).map((a) => (
              <button
                key={a}
                type="button"
                onClick={() => setArea(a)}
                className={cn("rounded-md px-2.5 py-1 font-medium", area === a ? "bg-teal-50 text-teal-800" : "text-slate-500 hover:text-slate-800")}
              >
                {a === "ALL" ? "All" : a === "PL" ? "P&L" : "Balance sheet"}
              </button>
            ))}
          </div>
          <label className="flex cursor-pointer items-center gap-1.5 text-xs text-slate-600">
            <input type="checkbox" checked={journalsOnly} onChange={() => setJournalsOnly(!journalsOnly)} className="h-3.5 w-3.5 accent-teal-700" />
            Only codes with journals ({withJournals})
          </label>
          <div className="flex rounded-lg border border-slate-200 bg-white p-0.5 text-xs">
            {([["etb", "Debit / credit"], ["ttb", "TTB"], ["compare", "Against last year"]] as [View, string][]).map(([v, label]) => (
              <button key={v} type="button" onClick={() => setView(v)}
                      className={cn("rounded-md px-2.5 py-1 font-medium", view === v ? "bg-teal-50 text-teal-800" : "text-slate-500 hover:text-slate-800")}>
                {label}
              </button>
            ))}
          </div>
          <span className="ml-auto text-[11px] text-slate-500">
            {hasLastYear ? `Last year: from ${etb?.last_year_source}` : "No last year's figures to compare with"}
          </span>
        </div>
        {etb && Math.abs(etb.unmapped) >= 0.005 && (
          <p className="rounded-md border border-amber-200 bg-amber-50 px-3 py-2 text-xs text-amber-900">
            {formatCurrency(etb.unmapped)} of the trial balance has no code yet and is not on the ETB: map it on the client accounts view.
          </p>
        )}
      </div>

      {error ? (
        <p className="border-t border-slate-100 px-5 py-6 text-sm text-rose-700">{error}</p>
      ) : !etb ? (
        <div className="border-t border-slate-100 p-5">
          <SkeletonRows rows={6} />
        </div>
      ) : (
        <div className="overflow-x-auto border-t border-slate-100">
          {view !== "compare" ? <DrCrTable cols={view === "ttb" ? TTB_COLS : COLS} rows={rows} shown={page.paginatedItems} partial={rows.length !== etb.rows.length} /> : (
          <table className="w-full text-xs">
            <thead className="border-b border-slate-200 bg-slate-50 text-[11px] uppercase tracking-wide text-slate-500">
              <tr className="text-left">
                <th className={cn(th, "pl-5")}>Code</th>
                <th className={th}>Account</th>
                <th className={cn(th, "text-right")}>Trial balance</th>
                <th className={cn(th, "text-right")}>Journals</th>
                <th className={cn(th, "text-right")}>Final</th>
                <th className={cn(th, "text-right")}>Last year</th>
                <th className={cn(th, "pr-5 text-right")}>Change</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-100">
              {page.paginatedItems.map((r) => (
                <Row key={r.code} r={r} />
              ))}
              {rows.length === 0 && (
                <tr>
                  <td colSpan={7} className="px-5 py-6 text-center text-slate-400">No codes match.</td>
                </tr>
              )}
            </tbody>
            <tfoot className="sticky bottom-0 border-t-2 border-slate-200 bg-slate-50 font-semibold text-slate-900">
              <tr>
                <td className="py-2.5 pl-5" colSpan={2}>Total{rows.length !== etb.rows.length ? " (shown)" : ""}</td>
                <td className="px-3 py-2.5 text-right font-mono">{formatCurrency(sum("tb"))}</td>
                <td className="px-3 py-2.5 text-right font-mono">{formatCurrency(sum("journals"))}</td>
                <td className="px-3 py-2.5 text-right font-mono">{formatCurrency(sum("final"))}</td>
                <td colSpan={2} />
              </tr>
            </tfoot>
          </table>
          )}
          <PageControls page={page} itemLabel="codes" sizes={[50, 100, 200]} />
        </div>
      )}
    </Card>
  );
}

function Row({ r }: { r: EtbRow }) {
  const moved = Math.abs(r.journals) >= 0.005;
  const known = r.last_year !== null;
  const change = known ? r.final - (r.last_year as number) : 0;
  const big = known && bigChange(r.final, r.last_year as number);
  const pct = known && Math.abs(r.last_year as number) >= 0.005 ? Math.round((Math.abs(change) / Math.abs(r.last_year as number)) * 100) : null;
  return (
    <tr className={cn("hover:bg-slate-50/60", moved && "bg-teal-50/30")}>
      <td className="py-2 pl-5 font-mono text-[11px] font-semibold text-teal-800">{String(r.code).padStart(4, "0")}</td>
      <td className="max-w-xs px-3 py-2">
        <p className="truncate font-medium text-slate-900">{r.name}</p>
        {r.accounts.length > 0 && (
          <p className="truncate text-[11px] text-slate-400" title={r.accounts.join(" · ")}>{r.accounts.join(" · ")}</p>
        )}
      </td>
      <td className="whitespace-nowrap px-3 py-2 text-right font-mono text-slate-500">{formatCurrency(r.tb)}</td>
      <td className={cn("whitespace-nowrap px-3 py-2 text-right font-mono", moved ? "font-semibold text-teal-800" : "text-slate-300")}>
        {moved ? formatCurrency(r.journals) : "—"}
      </td>
      <td className="whitespace-nowrap px-3 py-2 text-right font-mono font-semibold text-slate-900">{formatCurrency(r.final)}</td>
      <td className="whitespace-nowrap px-3 py-2 text-right font-mono text-slate-500">{known ? formatCurrency(r.last_year as number) : "–"}</td>
      <td className={cn("whitespace-nowrap py-2 pl-3 pr-5 text-right font-mono", big ? "font-semibold text-orange-700" : "text-slate-500")}>
        {!known ? "–" : Math.abs(change) < 0.005 ? "—" : formatCurrency(change)}
        {known && Math.abs(change) >= 0.005 && (
          <span className="block text-[10px] font-normal">{pct === null ? "new" : Math.abs(r.final) < 0.005 ? "gone" : `${pct}%`}</span>
        )}
      </td>
    </tr>
  );
}

/** The ETB in debit and credit columns: opening, trial balance, journals, profit and loss, balance sheet */
function DrCrTable({ cols: COLS, rows, shown, partial }: { cols: typeof TTB_COLS; rows: EtbRow[]; shown: EtbRow[]; partial: boolean }) {
  const th = "px-2 py-2 font-semibold";
  const money = (v: number) => (v ? formatCurrency(v) : "");
  const total = (f: (r: EtbRow) => number) => rows.reduce((t, r) => t + f(r), 0);
  return (
    <table className={cn("w-full text-xs", COLS.length > 3 && "min-w-[72rem]")}>
      <thead className="border-b border-slate-200 bg-slate-50 text-[11px] uppercase tracking-wide text-slate-500">
        <tr>
          <th rowSpan={2} className={cn(th, "pl-5 text-left align-bottom")}>Code</th>
          <th rowSpan={2} className={cn(th, "text-left align-bottom")}>Account</th>
          {COLS.map((c) => <th key={c.key} colSpan={2} className={cn(th, "border-l border-slate-200 text-center")}>{c.label}</th>)}
        </tr>
        <tr className="text-[10px]">
          {COLS.map((c) => [
            <th key={`${c.key}-dr`} className={cn(th, "border-l border-slate-200 text-right")}>Debit</th>,
            <th key={`${c.key}-cr`} className={cn(th, "text-right")}>Credit</th>,
          ])}
        </tr>
      </thead>
      <tbody className="divide-y divide-slate-100">
        {shown.map((r) => (
          <tr key={r.code} className={cn("hover:bg-slate-50/60", Math.abs(r.journals) >= 0.005 && "bg-teal-50/30")}>
            <td className="py-1.5 pl-5 font-mono text-[11px] font-semibold text-teal-800">{String(r.code).padStart(4, "0")}</td>
            <td className="max-w-56 truncate px-2 py-1.5 font-medium text-slate-900" title={[r.name, ...r.accounts].join(" · ")}>{r.name}</td>
            {COLS.map((c) => {
              const v = c.of(r);
              return [
                <td key={`${c.key}-dr`} className="whitespace-nowrap border-l border-slate-100 px-2 py-1.5 text-right font-mono text-slate-700">{money(dr(v))}</td>,
                <td key={`${c.key}-cr`} className="whitespace-nowrap px-2 py-1.5 text-right font-mono text-slate-700">{money(cr(v))}</td>,
              ];
            })}
          </tr>
        ))}
        {rows.length === 0 && <tr><td colSpan={2 + COLS.length * 2} className="px-5 py-6 text-center text-slate-400">No codes match.</td></tr>}
      </tbody>
      <tfoot className="sticky bottom-0 border-t-2 border-slate-200 bg-slate-50 font-semibold text-slate-900">
        <tr>
          <td className="py-2.5 pl-5" colSpan={2}>Total{partial ? " (shown)" : ""}</td>
          {COLS.map((c) => [
            <td key={`${c.key}-dr`} className="whitespace-nowrap border-l border-slate-200 px-2 py-2.5 text-right font-mono">{formatCurrency(total((r) => dr(c.of(r))))}</td>,
            <td key={`${c.key}-cr`} className="whitespace-nowrap px-2 py-2.5 text-right font-mono">{formatCurrency(total((r) => cr(c.of(r))))}</td>,
          ])}
        </tr>
      </tfoot>
    </table>
  );
}
