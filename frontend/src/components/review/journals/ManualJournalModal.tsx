"use client";

import { useEffect, useMemo, useState } from "react";
import { Plus, Trash2, CheckCircle2, AlertCircle } from "lucide-react";
import { toast } from "@/lib/notify";
import { Modal } from "@/components/ui/dialog";
import { api } from "@/lib/api";
import { formatCurrency } from "@/lib/formatters";
import { ProposedJournal } from "@/types/engagement";

interface ManualJournalModalProps {
  isOpen: boolean;
  engagementId: string;
  onClose: () => void;
  onSaved: () => void;
  /** A manual journal to change; leave out to enter a new one. */
  journal?: ProposedJournal | null;
}

interface LineDraft {
  account: string; // "3010 - Directors' salaries" or a bare code
  narrative: string;
  debit: string;
  credit: string;
}

const emptyLine = (): LineDraft => ({ account: "", narrative: "", debit: "", credit: "" });

const toPence = (v: string): number => Math.round((parseFloat(v.replace(/[£,]/g, "")) || 0) * 100);

export function ManualJournalModal({ isOpen, engagementId, onClose, onSaved, journal }: ManualJournalModalProps) {
  const [description, setDescription] = useState("");
  const [lines, setLines] = useState<LineDraft[]>([emptyLine(), emptyLine()]);
  const [chart, setChart] = useState<{ std_code: number; std_name: string }[]>([]);
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    if (isOpen && chart.length === 0) {
      api.getMasterCOA().then(setChart);
    }
  }, [isOpen, chart.length]);

  // Editing: start from the journal's own description and lines
  // (set during render when the modal opens or the journal changes, as React does for state following a prop)
  const editing = isOpen ? journal : null;
  const [startedFrom, setStartedFrom] = useState<typeof journal | null>(null);
  if (editing !== startedFrom) {
    setStartedFrom(editing);
    if (editing) {
      setDescription(editing.description);
      const own = (editing.lines || []).map((l) => ({
        account: `${l.account_code} - ${l.account_name || ""}`.trim(),
        narrative: l.narrative || "",
        debit: l.debit ? String(l.debit) : "",
        credit: l.credit ? String(l.credit) : "",
      }));
      setLines(own.length >= 2 ? own : [emptyLine(), emptyLine()]);
    }
  }

  const chartNames = useMemo(() => new Map(chart.map((c) => [c.std_code, c.std_name])), [chart]);

  const parsed = lines.map((l) => {
    const code = parseInt(l.account.trim().split(/\s|-/)[0], 10);
    return { code: Number.isFinite(code) ? code : null, debit: toPence(l.debit), credit: toPence(l.credit) };
  });
  const totalDebit = parsed.reduce((s, l) => s + l.debit, 0);
  const totalCredit = parsed.reduce((s, l) => s + l.credit, 0);
  const amountLines = parsed.filter((l) => l.debit || l.credit);
  const problems: string[] = [];
  if (!description.trim()) problems.push("Add a description");
  if (amountLines.length < 2) problems.push("Enter at least two lines with an amount");
  if (amountLines.some((l) => l.code === null)) problems.push("Every line with an amount needs an account");
  if (parsed.some((l) => l.debit && l.credit)) problems.push("A line can have a debit or a credit, not both");
  if (totalDebit !== totalCredit) problems.push("Debits and credits must be equal");

  const updateLine = (i: number, field: keyof LineDraft, value: string) =>
    setLines((prev) => prev.map((l, idx) => (idx === i ? { ...l, [field]: value } : l)));

  const reset = () => {
    setDescription("");
    setLines([emptyLine(), emptyLine()]);
  };

  const handleSave = async () => {
    if (problems.length) return;
    setSaving(true);
    try {
      const payload = lines
        .map((l, i) => ({ ...parsed[i], narrative: l.narrative.trim() }))
        .filter((l) => l.debit || l.credit)
        .map((l) => ({ account_code: l.code as number, narrative: l.narrative, debit: l.debit / 100, credit: l.credit / 100 }));
      const saved = journal
        ? await api.updateManualJournal(journal.id, description.trim(), payload)
        : await api.createManualJournal(engagementId, description.trim(), payload);
      toast.success(`Journal ${saved.journal_ref} saved`, { description: "It is waiting for approval in the journals list." });
      reset();
      onSaved();
      onClose();
    } catch (err: any) {
      toast.error("Journal not saved", { description: err.message });
    } finally {
      setSaving(false);
    }
  };

  return (
    <Modal
      isOpen={isOpen}
      onClose={saving ? () => {} : onClose}
      title={journal ? `Change journal ${journal.journal_ref}` : "New adjusting journal"}
      description="Enter each line with its account. The journal can be saved once debits equal credits."
      className="max-w-4xl"
    >
      <div className="space-y-4 pt-4">
        <div>
          <label className="block text-xs font-semibold text-slate-700 mb-1">Description</label>
          <input
            value={description}
            onChange={(e) => setDescription(e.target.value)}
            placeholder="e.g. Director's salary reclassified from wages"
            className="w-full rounded-lg border border-slate-200 px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-teal-200"
          />
        </div>

        <datalist id="firm-chart-accounts">
          {chart.map((c) => (
            <option key={c.std_code} value={`${String(c.std_code).padStart(4, "0")} - ${c.std_name}`} />
          ))}
        </datalist>

        <table className="w-full text-xs">
          <thead>
            <tr className="text-left text-slate-500 uppercase tracking-wide text-[11px]">
              <th className="py-1.5 pr-2 w-[38%]">Account</th>
              <th className="py-1.5 pr-2">Narrative</th>
              <th className="py-1.5 pr-2 text-right w-28">Debit £</th>
              <th className="py-1.5 pr-2 text-right w-28">Credit £</th>
              <th className="w-8" />
            </tr>
          </thead>
          <tbody>
            {lines.map((l, i) => {
              const code = parsed[i].code;
              const notInChart = code !== null && chart.length > 0 && !chartNames.has(code);
              return (
                <tr key={i} className="align-top">
                  <td className="py-1 pr-2">
                    <input
                      list="firm-chart-accounts"
                      value={l.account}
                      onChange={(e) => updateLine(i, "account", e.target.value)}
                      placeholder="Type a code or name"
                      className="w-full rounded-md border border-slate-200 px-2 py-1.5 focus:outline-none focus:ring-2 focus:ring-teal-200"
                    />
                    {notInChart && <div className="text-[11px] text-amber-700 mt-0.5">Code {code} is not in the firm chart</div>}
                  </td>
                  <td className="py-1 pr-2">
                    <input
                      value={l.narrative}
                      onChange={(e) => updateLine(i, "narrative", e.target.value)}
                      className="w-full rounded-md border border-slate-200 px-2 py-1.5 focus:outline-none focus:ring-2 focus:ring-teal-200"
                    />
                  </td>
                  <td className="py-1 pr-2">
                    <input
                      inputMode="decimal"
                      value={l.debit}
                      onChange={(e) => updateLine(i, "debit", e.target.value)}
                      className="w-full rounded-md border border-slate-200 px-2 py-1.5 text-right font-mono focus:outline-none focus:ring-2 focus:ring-teal-200"
                    />
                  </td>
                  <td className="py-1 pr-2">
                    <input
                      inputMode="decimal"
                      value={l.credit}
                      onChange={(e) => updateLine(i, "credit", e.target.value)}
                      className="w-full rounded-md border border-slate-200 px-2 py-1.5 text-right font-mono focus:outline-none focus:ring-2 focus:ring-teal-200"
                    />
                  </td>
                  <td className="py-1 text-center">
                    {lines.length > 2 && (
                      <button
                        type="button"
                        onClick={() => setLines((prev) => prev.filter((_, idx) => idx !== i))}
                        className="p-1.5 rounded text-slate-400 hover:text-rose-600 hover:bg-rose-50 cursor-pointer"
                        title="Remove line"
                      >
                        <Trash2 className="w-3.5 h-3.5" />
                      </button>
                    )}
                  </td>
                </tr>
              );
            })}
          </tbody>
          <tfoot>
            <tr className="border-t border-slate-200 font-semibold text-slate-800">
              <td className="pt-2">
                <button
                  type="button"
                  onClick={() => setLines((prev) => [...prev, emptyLine()])}
                  className="inline-flex items-center gap-1 text-xs font-semibold text-teal-800 hover:text-teal-800 cursor-pointer"
                >
                  <Plus className="w-3.5 h-3.5" /> Add line
                </button>
              </td>
              <td className="pt-2 text-right pr-2 text-slate-500">Totals</td>
              <td className="pt-2 pr-2 text-right font-mono">{formatCurrency(totalDebit / 100)}</td>
              <td className="pt-2 pr-2 text-right font-mono">{formatCurrency(totalCredit / 100)}</td>
              <td />
            </tr>
          </tfoot>
        </table>

        <div className="flex items-center justify-between border-t border-slate-100 pt-4">
          <div className="text-xs">
            {problems.length === 0 ? (
              <span className="inline-flex items-center gap-1 text-emerald-700 font-semibold">
                <CheckCircle2 className="w-4 h-4" /> Balanced: {formatCurrency(totalDebit / 100)}
              </span>
            ) : (
              <span className="inline-flex items-center gap-1 text-amber-700">
                <AlertCircle className="w-4 h-4" /> {problems[0]}
                {totalDebit !== totalCredit && ` (difference ${formatCurrency(Math.abs(totalDebit - totalCredit) / 100)})`}
              </span>
            )}
          </div>
          <div className="flex gap-2">
            <button
              type="button"
              onClick={onClose}
              disabled={saving}
              className="px-3 py-1.5 text-xs font-medium rounded-lg border border-slate-200 text-slate-600 hover:bg-slate-50 cursor-pointer disabled:opacity-50"
            >
              Cancel
            </button>
            <button
              type="button"
              onClick={handleSave}
              disabled={saving || problems.length > 0}
              className="px-3 py-1.5 text-xs font-semibold rounded-lg bg-teal-700 hover:bg-teal-800 text-white cursor-pointer disabled:opacity-50 disabled:cursor-not-allowed"
            >
              {saving ? "Saving…" : "Save journal"}
            </button>
          </div>
        </div>
      </div>
    </Modal>
  );
}
