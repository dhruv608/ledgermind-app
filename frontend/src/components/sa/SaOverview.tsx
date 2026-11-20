"use client";

// The return at a glance, in the company workspace's parts: the header card with the result's figure tiles, what
// stands before filing (as a company's points), and the income as a table. Where the return stands and what to do
// next live at the top of the checklist, as on a company.
import type { LucideIcon } from "lucide-react";
import { AlertTriangle, Briefcase, CheckCircle2, ChevronRight, FileStack, Globe, HeartHandshake, Home, Landmark,
         PiggyBank, Store, TrendingUp, Wallet } from "lucide-react";
import type { SaOverview as Data, SaState } from "@/lib/api";
import { cn } from "@/lib/utils";
import { NUM, PILL, SaHead, TABLE_WRAP, THEAD, TROW, text } from "@/components/sa/SaChrome";

export const SECTION_ICONS: Record<string, LucideIcon> = {
  employment: Briefcase, self_employment: Store, property: Home, savings: PiggyBank, dividends: TrendingUp,
  pensions: Wallet, foreign: Globe, capital_gains: Landmark, reliefs: HeartHandshake, documents: FileStack,
};
export const STATE_DOT: Record<SaState, string> = {
  done: "bg-emerald-500", look: "bg-amber-500", empty: "bg-slate-300", later: "bg-slate-200",
};

export const money = (v: number) => {
  const s = `£${Math.abs(v).toLocaleString("en-GB", { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
  return v < 0 ? `(${s})` : s;
};

// A section's state as the company checklist says it
export function statePill(state: SaState): { text: string; tone: "done" | "look" | "empty" } | null {
  return state === "done" ? { text: "Done", tone: "done" } : state === "look" ? { text: "To check", tone: "look" }
    : state === "empty" ? { text: "No figures", tone: "empty" } : null;
}

export function SaOverview({ data, open, openDoc }: { data: Data; open: (page: string) => void; openDoc: (id: number) => void }) {
  const r = data.result;
  const refund = r.balance < 0;
  const due = new Date(r.due_date).toLocaleDateString("en-GB", { day: "numeric", month: "long", year: "numeric" });
  const income = data.sections.filter((s) => s.source !== "RELIEFS");
  const total = income.reduce((t, s) => t + Math.max(s.amount, 0), 0);
  const reliefs = data.sections.find((s) => s.source === "RELIEFS");
  const look = data.look.length;

  return (
    <div className="space-y-5">
      <SaHead title="Overview"
              state={look ? { text: `${look} to check`, tone: "look" } : data.documents.count ? { text: "Ready for review", tone: "done" } : { text: "No documents yet", tone: "empty" }}
              meta={refund ? "A refund is due on these figures." : `Tax to pay by ${due}${r.poa_each > 0 ? `, then ${money(r.poa_each)} on account in January and July` : ""}.`}
              figures={[
                { label: "Total income", value: money(total) },
                { label: "Tax and NIC for the year", value: money(r.liability) },
                { label: "Paid at source", value: money(-r.tax_deducted) },
                { label: refund ? "Refund due" : "To pay", value: money(Math.abs(r.balance)), tone: refund ? "text-emerald-700" : undefined },
              ]} />

      {/* What stands before filing, as a company's points */}
      <section className="space-y-2">
        <h3 className={text.label}>Before this can be filed</h3>
        {look === 0 ? (
          <div className="flex items-center gap-2 rounded-xl border border-slate-200 bg-white px-4 py-3 text-sm text-emerald-700 shadow-2xs">
            <CheckCircle2 className="h-4 w-4" />
            {data.documents.count === 0 ? <span className="text-slate-600">Add the client&apos;s documents to start.</span> : "Nothing open on this return."}
          </div>
        ) : (
          <ul className={cn(TABLE_WRAP, "divide-y divide-slate-100")}>
            {data.look.map((l, i) => (
              <li key={i}>
                <button type="button" onClick={() => (l.doc_id ? openDoc(l.doc_id) : open(l.page))}
                        className={cn("group flex w-full items-center gap-3 px-4 py-2.5 text-left cursor-pointer", TROW)}>
                  <AlertTriangle className="h-4 w-4 shrink-0 text-amber-600" />
                  <span className={cn("flex-1", text.body)}>{l.text}</span>
                  <span className="flex items-center gap-0.5 text-xs font-semibold text-teal-700">Open <ChevronRight className="h-3.5 w-3.5" /></span>
                </button>
              </li>
            ))}
          </ul>
        )}
      </section>

      {/* The income, as a table */}
      <section className="space-y-2">
        <h3 className={text.label}>Income</h3>
        <div className={TABLE_WRAP}>
          <table className="w-full table-fixed text-xs">
            <thead className={THEAD}>
              <tr className="text-left">
                <th className="px-4 py-2 font-semibold">Kind</th>
                <th className="w-[38%] px-3 py-2 font-semibold">From</th>
                <th className="w-32 px-3 py-2 text-right font-semibold">Amount</th>
                <th className="w-28 px-4 py-2 text-right font-semibold">State</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-100">
              {[...income, ...(reliefs ? [reliefs] : [])].map((s) => {
                const Icon = SECTION_ICONS[s.id] || Briefcase;
                const pill = statePill(s.state);
                const empty = s.state === "empty";
                return (
                  <tr key={s.id} className={cn("cursor-pointer", TROW)} onClick={() => open(s.id)}>
                    <td className="px-4 py-2.5">
                      <span className="flex items-center gap-2 font-medium text-slate-800"><Icon className="h-3.5 w-3.5 text-slate-400" /> {s.label}</span>
                    </td>
                    <td className="truncate px-3 py-2.5 text-slate-500">
                      {empty ? "—" : s.from === "entered" ? "Entered by hand" : s.from.replace(", entered", " and entered by hand")}
                    </td>
                    <td className={cn("px-3 py-2.5 text-right", NUM, empty ? "text-slate-300" : "text-slate-900")}>{empty ? "—" : money(s.amount)}</td>
                    <td className="px-4 py-2.5 text-right">
                      {pill && <span className={cn("rounded-full px-2 py-px text-[10.5px] font-bold", PILL[pill.tone])}>{pill.text}</span>}
                    </td>
                  </tr>
                );
              })}
            </tbody>
            <tfoot className="border-t border-slate-200 bg-slate-50">
              <tr>
                <td className="px-4 py-2 text-xs font-semibold text-slate-700" colSpan={2}>Total income</td>
                <td className={cn("px-3 py-2 text-right font-semibold text-slate-900", NUM)}>{money(total)}</td>
                <td />
              </tr>
            </tfoot>
          </table>
        </div>
      </section>

      {data.notes.length > 0 && (
        <section className="space-y-2">
          <h3 className={text.label}>Carried forward and kept out</h3>
          <ul className="rounded-xl border border-slate-200 bg-white px-4 py-3 shadow-2xs space-y-1">
            {data.notes.map((n) => <li key={n} className={text.meta}>{n}</li>)}
          </ul>
        </section>
      )}
    </div>
  );
}
