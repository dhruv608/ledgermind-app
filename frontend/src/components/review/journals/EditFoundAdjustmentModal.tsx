"use client";

import { useState } from "react";
import { toast } from "@/lib/notify";
import { Modal } from "@/components/ui/dialog";
import { Button } from "@/components/ui/button";
import { api } from "@/lib/api";
import { formatCurrency } from "@/lib/formatters";
import { ProposedJournal } from "@/types/engagement";

/** The kind and cost of an accrual (Dr cost / Cr 5360) or prepayment (Dr 4900 / Cr cost) the app proposed; null for
 * any other journal. */
export function foundAdjustment(j: ProposedJournal): { kind: "Accrual" | "Prepayment"; cost: number; costName: string } | null {
  if (j.credit_code === 5360 && j.debit_code !== 5360) return { kind: "Accrual", cost: j.debit_code, costName: j.debit_name };
  if (j.debit_code === 4900 && j.credit_code !== 4900) return { kind: "Prepayment", cost: j.credit_code, costName: j.credit_name };
  return null;
}

interface Props {
  journal: ProposedJournal | null;
  onClose: () => void;
  onSaved: () => void;
}

/** Change the amount (and wording) of an accrual or prepayment the app found. Saved as the accountant's own
 * line on the accruals and prepayments panel; the app's proposal is replaced, and the checks, run again, propose the
 * journal from the line. */
export function EditFoundAdjustmentModal({ journal, onClose, onSaved }: Props) {
  const found = journal ? foundAdjustment(journal) : null;
  const [amount, setAmount] = useState("");
  const [description, setDescription] = useState("");
  const [saving, setSaving] = useState(false);

  // Another journal: the form starts from its amount and wording (set during render, as React does for state
  // following a prop)
  const [shownFor, setShownFor] = useState<ProposedJournal | null | undefined>(undefined);
  if (journal !== shownFor) {
    setShownFor(journal);
    if (journal) {
      setAmount(Number(journal.amount).toFixed(2));
      setDescription(journal.description || "");
    }
  }

  if (!journal || !found) return null;
  const value = parseFloat(amount.replace(/[£,]/g, ""));
  const valid = Number.isFinite(value) && value > 0;

  const save = async () => {
    if (!valid) return;
    setSaving(true);
    try {
      await api.editJournalAsLine(journal.id, value, description.trim());
      toast.success(`${found.kind} saved as your line`, {
        description: "The app's suggestion is replaced. Run the checks again to see the journal with your amount.",
      });
      onSaved();
      onClose();
    } catch (err: any) {
      toast.error("Not saved", { description: err.message });
    } finally {
      setSaving(false);
    }
  };

  return (
    <Modal
      isOpen={!!journal}
      onClose={saving ? () => {} : onClose}
      title={`Change this ${found.kind.toLowerCase()}`}
      description={`The app suggested ${formatCurrency(Number(journal.amount))} on ${found.cost} ${found.costName}. Your figure is kept as your own line and wins from now on.`}
      className="max-w-lg"
    >
      <div className="space-y-4 pt-4">
        <div>
          <label className="mb-1 block text-xs font-semibold text-slate-700">Amount £</label>
          <input
            value={amount}
            onChange={(e) => setAmount(e.target.value)}
            inputMode="decimal"
            className="w-full rounded-lg border border-slate-200 px-3 py-2 text-right font-mono text-sm focus:outline-none focus:ring-2 focus:ring-teal-200"
          />
        </div>
        <div>
          <label className="mb-1 block text-xs font-semibold text-slate-700">Description</label>
          <input
            value={description}
            onChange={(e) => setDescription(e.target.value)}
            className="w-full rounded-lg border border-slate-200 px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-teal-200"
          />
        </div>
        <p className="text-[11px] text-slate-500">
          It moves to Accruals and prepayments, where you can change or delete it later.
        </p>
        <div className="flex justify-end gap-2">
          <Button variant="outline" size="sm" onClick={onClose} disabled={saving}>Cancel</Button>
          <Button size="sm" onClick={save} disabled={!valid || saving} className="bg-teal-700 hover:bg-teal-800">
            {saving ? "Saving…" : "Save my figure"}
          </Button>
        </div>
      </div>
    </Modal>
  );
}
