// Each account against its statement or list before the trial balance is made.

import { AlertTriangle, Check } from "lucide-react";
import { BooksData } from "@/lib/api";
import { formatCurrency } from "@/lib/formatters";
import { cn } from "@/lib/utils";

/** Before making the trial balance: each account against its statement or list, as a table at the top of the Books tab
 *  (what agrees, what differs and by how much), so the result of the work is seen before scrolling through the lines. */
export function TrialBalanceChecks({ data }: { data: BooksData }) {
  const c = data.checks;
  const differs = (a: number | null, b: number | null) => (a !== null && b !== null ? Math.round((a - b) * 100) / 100 : null);
  const banks = c.banks ?? [];
  const rows: { label: string; books: number | null; other: number | null; against: string; note?: string }[] = [
    ...(banks.length > 1
      ? banks.map((b) => ({ label: `${b.account} (${b.code})`, books: b.books, other: b.statement, against: "statement" }))
      : [{ label: "Bank", books: c.bank_books, other: c.bank_statement, against: "statement" }]),
    ...(Math.abs(c.transfers ?? 0) >= 0.01
      ? [{ label: "Transfers between own accounts", books: c.transfers, other: 0, against: "nil", note: "one side missing" }] : []),
    { label: "Debtors", books: c.debtors_books, other: c.debtors, against: "unpaid invoices" },
    { label: "Creditors", books: c.creditors_books, other: c.creditors, against: "unpaid bills" },
    { label: "Suspense", books: c.suspense, other: 0, against: "nil",
      note: Math.abs(c.suspense) >= 0.01 ? `${c.questions_open} client question${c.questions_open === 1 ? "" : "s"} open` : undefined },
  ];
  const open = rows.filter((r) => { const d = differs(r.books, r.other); return d === null || Math.abs(d) >= 0.01; }).length;
  return (
    <div className="overflow-hidden rounded-xl border border-slate-200">
      <p className={cn("flex items-center gap-1.5 border-b border-slate-100 px-3 py-2 text-xs font-semibold",
                       open ? "bg-amber-50/60 text-amber-900" : "bg-emerald-50/60 text-emerald-800")}>
        {open ? <AlertTriangle className="h-3.5 w-3.5" /> : <Check className="h-3.5 w-3.5" />}
        {open ? `Before the trial balance: ${open} of ${rows.length} still to agree` : "Every account agrees: ready for the trial balance"}
      </p>
      <table className="w-full text-xs">
        <thead className="text-[10.5px] uppercase tracking-wide text-slate-500">
          <tr className="text-left">
            <th className="px-3 py-1.5 font-semibold">Account</th>
            <th className="px-3 py-1.5 text-right font-semibold">Books</th>
            <th className="px-3 py-1.5 text-right font-semibold">Should be</th>
            <th className="px-3 py-1.5 text-right font-semibold">Difference</th>
          </tr>
        </thead>
        <tbody className="divide-y divide-slate-100">
          {rows.map((r) => {
            const d = differs(r.books, r.other);
            const ok = d !== null && Math.abs(d) < 0.01;
            return (
              <tr key={r.label}>
                <td className="px-3 py-1.5 text-slate-800">
                  {r.label}
                  {r.note && <span className="ml-1.5 text-[11px] text-slate-500">{r.note}</span>}
                </td>
                <td className="px-3 py-1.5 text-right font-mono tabular-nums text-slate-800">{r.books === null ? "-" : formatCurrency(r.books)}</td>
                <td className="px-3 py-1.5 text-right font-mono tabular-nums text-slate-500">
                  {r.other === null ? "-" : formatCurrency(r.other)}
                  <span className="ml-1 font-sans text-[10.5px]">{r.against}</span>
                </td>
                <td className={cn("px-3 py-1.5 text-right font-mono tabular-nums", ok ? "text-emerald-700" : "font-semibold text-amber-700")}>
                  {ok ? <span className="inline-flex items-center gap-1 font-sans"><Check className="h-3.5 w-3.5" />Agrees</span>
                    : d === null ? "-" : formatCurrency(d)}
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}
