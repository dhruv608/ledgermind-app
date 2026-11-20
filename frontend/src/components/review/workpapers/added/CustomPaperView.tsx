"use client";

import { useState } from "react";
import { Loader2, Paperclip, Plus, Trash2 } from "lucide-react";
import { toast } from "@/lib/notify";
import type { CustomPaper, CustomPaperLine } from "@/lib/api";
import { api } from "@/lib/api";
import { SkeletonRows } from "@/components/common/SkeletonRows";
import { Button } from "@/components/ui/button";
import { Tabs } from "@/components/ui/tabs";
import { Ledger, wp, YearT } from "@/components/review/area/WorkpaperParts";
import { useLedger, useRollforward } from "@/lib/queries/job";
import { LoanScheduleView } from "@/components/review/workpapers/added/LoanScheduleView";
import { cn } from "@/lib/utils";

/** One added working paper, opened: Detailed (its T and ledger), Supporting (a note) or Reconciliation (two sides). */
const { money, th, num } = wp;
const field = "w-full rounded-md border border-slate-300 bg-white px-2 py-1 text-xs text-slate-800 focus:outline-none focus:ring-2 focus:ring-teal-200";

export function CustomPaperView({ engagementId, paper, onSaved, onAttach, yearEnd }: {
  engagementId: string;
  yearEnd?: string;
  paper: CustomPaper;
  onSaved: () => void;
  onAttach: () => void;
}) {
  if (paper.kind === "DETAILED") return <Detailed engagementId={engagementId} paper={paper} />;
  if (paper.kind === "LOAN_SCHEDULE") return <LoanScheduleView engagementId={engagementId} paper={paper} onSaved={onSaved} yearEnd={yearEnd} />;
  if (paper.kind === "SUPPORTING") return <Supporting engagementId={engagementId} paper={paper} onSaved={onSaved} onAttach={onAttach} />;
  return <ReconciliationLines engagementId={engagementId} paper={paper} onSaved={onSaved} />;
}

function Detailed({ engagementId, paper }: { engagementId: string; paper: CustomPaper }) {
  const [view, setView] = useState<"detailed" | "ledger">("detailed");
  const year = useRollforward(engagementId, paper.codes);
  const ledger = useLedger(engagementId, paper.codes[0], view === "ledger");
  return (
    <div className="space-y-3">
      <Tabs label={`${paper.name}`} value={view} onChange={setView}
            items={[{ id: "detailed", label: "Detailed" }, { id: "ledger", label: "Ledger", count: ledger.data?.current.length }]} />
      {view === "detailed" && (year.data ? <YearT rf={year.data} /> : <SkeletonRows rows={5} />)}
      {view === "ledger" && (ledger.data && year.data ? <Ledger lines={ledger.data.current} opening={year.data.opening} account={paper.name} /> : <SkeletonRows rows={6} />)}
    </div>
  );
}

function Supporting({ engagementId, paper, onSaved, onAttach }: { engagementId: string; paper: CustomPaper; onSaved: () => void; onAttach: () => void }) {
  const [note, setNote] = useState(paper.note);
  const [saving, setSaving] = useState(false);
  const save = async () => {
    setSaving(true);
    try {
      await api.updateCustomPaper(engagementId, paper.id, { note });
      onSaved();
      toast.success("Saved");
    } catch (e) {
      toast.error((e as Error).message);
    } finally {
      setSaving(false);
    }
  };
  return (
    <div className="space-y-2">
      <textarea value={note} onChange={(e) => setNote(e.target.value)} rows={5} placeholder="What this paper shows, how it was checked, and the documents behind it"
                className={cn(field, "py-2 leading-relaxed")} />
      <div className="flex justify-between gap-2">
        <Button variant="outline" size="sm" className="h-8 text-xs" onClick={onAttach}><Paperclip className="mr-1.5 h-3.5 w-3.5" /> Attach a document</Button>
        <Button variant="primary" size="sm" className="h-8 text-xs" disabled={saving || note === paper.note} onClick={save}>
          {saving && <Loader2 className="mr-1.5 h-3.5 w-3.5 animate-spin" />} Save
        </Button>
      </div>
    </div>
  );
}

/** Add New Reconciliation: debit details and credit details, and the difference between them */
function ReconciliationLines({ engagementId, paper, onSaved }: { engagementId: string; paper: CustomPaper; onSaved: () => void }) {
  const [lines, setLines] = useState<CustomPaperLine[]>(paper.lines);
  const [saving, setSaving] = useState(false);
  const dirty = JSON.stringify(lines) !== JSON.stringify(paper.lines);
  const total = (side: CustomPaperLine["side"]) => lines.filter((l) => l.side === side).reduce((s, l) => s + (l.amount || 0), 0);
  const difference = total("DEBIT") - total("CREDIT");
  const save = async () => {
    setSaving(true);
    try {
      await api.updateCustomPaper(engagementId, paper.id, { lines: lines.filter((l) => l.label.trim() || l.amount) });
      onSaved();
    } catch (e) {
      toast.error((e as Error).message);
    } finally {
      setSaving(false);
    }
  };
  const side = (s: CustomPaperLine["side"], title: string) => (
    <div className="overflow-hidden rounded-lg border border-slate-200 bg-white">
      <table className="w-full table-fixed text-xs">
        <thead className="border-b border-teal-100 bg-teal-50/80 text-[10.5px] uppercase tracking-wide text-teal-800">
          <tr><th className={cn(th, "pl-3 text-left")}>{title}</th><th className={cn(th, "w-32 text-right")}>Amount</th><th className="w-9" /></tr>
        </thead>
        <tbody className="divide-y divide-slate-100">
          {lines.map((l, i) => l.side !== s ? null : (
            <tr key={i}>
              <td className="py-1 pl-3 pr-2"><input aria-label="Details" value={l.label} placeholder="Details" className={field}
                                                     onChange={(e) => setLines(lines.map((x, j) => (j === i ? { ...x, label: e.target.value } : x)))} /></td>
              <td className="px-2 py-1"><input aria-label="Amount" type="number" step="any" value={l.amount || ""} placeholder="0.00" className={cn(field, "text-right")}
                                               onChange={(e) => setLines(lines.map((x, j) => (j === i ? { ...x, amount: parseFloat(e.target.value) || 0 } : x)))} /></td>
              <td className="pr-2 text-right">
                <button type="button" aria-label="Remove the line" onClick={() => setLines(lines.filter((_, j) => j !== i))}
                        className="rounded p-1 text-slate-400 hover:bg-rose-50 hover:text-rose-600"><Trash2 className="h-3.5 w-3.5" /></button>
              </td>
            </tr>
          ))}
        </tbody>
        <tfoot className="border-t border-teal-100 bg-teal-50/60 font-semibold text-teal-900">
          <tr><td className="py-1.5 pl-3">Total</td><td className={cn(num, "pr-2")}>{money(total(s))}</td><td /></tr>
        </tfoot>
      </table>
      <button type="button" onClick={() => setLines([...lines, { side: s, label: "", amount: 0 }])}
              className="mx-3 my-2 inline-flex items-center gap-1 text-[11px] font-medium text-teal-700 hover:underline">
        <Plus className="h-3.5 w-3.5" /> Add details
      </button>
    </div>
  );
  return (
    <div className="space-y-3">
      <div className="grid gap-3 lg:grid-cols-2">
        {side("DEBIT", "Debit details")}
        {side("CREDIT", "Credit details")}
      </div>
      <div className="flex items-center justify-between gap-3">
        <span className={cn("text-xs font-semibold", Math.abs(difference) >= 0.005 ? "text-rose-700" : "text-emerald-700")}>
          {Math.abs(difference) >= 0.005 ? `Difference ${money(difference)}` : "Debits and credits agree"}
        </span>
        <Button variant="primary" size="sm" className="h-8 text-xs" disabled={!dirty || saving} onClick={save}>
          {saving && <Loader2 className="mr-1.5 h-3.5 w-3.5 animate-spin" />} Save
        </Button>
      </div>
    </div>
  );
}
