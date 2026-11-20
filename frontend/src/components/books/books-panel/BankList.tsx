// The bank lines: one tab per statement, what each line is, and coding a line or every line from the same payee.

import { useMemo, useState } from "react";
import { Check, Loader2, RotateCcw } from "lucide-react";
import { Button } from "@/components/ui/button";
import { usePagination, UsePaginationResult } from "@/hooks/usePagination";
import { BooksBankRow } from "@/lib/api";
import { formatDate } from "@/lib/formatters";
import { cn } from "@/lib/utils";
import { Chart, Empty, Pager, amount, matches } from "./common";
import { HeadPicker } from "./HeadPicker";

export function BankList({ rows, choices, chart, onlyToCheck, search, saving, onChoose }: {
  rows: BooksBankRow[];
  choices: string[];
  chart: Chart;
  onlyToCheck: boolean;
  search: string;
  saving: string | null;
  onChoose: (key: string, value: Record<string, unknown> | null) => void;
}) {
  const [changing, setChanging] = useState<string | null>(null);
  // A head chosen on a line goes on every line from the same payee unless "This line only" is picked there
  // (one line and all similar ones are coded together)
  const [oneOnly, setOneOnly] = useState<Set<string>>(new Set());
  // One tab per statement (bank account or card) when the client has several, so a current account's and a
  // card's lines never mix in one list; "" = all of them
  const accounts = useMemo(() => {
    const by = new Map<string, { lines: number; check: number }>();
    for (const r of rows) {
      const a = by.get(r.account) || { lines: 0, check: 0 };
      a.lines += 1;
      if (r.check) a.check += 1;
      by.set(r.account, a);
    }
    return Array.from(by, ([name, n]) => ({ name, ...n }));
  }, [rows]);
  const several = accounts.length > 1;
  const [account, setAccount] = useState("");
  const perPayee = useMemo(() => {
    const n = new Map<string, number>();
    for (const r of rows) if (r.payee) n.set(r.payee, (n.get(r.payee) || 0) + 1);
    return n;
  }, [rows]);
  const shown = useMemo(() => {
    const list = (onlyToCheck ? rows.filter((r) => r.check) : rows)
      .filter((r) => !account || r.account === account)
      .filter((r) => !search || matches(`${r.description} ${r.head} ${r.account} ${r.why} ${amount(r)}`, search));
    return [...list].sort((a, b) => Number(b.check) - Number(a.check) || a.date.localeCompare(b.date));
  }, [rows, onlyToCheck, search, account]);
  const pager = usePagination({ items: shown, initialPageSize: 25, resetDependencies: [onlyToCheck, search, account] });
  const accountTabs = several && (
    <div role="tablist" aria-label="Statement" className="flex flex-wrap items-center gap-1 border-b border-slate-100 px-5 py-2">
      {[{ name: "", lines: rows.length, check: rows.filter((r) => r.check).length }, ...accounts].map((a) => (
        <button key={a.name || "all"} type="button" role="tab" aria-selected={account === a.name} onClick={() => setAccount(a.name)}
                className={cn("inline-flex items-center gap-1.5 rounded-md px-2.5 py-1 font-medium transition-colors",
                              account === a.name ? "bg-teal-50 text-teal-800 ring-1 ring-inset ring-teal-200" : "text-slate-600 hover:bg-teal-50/60 hover:text-teal-800")}>
          {a.name || "All statements"}
          <span className="text-[11px] tabular-nums text-slate-400">{a.lines}</span>
          {a.check > 0 && <span className="rounded-full bg-amber-100 px-1.5 text-[10px] font-semibold tabular-nums text-amber-800">{a.check} to check</span>}
        </button>
      ))}
    </div>
  );
  if (!shown.length)
    return (
      <>
        {accountTabs}
        <Empty text={search ? "No bank line matches the search." : onlyToCheck ? "Nothing to check: every bank line is sorted." : "No bank lines."} />
      </>
    );
  return (
    <div className="text-xs">
      {accountTabs}
      <div className="hidden grid-cols-[80px_minmax(0,1fr)_100px_220px] gap-3 border-b border-slate-200 bg-slate-50 px-5 py-2.5 text-[11px] font-semibold uppercase tracking-wide text-slate-500 sm:grid">
        <span>Date</span><span>Bank line</span><span className="text-right">Amount</span><span>What it is</span>
      </div>
      {pager.paginatedItems.map((r) => {
        const busy = saving === r.key || saving === `confirm:${r.key}` || (Boolean(r.payee) && saving === `payee:${r.payee}`);
        const open = r.check || changing === r.key;
        return (
          <div key={r.key} className={cn("grid gap-2 border-b border-slate-100 px-5 py-2.5 transition hover:bg-slate-50/60 sm:grid-cols-[80px_minmax(0,1fr)_100px_220px] sm:gap-3", r.check && "bg-amber-50/60 hover:bg-amber-50")}>
            <span className="text-slate-500">{formatDate(r.date, "short")}</span>
            <div className="min-w-0">
              <p className={cn("line-clamp-2 break-words font-medium", r.check ? "text-amber-900" : "text-slate-800")} title={r.description}>{r.description}</p>
              <p className="text-[11px] text-slate-500">{several && !account && <span className="font-medium text-slate-600">{r.account} · </span>}{r.why}</p>
            </div>
            <span className={cn("font-medium tabular-nums sm:text-right", r.money_in ? "text-emerald-700" : "text-slate-800")}>{amount(r)}</span>
            <div className="flex items-center gap-1.5">
              {busy ? (
                <Loader2 className="h-4 w-4 animate-spin text-slate-400" />
              ) : open ? (
                <div className="flex min-w-0 flex-1 flex-col gap-1">
                  <div className="flex min-w-0 items-center gap-1.5">
                  <HeadPicker
                    value={r.picked}
                    code={r.code}
                    choices={choices}
                    chart={chart}
                    onPick={(choice) => {
                      setChanging(null);
                      if (r.payee && (perPayee.get(r.payee) || 0) > 1 && !oneOnly.has(r.key)) onChoose(`payee:${r.payee}`, choice);
                      else onChoose(r.key, choice);
                    }}
                  />
                  {r.probable && (
                    <Button size="sm" variant="outline" className="h-7 px-2 text-[11px]" onClick={() => onChoose(`confirm:${r.key}`, { confirmed: true })}>
                      Confirm
                    </Button>
                  )}
                  </div>
                  {r.payee && (perPayee.get(r.payee) || 0) > 1 && (
                    <div className="inline-flex w-fit rounded-md border border-slate-200 bg-white p-0.5 text-[11px]" role="radiogroup"
                         aria-label="Lines the head goes on" title={`The head chosen goes on all ${perPayee.get(r.payee)} "${r.payee}" lines, this year and next year, unless Only this line`}>
                      {[false, true].map((only) => (
                        <button key={String(only)} type="button" role="radio" aria-checked={oneOnly.has(r.key) === only}
                                onClick={() => setOneOnly((prev) => {
                                  const next = new Set(prev);
                                  if (only) next.add(r.key);
                                  else next.delete(r.key);
                                  return next;
                                })}
                                className={cn("whitespace-nowrap rounded px-1.5 py-0.5 font-medium transition-colors",
                                              oneOnly.has(r.key) === only ? "bg-teal-600 text-white" : "text-slate-600 hover:bg-teal-50 hover:text-teal-800")}>
                          {only ? "Only this line" : `All ${perPayee.get(r.payee)} like this`}
                        </button>
                      ))}
                    </div>
                  )}
                </div>
              ) : (
                <button onClick={() => setChanging(r.key)} className="flex min-w-0 items-center gap-1 text-left text-emerald-700 hover:underline" title="Change">
                  <Check className="h-3.5 w-3.5 shrink-0" /> <span className="truncate">{r.head}</span>
                </button>
              )}
              {r.chosen && !busy && (
                <button onClick={() => onChoose(r.key, null)} className="text-slate-400 hover:text-slate-700" title="Undo: back to what the app worked out">
                  <RotateCcw className="h-3.5 w-3.5" />
                </button>
              )}
              {!r.chosen && r.payee_this_year && !busy && (
                <button onClick={() => onChoose(`payee:${r.payee}`, null)} className="text-slate-400 hover:text-slate-700" title={`Undo for every "${r.payee}" line`}>
                  <RotateCcw className="h-3.5 w-3.5" />
                </button>
              )}
            </div>
          </div>
        );
      })}
      <Pager p={pager as UsePaginationResult<unknown>} label="bank lines" />
    </div>
  );
}
