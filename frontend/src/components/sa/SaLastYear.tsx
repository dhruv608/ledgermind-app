"use client";

// Last year: last year's working paper read into its sources, carry-forwards and reliefs. This is
// this year's checklist: each line is matched to this year's figures (Continued, Changed, Unknown) in the next step.
// Lines read wrong can be changed, missed ones added by hand.
import { useEffect, useState } from "react";
import { toast } from "@/lib/notify";
import { AlertTriangle, FileSpreadsheet, History, MessageSquareMore, Plus, Trash2 } from "lucide-react";
import { api, SaDocument, SaExpectLine, SaLastYear as LastYear } from "@/lib/api";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { CustomSelect } from "@/components/ui/custom-select";
import { AddButton, AddPopup, NUM, PILL, PopupField, SaHead, TABLE_WRAP, THEAD, TROW, text } from "@/components/sa/SaChrome";
import { SaQuestions } from "@/components/sa/SaQuestions";
import { cn } from "@/lib/utils";

const money = (v: number | null) => v === null ? "—" :
  `${v < 0 ? "-" : ""}£${Math.abs(v).toLocaleString("en-GB", { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
const num = (s: string) => { const v = parseFloat(s.replace(/[£,]/g, "")); return isNaN(v) ? null : v; };
const STATUS_TONE: Record<string, string> = {
  CONTINUED: "bg-emerald-400", CHANGED: "bg-amber-400", UNKNOWN: "bg-rose-400", ENDED: "bg-slate-300",
};
const ANSWER_LABELS: Record<string, string> = {
  child_benefit: "Child Benefit", student_loan: "Student loan", marriage_allowance: "Marriage Allowance",
  director: "Director of a company", capital_gains: "Capital gains",
};

function Cell({ value, onSave, money: isMoney, className, placeholder }: { value: string | number | null; onSave: (v: string) => void; money?: boolean; className?: string; placeholder?: string }) {
  return (
    <input key={String(value)} placeholder={placeholder} defaultValue={value === null ? "" : isMoney ? Number(value).toFixed(2) : String(value)}
           inputMode={isMoney ? "decimal" : undefined}
           onBlur={(e) => { if (e.target.value !== (value === null ? "" : isMoney ? Number(value).toFixed(2) : String(value))) onSave(e.target.value); }}
           className={cn("w-full rounded border border-transparent bg-transparent px-1.5 py-1 hover:border-slate-200 focus:border-teal-500 focus:bg-white focus:outline-none",
             isMoney && cn("text-right", NUM), className)} />
  );
}

export function SaLastYear({ jobId }: { jobId: string }) {
  const [data, setData] = useState<LastYear | null>(null);
  const [papers, setPapers] = useState<SaDocument[]>([]);
  const [busy, setBusy] = useState<number | null>(null);
  const [source, setSource] = useState("EMPLOYMENT");
  const [kind, setKind] = useState("P60");
  const [name, setName] = useState("");
  const [adding, setAdding] = useState(false);
  const [amount, setAmount] = useState("");

  useEffect(() => {
    api.getSaLastYear(jobId).then(setData).catch(() => {});
    api.listSaDocuments(jobId).then((d) => setPapers(d.filter((x) => /\.(xls|xlsx|xlsm)$/i.test(x.filename)))).catch(() => {});
  }, [jobId]);

  if (!data) return <div className="skeleton h-48 rounded-xl" />;

  const save = async (line: SaExpectLine, patch: Record<string, string | number | null>) => {
    try { setData(await api.editSaLastYearLine(jobId, line.id, patch)); } catch (e: any) { toast.error("Not saved", { description: e.message }); }
  };
  const remove = async (line: SaExpectLine) => {
    try { setData(await api.deleteSaLastYearLine(jobId, line.id)); } catch (e: any) { toast.error("Not removed", { description: e.message }); }
  };
  const add = async () => {
    try {
      setData(await api.addSaLastYearLine(jobId, { source, kind, name: name.trim(), last_amount: num(amount) }));
      setName(""); setAmount("");
    } catch (e: any) { toast.error("Not added", { description: e.message }); }
  };
  const readPaper = async (docId: number) => {
    setBusy(docId);
    try { setData(await api.useAsLastYear(jobId, docId)); toast.success("Last year's working paper read"); }
    catch (e: any) { toast.error("Not read", { description: e.message }); } finally { setBusy(null); }
  };

  const income = data.lines.filter((l) => !["RELIEFS", "CARRY_FORWARD"].includes(l.source));
  const answers = Object.entries(data.answers);
  const others = papers.filter((p) => p.id !== data.document?.id);

  return (
    <div className="space-y-4">
      <SaHead title="Last year"
              state={!data.document ? { text: "Not read", tone: "empty" } : data.counts.UNKNOWN ? { text: `${data.counts.UNKNOWN} unknown`, tone: "look" }
                     : data.lines.some((l) => !l.agreed) ? { text: "Check", tone: "look" } : { text: "Done", tone: "done" }}
              meta="Last year's working paper read into its sources, what was carried forward and the reliefs. This is this year's checklist: every source must be found again this year, changed, or asked about."
              figures={data.document ? [
                { label: "Continued", value: String(data.counts.CONTINUED || 0) },
                { label: "Changed (over 25%)", value: String(data.counts.CHANGED || 0), tone: data.counts.CHANGED ? "text-amber-700" : undefined },
                { label: "Unknown: to ask", value: String(data.counts.UNKNOWN || 0), tone: data.counts.UNKNOWN ? "text-rose-700" : undefined },
                { label: "Taxable income last year", value: money(income.filter((l) => l.kind !== "EXEMPT").reduce((t, l) => t + (l.last_amount || 0), 0)) },
              ] : undefined} />

      {data.document?.note && (
        <div className="flex gap-1.5 rounded-lg border border-amber-200 bg-amber-50 px-3 py-2 text-xs text-amber-900">
          <AlertTriangle className="mt-px h-3.5 w-3.5 shrink-0" />{data.document.note}
        </div>
      )}

      {(!data.document || others.length > 0) && (
        <section className={cn(TABLE_WRAP, "px-4 py-3")}>
          <p className={cn(text.card, "mb-1")}>{data.document ? "Other working papers" : "Read last year's working paper"}</p>
          <p className="mb-2 text-xs text-slate-500">
            {papers.length === 0 ? "Add last year's working paper on Documents: a paper for the year before this one is read here by itself."
              : "A paper whose year was not read (an accounting year to 31 March) can be read as last year's."}
          </p>
          <div className="space-y-1.5">
            {others.map((p) => (
              <div key={p.id} className="flex items-center justify-between gap-3 text-xs">
                <span className="flex min-w-0 items-center gap-1.5 text-slate-700"><FileSpreadsheet className="h-3.5 w-3.5 shrink-0 text-emerald-700" />
                  <span className="truncate">{p.filename}</span>{p.tax_year && <span className="text-slate-400">{p.tax_year}</span>}</span>
                <Button size="sm" variant="outline" className="h-7 shrink-0 text-xs" disabled={busy !== null} onClick={() => readPaper(p.id)}>
                  <History className="mr-1 h-3.5 w-3.5" />{busy === p.id ? "Reading…" : "Read as last year's"}
                </Button>
              </div>
            ))}
          </div>
        </section>
      )}

      {(data.document || data.lines.length > 0) && (
        <section className={TABLE_WRAP}>
          <div className="flex flex-wrap items-center justify-between gap-2 border-b border-slate-200 px-4 py-3">
            <div className="min-w-0">
              <p className={text.card}>Last year&apos;s sources</p>
              {data.document && <p className="truncate text-xs text-slate-500">From {data.document.filename}</p>}
            </div>
            <AddButton onClick={() => setAdding(true)}>Add a line</AddButton>
          </div>
          <table className="w-full table-fixed text-xs">
            <thead className={THEAD}>
              <tr className="text-left">
                <th className="w-36 px-4 py-2 font-semibold">Kind</th>
                <th className="px-3 py-2 font-semibold">Name</th>
                <th className="w-28 px-3 py-2 text-right font-semibold">Last year</th>
                <th className="w-28 px-3 py-2 text-right font-semibold">This year</th>
                <th className="w-36 px-3 py-2 font-semibold">Status</th>
                <th className="w-9" />
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-100">
              {data.lines.length === 0 && <tr><td colSpan={6} className="px-4 py-3 text-slate-500">No sources read: add them below.</td></tr>}
              {data.lines.map((l, i) => (
                <tr key={l.id} className={cn(TROW, "align-top", i > 0 && data.lines[i - 1].source !== l.source && "border-t-2 border-t-slate-200")}>
                  <td className="px-4 py-1.5">
                    <p className="font-medium text-slate-800">{l.source_label}</p>
                    <p className="text-[11px] text-slate-400">{l.kind_label}{!l.auto && " · added by hand"}</p>
                    {!l.agreed && (
                      <button type="button" onClick={() => save(l, {})} title="The two readers read this line differently. Click when it agrees with the working paper."
                              className="mt-0.5 rounded-full bg-amber-100 px-2 py-px text-[10.5px] font-bold text-amber-800 hover:bg-emerald-50 hover:text-emerald-700 cursor-pointer">
                        Check · mark right
                      </button>
                    )}
                  </td>
                  <td className="px-2 py-1.5">
                    <Cell value={l.name} onSave={(v) => save(l, { name: v })} className="text-slate-800" />
                    <p className="truncate px-1.5 text-[11px] text-slate-400" title={l.note || ""}>
                      {[l.ref, l.last_tax !== null && `tax ${money(l.last_tax)}`, l.ended && `ended ${l.ended}`, l.group || l.note].filter(Boolean).join(" · ")}
                    </p>
                    {l.question && (
                      <p className="mt-1 flex gap-1.5 rounded-md bg-amber-50 px-2 py-1.5 text-[11.5px] text-amber-900">
                        <MessageSquareMore className="mt-px h-3.5 w-3.5 shrink-0" />{l.question}
                      </p>
                    )}
                    {(l.question || l.answer || l.hand) && (
                      <Cell value={l.answer} onSave={(v) => save(l, { answer: v || null })} className="mt-1 text-slate-700 placeholder:text-slate-400" placeholder="Answer or note" />
                    )}
                  </td>
                  <td className="px-2 py-1.5"><Cell money value={l.last_amount} onSave={(v) => save(l, { last_amount: num(v) })} className="font-semibold text-slate-900" /></td>
                  <td className={cn("px-3 py-2.5 text-right", NUM, l.this_amount === null ? "text-slate-300" : "text-slate-800")}>{money(l.this_amount)}</td>
                  <td className="px-2 py-1.5">
                    <CustomSelect size="sm" fullWidth value={l.status || ""}
                                  onChange={(v: string) => save(l, { status: v === "AUTO" ? null : v })}
                                  options={[...data.statuses.map((x) => ({ value: x.status, label: x.label })),
                                            ...(l.hand ? [{ value: "AUTO", label: "By the figures" }] : [])]} />
                    <span className={cn("mt-1 inline-block h-1 w-full rounded-full", STATUS_TONE[l.status || ""] || "bg-slate-200")} />
                    {l.hand && <p className="text-[10.5px] text-slate-400">Set by hand</p>}
                  </td>
                  <td className="px-1 py-1.5 text-right">
                    <button type="button" onClick={() => remove(l)} title="Remove" className="rounded p-1 text-slate-400 hover:bg-rose-50 hover:text-rose-600 cursor-pointer">
                      <Trash2 className="h-3 w-3" />
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
          {data.new.length > 0 && (
            <div className="border-t border-slate-200 px-4 py-3">
              <p className={cn(text.label, "mb-1.5")}>New this year (not on last year&apos;s paper)</p>
              <div className="flex flex-wrap gap-1.5">
                {data.new.map((n) => (
                  <span key={n.source + n.name} className={cn("rounded-lg px-2.5 py-1 text-xs", PILL.info)}>
                    {n.source_label}: {n.name} <span className={cn("font-semibold", NUM)}>{money(n.amount)}</span>
                  </span>
                ))}
              </div>
            </div>
          )}
          <AddPopup open={adding} onClose={() => setAdding(false)} onAdd={add} title="Add a line from last year"
                    description="A source, relief or carry-forward on last year's working paper that the reading missed.">
            <PopupField label="Kind" wide>
              <CustomSelect fullWidth searchable value={`${source}|${kind}`}
                            onChange={(v: string) => { const [s, k] = v.split("|"); setSource(s); setKind(k); }}
                            options={Object.entries(data.sources).flatMap(([s, d]) => d.kinds.map((k) => ({
                              value: `${s}|${k.kind}`, label: d.kinds.length > 1 ? `${d.label}: ${k.label}` : d.label, group: d.label })))} />
            </PopupField>
            <PopupField label="Name"><Input value={name} onChange={(e) => setName(e.target.value)} placeholder="Employer, bank, address" /></PopupField>
            <PopupField label="Last year (£)"><Input value={amount} onChange={(e) => setAmount(e.target.value)} inputMode="decimal" /></PopupField>
          </AddPopup>
        </section>
      )}

      {answers.length > 0 && (
        <section className={cn(TABLE_WRAP, "px-4 py-3")}>
          <p className={cn(text.card, "mb-2")}>Last year&apos;s answers</p>
          <div className="flex flex-wrap gap-2">
            {answers.map(([k, v]) => (
              <span key={k} className="rounded-lg bg-slate-50 px-2.5 py-1 text-xs text-slate-700">
                {ANSWER_LABELS[k] || k}: <span className="font-semibold">{v ? "Yes" : "No"}</span>
              </span>
            ))}
          </div>
        </section>
      )}
      <SaQuestions jobId={jobId} />
    </div>
  );
}
