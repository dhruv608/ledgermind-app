"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { FileSearch, Flag } from "lucide-react";
import { api, ScrutinyAccount } from "@/lib/api";
import { cn } from "@/lib/utils";
import { Card } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { SectionHeader } from "@/components/ui/section-header";
import { Tabs } from "@/components/ui/tabs";
import { useQueryClient } from "@tanstack/react-query";
import { jobKeys } from "@/lib/queries/job";
import { ScrutinyErrorReport } from "@/components/mapping/scrutiny/ScrutinyErrorReport";
import { ScrutinySummary } from "@/components/mapping/scrutiny/ScrutinySummary";
import { SkeletonRows } from "@/components/common/SkeletonRows";
import { formatCurrency } from "@/lib/formatters";
import { Area, ChartCode, codeLabel } from "@/components/mapping/scrutiny/shared";
import { AccountLines } from "@/components/mapping/scrutiny/AccountLines";

/** GL scrutiny: the ledger one code at a time. Each line is marked OK, or moved to another code by a proposed journal
 *  (approved on the Journals tab like any other); a line can also be asked about (a client query on the Queries tab). */
export function ScrutinyPanel({
  engagementId,
  initialKey,
  onChanged,
  onQueriesChanged,
}: {
  engagementId: string;
  /** The account to open first (a code), when another tab sends you here */
  initialKey?: string | null;
  onChanged?: () => void;
  onQueriesChanged?: () => void;
}) {
  const [accounts, setAccounts] = useState<ScrutinyAccount[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [search, setSearch] = useState("");
  const [area, setArea] = useState<Area>("ALL");
  const [selected, setSelected] = useState<string | null>(null);
  const [chart, setChart] = useState<ChartCode[]>([]);
  // The three GL scrutiny screens: Summary, Analysis (one account's lines), Error report (its adjustments)
  const [view, setView] = useState<"summary" | "analysis" | "errors">("analysis");
  const qc = useQueryClient();

  const loadAccounts = useCallback(() => {
    api
      .getScrutinyAccounts(engagementId)
      .then((a) => {
        setAccounts(a.accounts);
        setSelected((s) => s ?? (a.accounts.some((x) => x.key === initialKey) ? initialKey : null) ?? a.accounts[0]?.key ?? null);
      })
      .catch((e) => setError(e.message));
  }, [engagementId, initialKey]);

  // Another job (or start account): clear the old list at once (during render); the effect below loads the new one
  const [loadedFor, setLoadedFor] = useState(`${engagementId}|${initialKey}`);
  if (`${engagementId}|${initialKey}` !== loadedFor) {
    setLoadedFor(`${engagementId}|${initialKey}`);
    setError(null);
    setAccounts(null);
    setSelected(null);
  }

  useEffect(() => {
    loadAccounts();
  }, [loadAccounts]);

  useEffect(() => {
    api.getMasterCOA().then((c) => setChart(c as ChartCode[]));
  }, []);

  const shown = useMemo(() => {
    const q = search.trim().toLowerCase();
    return (accounts || []).filter(
      (a) =>
        (area === "ALL" || (a.code !== null && (area === "PL") === a.pl)) &&
        (!q || codeLabel(a.code).includes(q) || a.name.toLowerCase().includes(q) || a.accounts.some((n) => n.toLowerCase().includes(q))),
    );
  }, [accounts, search, area]);
  const total = (accounts || []).reduce((t, a) => t + a.lines, 0);
  const checked = (accounts || []).reduce((t, a) => t + a.checked, 0);
  const flagged = (accounts || []).reduce((t, a) => t + a.flagged, 0);

  return (
    <Card className="@container/scrutiny overflow-clip">
      <div className="space-y-1 p-5">
        <SectionHeader
          icon={FileSearch}
          title="GL scrutiny"
          description="Read the ledger one account code at a time. Mark each line OK, move it to the right code (a journal is proposed on the Journals tab), or ask the client about it (a query on the Queries tab)."
        />
        {accounts && (
          <p className="text-xs text-slate-500">
            {checked} of {total} lines checked
            {flagged > 0 && (
              <span className="text-amber-700">
                {" "}· <Flag className="inline h-3 w-3" /> {flagged} flagged line{flagged === 1 ? "" : "s"} to read first
              </span>
            )}
          </p>
        )}
        <Tabs className="pt-2" label="GL scrutiny screens" value={view} onChange={setView}
              items={[{ id: "summary", label: "Summary" }, { id: "analysis", label: "Analysis" }, { id: "errors", label: "Error report" }]} />
      </div>

      {view === "summary" ? (
        <div className="border-t border-slate-100">
          <ScrutinySummary engagementId={engagementId} onOpen={(code) => {
            const a = (accounts || []).find((x) => x.code === code);
            if (a) setSelected(a.key);
            setView("analysis");
          }} />
        </div>
      ) : error ? (
        <p className="border-t border-slate-100 px-5 py-6 text-sm text-rose-700">{error}</p>
      ) : !accounts ? (
        <div className="border-t border-slate-100 p-5">
          <SkeletonRows rows={6} />
        </div>
      ) : accounts.length === 0 ? (
        <p className="border-t border-slate-100 px-5 py-6 text-sm text-slate-500">This job has no ledger lines to read.</p>
      ) : (
        <div className="grid border-t border-slate-100 @min-[56rem]/scrutiny:grid-cols-[16rem_minmax(0,1fr)]">
          {/* The codes: above the lines on a narrow page; beside them, staying in view while the lines scroll, on a wide one */}
          <div className="border-b border-slate-100 @min-[56rem]/scrutiny:sticky @min-[56rem]/scrutiny:top-16 @min-[56rem]/scrutiny:self-start @min-[56rem]/scrutiny:border-b-0 @min-[56rem]/scrutiny:border-r">
            <div className="space-y-2 p-3">
              <Input value={search} onChange={(e) => setSearch(e.target.value)} placeholder="Search a code or account" className="h-8 text-xs" />
              <div className="flex w-fit rounded-lg border border-slate-200 bg-white p-0.5 text-xs">
                {(["ALL", "PL", "BS"] as Area[]).map((a) => (
                  <button
                    key={a}
                    type="button"
                    onClick={() => setArea(a)}
                    className={cn("rounded-md px-2.5 py-1 font-medium transition-colors", area === a ? "bg-teal-50 text-teal-800" : "text-slate-500 hover:bg-teal-50/60 hover:text-teal-800")}
                  >
                    {a === "ALL" ? "All" : a === "PL" ? "P&L" : "Balance sheet"}
                  </button>
                ))}
              </div>
            </div>
            <ul className="max-h-56 overflow-y-auto border-t border-slate-100 text-xs @min-[56rem]/scrutiny:max-h-[calc(100vh-13rem)]">
              {shown.map((a) => {
                const left = a.lines - a.checked;
                return (
                  <li key={a.key}>
                    <button
                      type="button"
                      onClick={() => setSelected(a.key)}
                      className={cn(
                        "flex w-full items-start gap-2 px-3 py-2 text-left transition-colors hover:bg-teal-50/50",
                        selected === a.key && "bg-teal-50/60 hover:bg-teal-50/60",
                      )}
                    >
                      <span className="w-10 shrink-0 font-mono text-[11px] font-semibold text-teal-800">{codeLabel(a.code)}</span>
                      <span className="min-w-0 flex-1">
                        <span className="block truncate font-medium text-slate-900">{a.name}</span>
                        <span className="block text-[11px] text-slate-400">
                          {a.lines} line{a.lines === 1 ? "" : "s"} · {formatCurrency(a.total)}
                          {a.asked > 0 && <span className="text-violet-700"> · {a.asked} asked</span>}
                          {a.flagged > 0 && (
                            <span className="text-amber-700">
                              {" "}· <Flag className="inline h-2.5 w-2.5" /> {a.flagged}
                            </span>
                          )}
                        </span>
                      </span>
                      <span
                        className={cn(
                          "shrink-0 rounded-full px-2 py-0.5 text-[10px] font-semibold",
                          left === 0 ? "bg-emerald-50 text-emerald-700" : a.checked ? "bg-amber-50 text-amber-700" : "bg-slate-100 text-slate-500",
                        )}
                      >
                        {left === 0 ? "Done" : a.checked ? `${left} left` : "New"}
                      </span>
                    </button>
                  </li>
                );
              })}
              {shown.length === 0 && <li className="px-3 py-6 text-center text-slate-400">No codes match.</li>}
            </ul>
          </div>
          <div className="min-w-0">
            {selected && view === "errors" ? (
              <ScrutinyErrorReport engagementId={engagementId} code={(accounts || []).find((a) => a.key === selected)?.code ?? null}
                                   name={(accounts || []).find((a) => a.key === selected)?.name ?? ""} />
            ) : selected ? (
              <AccountLines
                key={selected}
                engagementId={engagementId}
                codeKey={selected}
                chart={chart}
                onChanged={(journalChanged) => {
                  loadAccounts();
                  if (journalChanged) qc.invalidateQueries({ queryKey: jobKeys.journals(engagementId) });
                  if (journalChanged) onChanged?.();
                }}
                onQueriesChanged={() => onQueriesChanged?.()}
              />
            ) : (
              <p className="px-5 py-6 text-sm text-slate-500">Pick an account on the left.</p>
            )}
          </div>
        </div>
      )}
    </Card>
  );
}
