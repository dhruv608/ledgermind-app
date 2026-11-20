// The VAT proof: the lines that explain the VAT account, with the typed lines editable in place.
import { Fragment, useState } from "react";
import { toast } from "@/lib/notify";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { api, Reconciliations, VatProof, VatProofLine } from "@/lib/api";
import { cn } from "@/lib/utils";
import { money, parseAmount } from "@/components/control-accounts/reconciliations/shared";

/** The VAT proof (the VAT reconciliation layout for the client's scheme and basis): each line that explains the
 * VAT account, the total, the books and what is left; the exception report and adjustments are typed here */
export function VatProofBox({ proof, engagementId, onSaved }: { proof: VatProof; engagementId: string; onSaved: (next: Reconciliations) => void }) {
  const [editing, setEditing] = useState<string | null>(null);
  if (proof.missing) return <p className="text-[11px] text-slate-500">{proof.missing}</p>;
  return (
    <div className="overflow-hidden rounded-lg border border-slate-200">
      <div className="bg-slate-50 px-3 py-2 text-xs font-semibold text-slate-800">{proof.title}</div>
      <table className="w-full text-xs">
        <tbody>
          {proof.lines.map((l) => (
            <Fragment key={l.key}>
              <tr className="border-t border-slate-100 align-top">
                <td className="px-3 py-2">
                  <span className="block font-medium text-slate-800">{l.label}</span>
                  <span className="block text-[11px] text-slate-500">{l.note}</span>
                </td>
                <td className="w-32 whitespace-nowrap px-3 py-2 text-right font-mono">
                  {l.amount === null ? <span className="text-slate-400">{l.entered ? "-" : "Not known"}</span> : money(l.amount)}
                </td>
                <td className="w-16 px-2 py-2 text-right">
                  {l.entered && (
                    <button type="button" className="text-[11px] font-medium text-teal-700 hover:underline" onClick={() => setEditing(editing === l.key ? null : l.key)}>
                      {l.amount === null ? "Add" : "Edit"}
                    </button>
                  )}
                </td>
              </tr>
              {editing === l.key && (
                <tr>
                  <td colSpan={3} className="px-3 pb-3">
                    <ProofLineForm line={l} engagementId={engagementId} onSaved={(next) => { setEditing(null); onSaved(next); }} />
                  </td>
                </tr>
              )}
            </Fragment>
          ))}
          <tr className="border-t border-slate-300 font-semibold">
            <td className="px-3 py-2">Total</td>
            <td className="px-3 py-2 text-right font-mono">{money(proof.total)}</td>
            <td />
          </tr>
          <tr className="border-t border-slate-100">
            <td className="px-3 py-2 text-slate-600">VAT owed per the books</td>
            <td className="px-3 py-2 text-right font-mono">{money(proof.books)}</td>
            <td />
          </tr>
          <tr className="border-t border-slate-100 font-semibold">
            <td className="px-3 py-2">Difference</td>
            <td className={cn("px-3 py-2 text-right font-mono", proof.difference !== null && Math.abs(proof.difference) >= 1 && "text-rose-700")}>
              {money(proof.difference)}
            </td>
            <td />
          </tr>
        </tbody>
      </table>
    </div>
  );
}

function ProofLineForm({ line, engagementId, onSaved }: { line: VatProofLine; engagementId: string; onSaved: (next: Reconciliations) => void }) {
  const key = `vatproof:${line.key}`;
  const [figure, setFigure] = useState(line.amount !== null ? String(line.amount) : "");
  const [note, setNote] = useState(line.amount !== null ? line.note : "");
  const [saving, setSaving] = useState(false);
  const send = async (body: { key: string; balance?: number; note?: string; clear?: boolean }) => {
    setSaving(true);
    try {
      onSaved(await api.saveReconciliationEntry(engagementId, body));
      toast.success(body.clear ? "Removed" : "Saved");
    } catch (e) {
      toast.error(e instanceof Error ? e.message : "Could not save");
    } finally {
      setSaving(false);
    }
  };
  return (
    <form
      className="flex flex-wrap items-end gap-2"
      onSubmit={(e) => {
        e.preventDefault();
        const b = parseAmount(figure);
        if (b === null) return toast.error("Enter an amount (less: a minus sign)");
        send({ key, balance: b, note });
      }}
    >
      <label className="w-36 text-[11px] text-slate-600">
        Amount (£)
        <Input value={figure} onChange={(e) => setFigure(e.target.value)} inputMode="decimal" placeholder="-120.00" className="mt-1 font-mono" />
      </label>
      <label className="min-w-40 flex-1 text-[11px] text-slate-600">
        What it is
        <Input value={note} onChange={(e) => setNote(e.target.value)} placeholder="Fuel scale charge not posted" className="mt-1" />
      </label>
      <Button type="submit" size="sm" disabled={saving}>Save</Button>
      {line.amount !== null && (
        <Button type="button" size="sm" variant="outline" disabled={saving} onClick={() => send({ key, clear: true })}>Remove</Button>
      )}
    </form>
  );
}
