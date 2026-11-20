"use client";

import { useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { FileText, Loader2 } from "lucide-react";
import { toast } from "@/lib/notify";
import type { BankStatementMatch, StatementLine } from "@/lib/api";
import { api } from "@/lib/api";
import { AskLedge } from "@/components/assistant/AskLedge";
import { SkeletonRows } from "@/components/common/SkeletonRows";
import { Button } from "@/components/ui/button";
import { Tabs } from "@/components/ui/tabs";
import { wp } from "@/components/review/area/WorkpaperParts";
import { UnrecordedAction } from "@/components/review/journals/UnrecordedAction";
import { jobKeys, useBankStatement, useEvidence } from "@/lib/queries/job";
import { cn } from "@/lib/utils";

/**
 * A bank account's statement lines against its ledger (the bank reconciliation): read a statement uploaded on the
 * bank Evidence, then Matched (statement line beside its ledger line), Unmatched (in the books, not on the
 * statement) and Unrecorded (on the statement, not in the books), each as receipts and payments.
 */
const { money, th, num } = wp;
type View = "unrecorded" | "unmatched" | "matched";
const day = (iso: string | null) => (iso ? new Date(`${iso}T00:00:00`).toLocaleDateString("en-GB") : "-");

export function BankStatementLines({ engagementId, code, account, onAttach }: {
  engagementId: string;
  code: number;
  account: string;
  onAttach: () => void;
}) {
  const qc = useQueryClient();
  const match = useBankStatement(engagementId, code);
  const files = (useEvidence(engagementId).data?.bank || []).filter((f) => f.id !== null && /\.(pdf|csv|xlsx?)$/i.test(f.filename));
  const [pick, setPick] = useState<number | null>(null);
  const [reading, setReading] = useState(false);
  const [view, setView] = useState<View>("unrecorded");
  const chosen = pick ?? files[0]?.id ?? null;

  const read = async () => {
    if (chosen === null) return;
    setReading(true);
    try {
      const r = await api.readBankStatement(engagementId, chosen, code);
      toast.success(`${r.lines} statement lines read`, { description: r.notes[0] });
      await qc.invalidateQueries({ queryKey: jobKeys.bankStatement(engagementId, code) });
    } catch (e) {
      toast.error((e as Error).message);
    } finally {
      setReading(false);
    }
  };

  const m: BankStatementMatch | undefined = match.data;
  return (
    <div className="overflow-hidden rounded-xl border border-slate-200 bg-white shadow-2xs">
      <div className="flex flex-wrap items-end justify-between gap-3 border-b border-teal-100 bg-linear-to-r from-teal-50/70 to-white px-4 py-3">
        <div>
          <h3 className="text-sm font-bold text-teal-900">Statement lines</h3>
          <p className="text-[11px] text-slate-500">
            {m?.read ? `The statement from ${day(m.from)} to ${day(m.to)} against the books: ${m.statement_lines} statement lines, ${m.ledger_lines} ledger lines in those dates.`
              : "Read the bank statement to see which lines are in the books and which are not."}
          </p>
        </div>
        <div className="flex items-center gap-2">
          {files.length > 0 ? (
            <>
              {files.length > 1 && (
                <select aria-label="Statement file" value={chosen ?? ""} onChange={(e) => setPick(Number(e.target.value))}
                        className="h-8 max-w-56 rounded-md border border-slate-300 bg-white px-2 text-xs text-slate-700">
                  {files.map((f) => <option key={f.id!} value={f.id!}>{f.filename}</option>)}
                </select>
              )}
              <Button variant="outline" size="sm" className="h-8 text-xs" disabled={reading || chosen === null} onClick={read}>
                {reading ? <Loader2 className="mr-1.5 h-3.5 w-3.5 animate-spin" /> : <FileText className="mr-1.5 h-3.5 w-3.5" />}
                {reading ? "Reading…" : m?.read ? "Read again" : files.length === 1 ? `Read ${files[0].filename}` : "Read lines"}
              </Button>
            </>
          ) : (
            <Button variant="outline" size="sm" className="h-8 text-xs" onClick={onAttach}>Upload the statement</Button>
          )}
        </div>
      </div>
      {match.isLoading ? <div className="p-4"><SkeletonRows rows={4} /></div> : m?.read && (
        <div className="space-y-3 p-4">
          <Tabs label={`${account} statement lines`} value={view} onChange={setView} items={[
            { id: "unrecorded", label: "Unrecorded", count: m.unrecorded.length },
            { id: "unmatched", label: "Unmatched", count: m.unmatched.length },
            { id: "matched", label: "Matched", count: m.matched.length },
          ]} />
          {view === "matched" ? <Matched pairs={m.matched} /> : (
            <Split lines={view === "unrecorded" ? m.unrecorded : m.unmatched} account={account} kind={view}
                   action={view === "unrecorded" ? (l) => <UnrecordedAction engagementId={engagementId} bankCode={code} line={l} /> : undefined} />
          )}
        </div>
      )}
    </div>
  );
}

/** Receipts and payments apart (Unrecorded Receipts / Unrecorded Payments) */
function Split({ lines, account, kind, action }: {
  lines: StatementLine[];
  account: string;
  kind: "unrecorded" | "unmatched";
  /** The action on each line (unrecorded: post it to an account) */
  action?: (l: StatementLine) => React.ReactNode;
}) {
  if (!lines.length) {
    return <p className="text-xs text-slate-500">{kind === "unrecorded" ? "Every statement line is in the books." : "Every ledger line in the statement's dates is on the statement."}</p>;
  }
  const what = kind === "unrecorded" ? "on the bank statement but not in the books" : "in the books but not on the bank statement";
  return (
    <div className="grid gap-3 lg:grid-cols-2">
      {(["Receipts", "Payments"] as const).map((side) => {
        const list = lines.filter((l) => (side === "Receipts" ? l.amount > 0 : l.amount < 0));
        return (
          <LineTable key={side} title={`${kind === "unrecorded" ? "Unrecorded" : "Unmatched"} ${side.toLowerCase()}`} lines={list} action={action}
                     ask={(l) => `On ${account}, the line of ${day(l.date)} "${l.description}" for ${money(Math.abs(l.amount))} is ${what}. What is it likely to be, and what journal or document would clear it?`} />
        );
      })}
    </div>
  );
}

function LineTable({ title, lines, ask, action }: {
  title: string;
  lines: StatementLine[];
  ask: (l: StatementLine) => string;
  action?: (l: StatementLine) => React.ReactNode;
}) {
  const total = lines.reduce((s, l) => s + Math.abs(l.amount), 0);
  return (
    <div className="overflow-hidden rounded-lg border border-slate-200">
      <table className="w-full table-fixed text-xs">
        <thead className="border-b border-teal-100 bg-teal-50/80 text-[10.5px] uppercase tracking-wide text-teal-800">
          <tr>
            <th className={cn(th, "w-24 pl-3 text-left")}>{title}</th>
            <th className={cn(th, "text-left")} aria-label="Description" />
            <th className={cn(th, "w-28 pr-3 text-right")}>Amount</th>
            {action && <th className={cn(th, "w-32 pr-3 text-right")}>Action</th>}
          </tr>
        </thead>
        <tbody className="divide-y divide-slate-100">
          {lines.map((l) => (
            <tr key={l.id} className="group">
              <td className="whitespace-nowrap py-1.5 pl-3 text-slate-500">{day(l.date)}</td>
              <td className="truncate px-3 py-1.5 text-slate-800" title={l.description}>{l.description || "-"}</td>
              <td className={cn(num, "py-1.5 pr-3")}>
                <span className="inline-flex items-center justify-end gap-1">
                  <span className="opacity-0 transition group-hover:opacity-100"><AskLedge icon label="Ask Ledge" question={ask(l)} /></span>
                  {money(Math.abs(l.amount))}
                </span>
              </td>
              {action && <td className="py-1 pr-3 text-right">{action(l)}</td>}
            </tr>
          ))}
          {!lines.length && <tr><td colSpan={action ? 4 : 3} className="px-3 py-2 text-slate-400">None</td></tr>}
        </tbody>
        {lines.length > 0 && (
          <tfoot className="border-t border-teal-100 bg-teal-50/60 font-semibold text-teal-900">
            <tr><td className="py-1.5 pl-3" colSpan={2}>Total</td><td className={cn(num, "pr-3")}>{money(total)}</td>{action && <td />}</tr>
          </tfoot>
        )}
      </table>
    </div>
  );
}

/** Each statement line beside the ledger line it matched (Bank Account | General Ledger) */
function Matched({ pairs }: { pairs: BankStatementMatch["matched"] }) {
  if (!pairs.length) return <p className="text-xs text-slate-500">No statement line matched a ledger line yet.</p>;
  return (
    <div className="max-h-[28rem] overflow-auto rounded-lg border border-slate-200">
      <table className="w-full table-fixed text-xs">
        <thead className="sticky top-0 border-b border-teal-100 bg-teal-50 text-[10.5px] uppercase tracking-wide text-teal-800">
          <tr>
            <th className={cn(th, "w-24 pl-3 text-left")}>Bank date</th>
            <th className={cn(th, "text-left")}>Bank description</th>
            <th className={cn(th, "w-24 text-left")}>Book date</th>
            <th className={cn(th, "text-left")}>Book description</th>
            <th className={cn(th, "w-28 pr-3 text-right")}>Amount</th>
          </tr>
        </thead>
        <tbody className="divide-y divide-slate-100">
          {pairs.map(({ statement: s, ledger: g }) => (
            <tr key={s.id}>
              <td className="whitespace-nowrap py-1.5 pl-3 text-slate-500">{day(s.date)}</td>
              <td className="truncate px-3 py-1.5 text-slate-800" title={s.description}>{s.description || "-"}</td>
              <td className="whitespace-nowrap px-3 py-1.5 text-slate-500">{day(g.date)}</td>
              <td className="truncate px-3 py-1.5 text-slate-600" title={g.description}>{g.description || g.type || "-"}</td>
              <td className={cn(num, "py-1.5 pr-3", s.amount < 0 && "text-slate-600")}>{s.amount < 0 ? `(${money(-s.amount)})` : money(s.amount)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
