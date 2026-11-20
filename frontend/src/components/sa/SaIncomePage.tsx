"use client";

// One kind of income on the return (or the reliefs): its lines, where each came from, and a row to add one by hand.
// A line read from a document says so; a line left out (an ISA, a salary sacrifice) stays on the page, struck through.
import { useEffect, useState } from "react";
import { toast } from "@/lib/notify";
import { FileText, Plus, Trash2 } from "lucide-react";
import { api, SaDividend, SaLine } from "@/lib/api";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { CustomSelect } from "@/components/ui/custom-select";
import { Modal } from "@/components/ui/dialog";
import { NUM, SaHead, TABLE_WRAP, THEAD, TROW } from "@/components/sa/SaChrome";
import { cn } from "@/lib/utils";

interface Page {
  title: string;
  help: string;
  kinds: { value: string; label: string }[];
  amountLabel: string;
  tax?: boolean;               // a 'tax paid' column (PAYE, tax on a pension)
  share?: boolean;             // a 'your share' column (joint accounts, joint property)
  extra?: string;              // a second amount (property: finance costs)
}

export const PAGES: Record<string, Page> = {
  EMPLOYMENT: { title: "Employment (SA102)", help: "Pay and tax in each employment: from its P60 (added as it is read), or entered here.",
    kinds: [{ value: "PAY", label: "Pay (no P60)" }], amountLabel: "Pay", tax: true },
  SAVINGS: { title: "Savings interest", help: "Interest from each account in the tax year. ISA interest stays out of the figures; a joint account is half each unless the evidence says otherwise.",
    kinds: [{ value: "INTEREST", label: "Interest" }, { value: "ISA", label: "ISA interest (left out)" }], amountLabel: "Interest", tax: true, share: true },
  DIVIDENDS: { title: "Dividends", help: "Dividends received in the tax year, taxed when paid. A director's dividends come from the company's own books.",
    kinds: [{ value: "DIVIDEND", label: "Dividend" }], amountLabel: "Dividend", share: true },
  PENSIONS: { title: "Pensions and benefits", help: "State Pension, private pensions (from their P60s, never from bank credits) and taxable benefits such as Jobseeker's Allowance.",
    kinds: [{ value: "STATE_PENSION", label: "State Pension" }, { value: "PENSION", label: "Private pension" }, { value: "BENEFIT", label: "Taxable benefit (JSA...)" }],
    amountLabel: "Amount", tax: true },
  RELIEFS: { title: "Reliefs", help: "Gift Aid and pension contributions under relief at source, as paid: grossed up (÷ 0.8) they extend the bands. Salary sacrifice and net pay pensions need no entry (kept here as a note). VCT, EIS and SEIS: the amount subscribed in the year (from the EIS3 / SEIS3 certificate or the VCT statement): 30%, 30% and 50% off the income tax. Qualifying loan interest comes off income.",
    kinds: [{ value: "GIFT_AID", label: "Gift Aid (paid)" }, { value: "PENSION_RAS", label: "Pension contribution (relief at source)" }, { value: "SALARY_SACRIFICE", label: "Salary sacrifice (no entry)" },
            { value: "VCT", label: "VCT subscription" }, { value: "EIS", label: "EIS subscription (EIS3)" }, { value: "SEIS", label: "SEIS subscription (SEIS3)" },
            { value: "LOAN_INTEREST", label: "Qualifying loan interest" }],
    amountLabel: "Paid" },
  SELF_EMPLOYMENT: { title: "Self-employment (SA103)", help: "For now, the taxable profit of each trade. The books, expenses and capital allowances come in stage 5.",
    kinds: [{ value: "PROFIT", label: "Taxable profit" }], amountLabel: "Profit" },
  PROPERTY: { title: "UK property (SA105)", help: "For now, the profit of each property and its residential finance costs (for the 20% credit). Each property in full comes in stage 5.",
    kinds: [{ value: "PROFIT", label: "Property profit" }], amountLabel: "Profit", share: true, extra: "Finance costs" },
  FOREIGN: { title: "Foreign income (SA106)", help: "Foreign income entered as one figure, in pounds. Enter it on the Foreign income page by country and kind instead, for the right rates and the foreign tax credit.",
    kinds: [{ value: "INCOME", label: "Foreign income" }], amountLabel: "Income" },
};

const money = (v: number) => `£${v.toLocaleString("en-GB", { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
const KIND_LABEL: Record<string, string> = Object.fromEntries(
  [{ value: "P60", label: "P60" }, ...Object.values(PAGES).flatMap((p) => p.kinds)].map((k) => [k.value, k.label]));

export function SaIncomePage({ jobId, source, company, onChange, onOpenDoc }: {
  jobId: string; source: string; company?: string | null; onChange?: () => void; onOpenDoc?: (docId: number) => void;
}) {
  const page = PAGES[source];
  const [lines, setLines] = useState<SaLine[] | null>(null);
  const [kind, setKind] = useState(page.kinds[0].value);
  const [label, setLabel] = useState("");
  const [amount, setAmount] = useState("");
  const [tax, setTax] = useState("");
  const [share, setShare] = useState("1");
  const [extra, setExtra] = useState("");
  const [divs, setDivs] = useState<SaDividend[] | null>(null);
  const [adding, setAdding] = useState(false);
  // Every change: the new lines here, and the overview (checklist, result) told
  const changed = (next: SaLine[]) => { setLines(next); onChange?.(); };

  useEffect(() => {
    api.listSaLines(jobId).then(setLines).catch(() => setLines([]));
    if (source === "DIVIDENDS" && company) api.getDirectorDividends(jobId).then(setDivs).catch(() => setDivs([]));
  }, [jobId, source, company]);

  const mine = (lines || []).filter((l) => l.source === source);
  const total = mine.filter((l) => l.include).reduce((s, l) => s + l.amount * l.share, 0);
  const taxTotal = mine.filter((l) => l.include).reduce((s, l) => s + l.tax_paid, 0);

  const add = async () => {
    const a = parseFloat(amount.replace(/[£,]/g, ""));
    if (!label.trim() || isNaN(a)) return toast.error("Enter a name and an amount");
    try {
      changed(await api.addSaLine(jobId, {
        source, kind, label: label.trim(), amount: a, tax_paid: parseFloat(tax.replace(/[£,]/g, "")) || 0,
        share: parseFloat(share) || 1, extra: extra ? parseFloat(extra.replace(/[£,]/g, "")) : null,
      }));
      setLabel(""); setAmount(""); setTax(""); setExtra(""); setShare("1");
      setAdding(false);
    } catch (e: any) {
      toast.error("Not added", { description: e.message });
    }
  };

  const edit = async (l: SaLine, patch: Partial<SaLine>) => {
    try { changed(await api.editSaLine(jobId, l.id, patch)); } catch (e: any) { toast.error("Not saved", { description: e.message }); }
  };
  const remove = async (l: SaLine) => {
    try { changed(await api.deleteSaLine(jobId, l.id)); } catch (e: any) { toast.error("Not removed", { description: e.message }); }
  };
  const addDividends = async () => {
    try {
      changed(await api.addDirectorDividends(jobId));
      setDivs(await api.getDirectorDividends(jobId));
      toast.success("Dividends added from the company's books");
    } catch (e: any) {
      toast.error("Not added", { description: e.message });
    }
  };
  const newDivs = (divs || []).filter((d) => !d.added);

  return (
    <div className="space-y-4">
    <SaHead title={page.title} meta={page.help}
            state={mine.length === 0 ? { text: "No figures", tone: "empty" } : undefined}
            actions={<Button size="sm" className="h-8 text-xs" onClick={() => setAdding(true)}><Plus className="mr-1 h-3.5 w-3.5" /> Add</Button>}
            figures={[
              { label: "Total", value: money(total) },
              ...(page.tax ? [{ label: "Tax paid", value: money(taxTotal) }] : []),
              { label: "Lines", value: String(mine.filter((l) => l.include).length) },
              { label: "From documents", value: String(mine.filter((l) => l.doc_id).length) },
            ]} />
    <section className="space-y-3">
      {source === "DIVIDENDS" && company && divs !== null && (
        <div className="rounded-xl border border-teal-200 bg-teal-50/60 px-4 py-3 flex flex-wrap items-center justify-between gap-3">
          <p className="text-xs text-teal-900">
            {divs.length === 0 ? `No dividends paid in this tax year in ${company}'s books in LedgerMind.`
              : newDivs.length === 0 ? `All ${divs.length} dividends paid in this tax year in ${company}'s books are on the return.`
              : `${newDivs.length} dividend${newDivs.length === 1 ? "" : "s"} paid in this tax year in ${company}'s books (${money(newDivs.reduce((s, d) => s + d.amount, 0))}) not on the return yet.`}
          </p>
          {newDivs.length > 0 && <Button size="sm" variant="primary" onClick={addDividends}>Add from the books</Button>}
        </div>
      )}

      {lines === null ? <div className="skeleton h-16 rounded-xl" /> : (
        <div className={cn(TABLE_WRAP, "overflow-x-auto")}>
          <table className="w-full text-xs">
            <thead className={THEAD}>
              <tr className="text-left">
                <th className="px-4 py-2 font-semibold">Name</th>
                <th className="py-2 font-semibold">Kind</th>
                <th className="py-2 font-semibold text-right">{page.amountLabel}</th>
                {page.tax && <th className="py-2 font-semibold text-right">Tax paid</th>}
                {page.share && <th className="py-2 font-semibold text-right">Share</th>}
                {page.extra && <th className="py-2 font-semibold text-right">{page.extra}</th>}
                <th className="py-2 pl-3 font-semibold">From</th>
                <th className="py-2 font-semibold text-center">Use</th>
                <th />
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-100">
              {mine.length === 0 && (
                <tr><td colSpan={9} className="px-4 py-4 text-slate-500">Nothing yet{source === "EMPLOYMENT" ? ": add the P60 on Documents, or use Add." : ": use Add."}</td></tr>
              )}
              {mine.map((l) => (
                <tr key={l.id} className={cn(TROW, !l.include && "text-slate-400")}>
                  <td className={cn("px-4 py-2 font-medium text-slate-800", !l.include && "line-through text-slate-400")}>
                    {l.label}
                    {l.paid_on && <span className="ml-1 text-slate-400">· {l.paid_on.split("-").reverse().join("/")}</span>}
                    {l.note && <span className="block text-[11px] text-slate-400 no-underline">{l.note}</span>}
                  </td>
                  <td className="py-2 whitespace-nowrap">{KIND_LABEL[l.kind] || l.kind}</td>
                  <td className={cn("py-2 text-right text-slate-900", NUM)}>{money(l.amount)}</td>
                  {page.tax && <td className={cn("py-2 text-right text-slate-700", NUM)}>{money(l.tax_paid)}</td>}
                  {page.share && <td className="py-2 text-right tabular-nums">{l.share === 1 ? "all" : `${Math.round(l.share * 100)}%`}</td>}
                  {page.extra && <td className="py-2 text-right tabular-nums">{l.extra != null ? money(l.extra) : "—"}</td>}
                  <td className="py-2 pl-3 whitespace-nowrap text-slate-500">
                    {l.doc_id ? (
                      <button type="button" onClick={() => onOpenDoc?.(l.doc_id!)} title="Open the document"
                              className="inline-flex items-center gap-1 rounded-full border border-teal-200 bg-teal-50 px-2 py-0.5 text-[11px] font-semibold text-teal-800 hover:bg-teal-100 cursor-pointer">
                        <FileText className="w-3 h-3" /> {l.kind === "P60" ? "P60" : "Document"}
                      </button>
                    ) : (
                      <span className="inline-flex rounded-full border border-slate-200 bg-slate-50 px-2 py-0.5 text-[11px] text-slate-600">
                        {l.paid_on && l.note?.startsWith("From ") ? "Company books" : "Entered"}
                      </span>
                    )}
                  </td>
                  <td className="py-2 text-center">
                    <input type="checkbox" checked={l.include} onChange={() => edit(l, { include: !l.include })}
                           className="accent-teal-600" title={l.include ? "In the figures" : "Left out of the figures"} />
                  </td>
                  <td className="py-2 pr-4 text-right">
                    <button type="button" onClick={() => remove(l)} title="Remove"
                            className="p-1 rounded text-slate-400 hover:text-rose-600 hover:bg-rose-50 cursor-pointer">
                      <Trash2 className="w-3.5 h-3.5" />
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      <Modal isOpen={adding} onClose={() => setAdding(false)} title={`Add to ${page.title.replace(/ \(.*\)$/, "").toLowerCase()}`}
             description={page.help} className="max-w-lg">
        <div className="space-y-3 pt-4">
          {page.kinds.length > 1 && (
            <label className="block space-y-1"><span className="text-xs font-semibold text-slate-700">Kind</span>
              <CustomSelect value={kind} onChange={setKind} options={page.kinds} fullWidth /></label>
          )}
          <label className="block space-y-1"><span className="text-xs font-semibold text-slate-700">Name</span>
            <Input value={label} onChange={(e) => setLabel(e.target.value)} placeholder="Employer, bank or payer" autoFocus /></label>
          <div className="grid grid-cols-2 gap-3">
            <label className="block space-y-1"><span className="text-xs font-semibold text-slate-700">{page.amountLabel}</span>
              <Input value={amount} onChange={(e) => setAmount(e.target.value)} placeholder="0.00" inputMode="decimal" /></label>
            {page.tax && <label className="block space-y-1"><span className="text-xs font-semibold text-slate-700">Tax paid</span>
              <Input value={tax} onChange={(e) => setTax(e.target.value)} placeholder="0.00" inputMode="decimal" /></label>}
            {page.share && <label className="block space-y-1"><span className="text-xs font-semibold text-slate-700">Share</span>
              <CustomSelect value={share} onChange={setShare} fullWidth options={[{ value: "1", label: "All" }, { value: "0.5", label: "Half (joint)" }]} /></label>}
            {page.extra && <label className="block space-y-1"><span className="text-xs font-semibold text-slate-700">{page.extra}</span>
              <Input value={extra} onChange={(e) => setExtra(e.target.value)} placeholder="0.00" inputMode="decimal" /></label>}
          </div>
          <div className="flex justify-end gap-2 pt-2 border-t border-slate-100">
            <Button variant="ghost" size="sm" onClick={() => setAdding(false)}>Cancel</Button>
            <Button variant="primary" size="sm" onClick={add}>Add</Button>
          </div>
        </div>
      </Modal>
    </section>
    </div>
  );
}
