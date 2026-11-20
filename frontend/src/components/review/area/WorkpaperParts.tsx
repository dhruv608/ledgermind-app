"use client";

import { useMemo, useState } from "react";
import { Check, Search } from "lucide-react";
import type { LedgerViewLine } from "@/lib/api/ledgerViews";
import type { Rollforward } from "@/lib/api";
import { AskLedge } from "@/components/assistant/AskLedge";
import { Input } from "@/components/ui/input";
import { formatCurrency } from "@/lib/formatters";
import { cn } from "@/lib/utils";

/**
 * The parts every working paper on screen is made of (Summary, Detailed, Ledger, Reconciliation): the figure boxes,
 * the T-account and the ledger with its running balance. Bank, Payroll and the other areas use these, so every
 * working paper looks and works the same.
 */
export const wp = {
  money: (n: number | null | undefined) => (n === null || n === undefined ? "-" : formatCurrency(n)),
  side: (n: number) => (Math.abs(n) < 0.005 ? "" : formatCurrency(Math.abs(n))),
  th: "px-3 py-2 font-semibold",
  num: "px-3 py-2 text-right font-mono tabular-nums",
};
const { side, th, num } = wp;

export interface TLine {
  label: string; ref?: string; dr: number; cr: number; tone?: "red";
  /** A question for Ledge about this line (a difference to explain): an Explain button beside it */
  explain?: string;
}

/** An account's year as a T (Details, Ref, Debit, Credit): the lines, the closing balance carried down on the side
 *  that balances it, and the totals. */
export function TAccount({ lines, closing, closingRef, note }: {
  lines: TLine[];
  /** The closing balance, debit + */
  closing: number;
  closingRef?: string;
  note?: React.ReactNode;
}) {
  const close = { dr: Math.max(-closing, 0), cr: Math.max(closing, 0) };
  const dr = lines.reduce((s, l) => s + l.dr, 0) + close.dr;
  const cr = lines.reduce((s, l) => s + l.cr, 0) + close.cr;
  return (
    <div className="overflow-hidden rounded-xl border border-slate-200 bg-white shadow-2xs">
      <table className="w-full table-fixed text-xs">
        <thead className="border-b border-teal-100 bg-teal-50/80 text-[10.5px] uppercase tracking-wide text-teal-800">
          <tr>
            <th className={cn(th, "pl-4 text-left")}>Details</th>
            <th className={cn(th, "w-60 text-left")}>Ref</th>
            <th className={cn(th, "w-32 text-right")}>Debit</th>
            <th className={cn(th, "w-32 pr-4 text-right")}>Credit</th>
          </tr>
        </thead>
        <tbody className="divide-y divide-slate-100">
          {lines.map((l, i) => (
            <tr key={i} className={cn(l.tone === "red" && "font-semibold text-rose-700")}>
              <td className={cn("py-2 pl-4 pr-3", l.tone !== "red" && "text-slate-800")}>
                {l.label}
                {l.explain && <AskLedge icon label="Explain with Ledge" question={l.explain} className="ml-1 align-middle" />}
              </td>
              <td className="truncate px-3 py-2 text-[11px] text-slate-400" title={l.ref}>{l.ref}</td>
              <td className={num}>{side(l.dr)}</td>
              <td className={cn(num, "pr-4")}>{side(l.cr)}</td>
            </tr>
          ))}
          <tr className="bg-terra-50/60">
            <td className="py-2 pl-4 pr-3 font-semibold text-terra-800">Closing balance c/d</td>
            <td className="truncate px-3 py-2 text-[11px] text-slate-400">{closingRef}</td>
            <td className={cn(num, "font-semibold")}>{side(close.dr)}</td>
            <td className={cn(num, "pr-4 font-semibold")}>{side(close.cr)}</td>
          </tr>
        </tbody>
        <tfoot className="border-t-2 border-teal-200 bg-teal-50/70 font-bold text-teal-900">
          <tr>
            <td className="py-2 pl-4 pr-3">Total</td>
            <td />
            <td className={num}>{formatCurrency(dr)}</td>
            <td className={cn(num, "pr-4")}>{formatCurrency(cr)}</td>
          </tr>
        </tfoot>
      </table>
      {note && <div className="border-t border-slate-100 px-4 py-2 text-[11px]">{note}</div>}
    </div>
  );
}

/** Every line on the account this year, oldest first, with the running balance from the opening. */
export function Ledger({ lines, opening, account }: {
  lines: LedgerViewLine[];
  opening: number;
  /** The account's name, for the question about a line */
  account?: string;
}) {
  const [q, setQ] = useState("");
  const sorted = useMemo(() => [...lines].sort((a, b) => (a.date || "").localeCompare(b.date || "")), [lines]);
  // The running balance from the opening, line by line
  const all = sorted.reduce<(LedgerViewLine & { balance: number })[]>((acc, l) => {
    acc.push({ ...l, balance: (acc.length ? acc[acc.length - 1].balance : opening) + l.net });
    return acc;
  }, []);
  const shown = q ? all.filter((l) => `${l.description} ${l.account} ${l.date} ${l.type || ""} ${l.label || ""}`.toLowerCase().includes(q.toLowerCase())) : all;
  // The ledger columns (Date, Type, Description, Debit, Credit, VAT, Balance, Account name, Label); VAT and
  // Label only when the books carry them
  const hasVat = all.some((l) => Boolean(l.vat));
  const hasLabel = all.some((l) => l.label);
  return (
    <div className="overflow-hidden rounded-xl border border-slate-200 bg-white shadow-2xs">
      <div className="flex items-center gap-2 border-b border-slate-100 px-4 py-2">
        <Search className="h-3.5 w-3.5 text-slate-400" />
        <Input value={q} onChange={(e) => setQ(e.target.value)} placeholder="Search the lines" className="h-8 max-w-xs text-xs" aria-label="Search the lines" />
        <span className="ml-auto text-[11px] text-slate-500">{shown.length} of {all.length} lines</span>
      </div>
      <div className="max-h-[32rem] overflow-y-auto">
        <table className="w-full table-fixed text-xs">
          <thead className="sticky top-0 border-b border-teal-100 bg-teal-50/80 text-[10.5px] uppercase tracking-wide text-teal-800">
            <tr>
              <th className={cn(th, "w-24 pl-4 text-left")}>Date</th>
              <th className={cn(th, "w-28 text-left")}>Type</th>
              <th className={cn(th, "text-left")}>Description</th>
              <th className={cn(th, "w-28 text-right")}>Debit</th>
              <th className={cn(th, "w-28 text-right")}>Credit</th>
              {hasVat && <th className={cn(th, "w-24 text-right")}>VAT</th>}
              <th className={cn(th, "w-32 text-right")}>Balance</th>
              <th className={cn(th, "w-40 text-left")}>Account name</th>
              {hasLabel && <th className={cn(th, "w-28 text-left")}>Label</th>}
              <th className="w-10 pr-3" aria-label="Ask Ledge" />
            </tr>
          </thead>
          <tbody className="divide-y divide-slate-100">
            <tr className="text-slate-500">
              <td className="py-1.5 pl-4" />
              <td />
              <td className="px-3 py-1.5 italic">Opening balance</td>
              <td /><td />
              {hasVat && <td />}
              <td className={cn(num, "py-1.5")}>{formatCurrency(opening)}</td>
              <td />
              {hasLabel && <td />}
              <td />
            </tr>
            {shown.map((l) => (
              <tr key={l.key} className="group">
                <td className="whitespace-nowrap py-1.5 pl-4 text-slate-500">{l.date || "-"}</td>
                <td className="truncate px-3 py-1.5 text-slate-600" title={l.type}>{l.type || "-"}</td>
                <td className="truncate px-3 py-1.5 text-slate-800" title={l.note ? `${l.description} (${l.note})` : l.description}>{l.description || l.note || "-"}</td>
                <td className={cn(num, "py-1.5")}>{side(Math.max(l.net, 0))}</td>
                <td className={cn(num, "py-1.5")}>{side(Math.max(-l.net, 0))}</td>
                {hasVat && <td className={cn(num, "py-1.5 text-slate-500")}>{l.vat ? formatCurrency(l.vat) : ""}</td>}
                <td className={cn(num, "py-1.5 text-slate-600")}>{formatCurrency(l.balance)}</td>
                <td className="truncate px-3 py-1.5 text-slate-500" title={l.account}>{l.account || "-"}</td>
                {hasLabel && <td className="truncate px-3 py-1.5 text-slate-500" title={l.label}>{l.label}</td>}
                <td className="pr-3 text-right opacity-0 transition group-hover:opacity-100 focus-within:opacity-100">
                  <AskLedge icon label="Ask about this line" question={`On ${account || l.account}, the line of ${l.date || "no date"} "${l.description || l.account}" for ${formatCurrency(l.net)} (debit +): what is it, and is it in the right account?`} />
                </td>
              </tr>
            ))}
          </tbody>
        </table>
        {all.length === 0 && <p className="px-4 py-3 text-xs text-slate-500">No ledger lines on this account this year.</p>}
      </div>
    </div>
  );
}


/** The key figures of a working paper in one strip: thin dividers, small labels, large figures. */
export function FigRow({ children, className }: { children: React.ReactNode; className?: string }) {
  return (
    <div className={cn("grid grid-cols-2 overflow-hidden rounded-xl border border-slate-200 bg-white shadow-2xs sm:grid-cols-4 sm:divide-x sm:divide-slate-100", className)}>
      {children}
    </div>
  );
}

/** One figure in the strip. A difference shows as a pill: green when it agrees, red when it differs. */
export function Fig({ label, value, tone }: { label: string; value: string; tone?: string }) {
  const good = tone?.includes("emerald"), bad = tone?.includes("rose");
  return (
    <div className="min-w-0 px-4 py-2.5">
      <span className="block truncate text-[10.5px] font-semibold uppercase tracking-wide text-slate-500" title={label}>{label}</span>
      {good || bad ? (
        <span className={cn("mt-1 inline-flex items-center gap-1 rounded-full px-2 py-0.5 font-mono text-sm font-bold tabular-nums",
                            good ? "bg-emerald-50 text-emerald-700" : "bg-rose-50 text-rose-700")}>
          {good && <Check className="h-3.5 w-3.5" />}{value}
        </span>
      ) : (
        <span className="mt-0.5 block truncate font-mono text-[15px] font-bold tabular-nums text-slate-900">{value}</span>
      )}
    </div>
  );
}

/** The account's year as a T: opening, this year's lines by type, the journals by name, closing carried down. */
export function YearT({ rf }: { rf: Rollforward }) {
  const lines: TLine[] = [
    { label: "Opening balance b/f", dr: Math.max(rf.opening, 0), cr: Math.max(-rf.opening, 0), ref: rf.opening_source ? `from ${rf.opening_source}` : "worked out" },
    // Each named line once, at its net figure (one figure a line); the software's types as the ref
    ...rf.movements.filter((m) => Math.abs(m.net) >= 0.005).map((m) => ({
      label: m.type, dr: Math.max(m.net, 0), cr: Math.max(-m.net, 0),
      ref: `${m.lines} line${m.lines === 1 ? "" : "s"}${m.types?.length ? `: ${m.types.slice(0, 2).join(", ")}${m.types.length > 2 ? " ..." : ""}` : ""}`,
    })),
    ...(rf.journal_lines?.length ? rf.journal_lines.filter((j) => j.amount !== null)
      .map((j) => ({ label: j.named ? j.label : `Journal: ${j.label}`, dr: Math.max(j.amount!, 0), cr: Math.max(-j.amount!, 0), ref: j.note }))
      : Math.abs(rf.journals) >= 0.005 ? [{ label: "Journals", dr: Math.max(rf.journals, 0), cr: Math.max(-rf.journals, 0) }] : []),
  ];
  // What the lines do not reach: the trial balance's closing less opening, lines and journals. Shown as its own red
  // line, so the T still adds up and the gap reads as a figure to explain (an opening missing from the ledger, ledger
  // lines missing), not as a T that does not balance
  const worked = lines.reduce((s, l) => s + l.dr - l.cr, 0);
  const gap = rf.closing - worked;
  const name = rf.names?.[0] || "this account";
  if (Math.abs(gap) >= 1) {
    lines.push({ label: "Not explained by the ledger lines", ref: "trial balance less the lines", dr: Math.max(gap, 0), cr: Math.max(-gap, 0), tone: "red",
                 explain: `On ${name}, the trial balance's closing balance is ${wp.money(rf.closing)} but the opening and this year's ledger lines come to ${wp.money(worked)}: why the ${wp.money(Math.abs(gap))} gap (an opening balance missing from the ledger, or ledger lines missing), and how is it cleared?` });
  }
  return (
    <TAccount lines={lines} closing={rf.closing} note={Math.abs(gap) >= 1 ? (
      <span className="text-rose-700">
        The trial balance holds {wp.money(rf.closing)}, but the opening and this year&apos;s ledger lines come to {wp.money(worked)}: {wp.money(Math.abs(gap))} is not in the ledger lines (often last year&apos;s balance missing from the ledger). Check it on the Files step.
      </span>
    ) : undefined} />
  );
}
