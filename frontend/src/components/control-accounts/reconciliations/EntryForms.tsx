// The forms that agree an account by hand: a figure or a tick against a document, and a bank statement balance.
import { useState } from "react";
import { CheckCircle2 } from "lucide-react";
import { toast } from "@/lib/notify";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { api, Reconciliation, Reconciliations } from "@/lib/api";
import { parseAmount } from "@/components/control-accounts/reconciliations/shared";

/** An account agreed to a document the app does not hold: the figure on it, or a tick (with a note) that it agrees */
export function AgreeForm({ row, engagementId, onSaved }: { row: Reconciliation; engagementId: string; onSaved: (next: Reconciliations) => void }) {
  const entered = row.entered ?? {};
  const [figure, setFigure] = useState(entered.balance != null ? String(entered.balance) : "");
  const [note, setNote] = useState(entered.note ?? "");
  const [problem, setProblem] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);
  const doc = row.compared_with.charAt(0).toLowerCase() + row.compared_with.slice(1);

  const send = async (body: { key: string; balance?: number; agreed?: boolean; note?: string; clear?: boolean }, done: string) => {
    setProblem(null);
    setSaving(true);
    try {
      onSaved(await api.saveReconciliationEntry(engagementId, body));
      toast.success(done);
    } catch (e) {
      toast.error(e instanceof Error ? e.message : "Could not save");
    } finally {
      setSaving(false);
    }
  };

  return (
    <div className="flex flex-wrap items-end gap-3">
      <form
        className="flex items-end gap-2"
        onSubmit={(e) => {
          e.preventDefault();
          const b = parseAmount(figure);
          if (b === null) return setProblem(`Enter the figure on the ${doc} (a credit balance: a minus sign)`);
          send({ key: row.key, balance: b }, "Figure saved");
        }}
      >
        <label className="w-52 text-[11px] text-slate-600">
          Figure on the {doc} (£)
          <Input value={figure} onChange={(e) => { setFigure(e.target.value); setProblem(null); }} inputMode="decimal" placeholder="12,500.00" className="mt-1 font-mono" />
        </label>
        <Button type="submit" size="sm" variant="outline" disabled={saving}>Save figure</Button>
      </form>
      <span className="pb-2 text-[11px] text-slate-400">or</span>
      <form
        className="flex flex-1 items-end gap-2"
        onSubmit={(e) => {
          e.preventDefault();
          send({ key: row.key, agreed: true, note }, "Marked as agreed");
        }}
      >
        <label className="min-w-40 flex-1 text-[11px] text-slate-600">
          Note (optional)
          <Input value={note} onChange={(e) => setNote(e.target.value)} placeholder="Loan statement 31/03/2025" className="mt-1" />
        </label>
        <Button type="submit" size="sm" disabled={saving}>
          <CheckCircle2 className="mr-1.5 h-3.5 w-3.5" />
          It agrees
        </Button>
      </form>
      {row.entered && (
        <Button type="button" variant="ghost" size="sm" disabled={saving} onClick={() => send({ key: row.key, clear: true }, "Removed")}>
          Remove
        </Button>
      )}
      {problem && <p className="basis-full text-[11px] text-rose-700">{problem}</p>}
    </div>
  );
}

/** The statement balance at the year end: in £, or the currency balance and the year-end rate for a foreign account */
export function StatementForm({ row, engagementId, onSaved }: { row: Reconciliation; engagementId: string; onSaved: (next: Reconciliations) => void }) {
  const entered = row.entered ?? {};
  const [balance, setBalance] = useState(entered.balance != null ? String(entered.balance) : "");
  const [amount, setAmount] = useState(entered.currency_amount != null ? String(entered.currency_amount) : "");
  const [rate, setRate] = useState(entered.rate != null ? String(entered.rate) : "");
  // Where the balance came from (the workbook's 'Statement date / page' and 'Rate source'): banks only
  const [statementDate, setStatementDate] = useState(entered.statement_date ?? "");
  const [page, setPage] = useState(entered.page ?? "");
  const [rateSource, setRateSource] = useState(entered.rate_source ?? "");
  const [problem, setProblem] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);
  const foreign = Boolean(row.currency);
  const bank = row.key.startsWith("bank:");

  const send = async (clear = false) => {
    setProblem(null);
    let body;
    if (clear) {
      body = { key: row.key, clear: true };
    } else if (foreign) {
      const a = parseAmount(amount), x = parseAmount(rate);
      if (a === null) return setProblem(`Enter the ${row.currency} balance on the statement`);
      if (x === null || x <= 0) return setProblem(`Enter the year-end rate (${row.currency} per £1), above nil`);
      body = { key: row.key, currency_amount: a, rate: x };
    } else {
      const b = parseAmount(balance);
      if (b === null) return setProblem("Enter the balance on the statement (overdrawn: a minus sign)");
      body = { key: row.key, balance: b };
    }
    if (!clear && bank) body = { ...body, statement_date: statementDate || undefined, page: page.trim() || undefined, rate_source: foreign ? rateSource.trim() || undefined : undefined };
    setSaving(true);
    try {
      onSaved(await api.saveReconciliationEntry(engagementId, body));
      toast.success(clear ? "Statement balance removed" : "Statement balance saved");
    } catch (e) {
      toast.error(e instanceof Error ? e.message : "Could not save the statement balance");
    } finally {
      setSaving(false);
    }
  };

  return (
    <form
      className="flex flex-wrap items-end gap-3"
      onSubmit={(e) => {
        e.preventDefault();
        send();
      }}
    >
      {foreign ? (
        <>
          <label className="w-44 text-[11px] text-slate-600">
            Statement balance ({row.currency})
            <Input value={amount} onChange={(e) => { setAmount(e.target.value); setProblem(null); }} inputMode="decimal" placeholder="12,500.00" className="mt-1 font-mono" />
          </label>
          <label className="w-44 text-[11px] text-slate-600">
            Year-end rate ({row.currency} per £1)
            <Input value={rate} onChange={(e) => { setRate(e.target.value); setProblem(null); }} inputMode="decimal" placeholder="1.2650" className="mt-1 font-mono" />
          </label>
        </>
      ) : (
        <label className="w-52 text-[11px] text-slate-600">
          Statement balance at the year end (£)
          <Input value={balance} onChange={(e) => { setBalance(e.target.value); setProblem(null); }} inputMode="decimal" placeholder="12,500.00" className="mt-1 font-mono" />
        </label>
      )}
      {bank && (
        <>
          <label className="w-36 text-[11px] text-slate-600">
            Statement date
            <Input type="date" value={statementDate} onChange={(e) => setStatementDate(e.target.value)} className="mt-1" />
          </label>
          <label className="w-20 text-[11px] text-slate-600">
            Page
            <Input value={page} onChange={(e) => setPage(e.target.value)} placeholder="3" className="mt-1" />
          </label>
          {foreign && (
            <label className="w-44 text-[11px] text-slate-600">
              Rate source
              <Input value={rateSource} onChange={(e) => setRateSource(e.target.value)} placeholder="HMRC monthly rate" className="mt-1" />
            </label>
          )}
        </>
      )}
      <Button type="submit" size="sm" disabled={saving}>{saving ? "Saving…" : "Save"}</Button>
      {row.entered && (
        <Button type="button" variant="ghost" size="sm" disabled={saving} onClick={() => send(true)}>
          Remove
        </Button>
      )}
      {problem && <p className="basis-full text-[11px] text-rose-700">{problem}</p>}
    </form>
  );
}
