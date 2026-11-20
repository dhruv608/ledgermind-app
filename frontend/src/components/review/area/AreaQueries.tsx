"use client";

import { useEffect, useState } from "react";
import { ArrowRight, Loader2, MessageSquarePlus, Trash2 } from "lucide-react";
import { toast } from "@/lib/notify";
import type { AuditFinding } from "@/types/engagement";
import type { JobQueries, JobQuery, QueryAudience, QueryUpdate } from "@/lib/api";
import type { Area } from "@/lib/areas";
import { api } from "@/lib/api";
import { isOpen, QueryRow, type GoTo } from "@/components/queries/QueriesPanel";
import { Button } from "@/components/ui/button";
import { CustomSelect } from "@/components/ui/custom-select";

// The job's queries that are not about a review point but belong to an area: the Data check's files and the Books
// tab's bank questions
const AREA_KEYS: Record<string, RegExp> = {
  bank: /^(books:(bank|money_in|money_out|transfer|payee)|data:(bank|statement))/,
  payroll: /^data:payroll/,
  vat: /^data:vat/,
  loans: /^data:loan/,
  fixed: /^data:far/,
  opening: /^data:openings/,
};

// A review point's query is in the area its point is in (pointIds: the area's points), whatever its code says
export const inArea = (q: JobQuery, area: Area, pointIds?: Set<number>) =>
  q.source === "review" && pointIds && q.finding_id ? pointIds.has(q.finding_id)
  : q.source === "raised" ? q.area === area.key || Boolean(q.ref && area.refs.test(q.ref))
    : Boolean(q.ref && area.refs.test(q.ref)) || Boolean(AREA_KEYS[area.key]?.test(q.key));

const AUDIENCES: { id: QueryAudience; label: string }[] = [
  { id: "CLIENT", label: "The client" },
  { id: "ACCOUNTANT", label: "The accountant" },
  { id: "INTERNAL", label: "Internal (preparer)" },
];

/** An area page's Queries tab: this account's queries from the job's one list, answered here or on the Queries
 *  tab (the same list, so both agree), and a query raised by hand, on the account or on one of its points. A client
 *  query raised here goes in the client email on the Queries tab. */
export function AreaQueries({
  engagementId, area, data, onData, raiseFor, onRaiseForUsed, onGoTo, onGoToQueries, pointIds,
}: {
  engagementId: string;
  area: Area;
  /** The area's review points: their queries are listed here */
  pointIds?: Set<number>;
  data: JobQueries | null;
  onData: (next: JobQueries) => void;
  /** A point whose Raise query was pressed: the form opens filled from it */
  raiseFor?: AuditFinding | null;
  onRaiseForUsed?: () => void;
  onGoTo: (tab: GoTo) => void;
  onGoToQueries?: () => void;
}) {
  const [formOpen, setFormOpen] = useState(false);
  const [audience, setAudience] = useState<QueryAudience>("CLIENT");
  const [title, setTitle] = useState("");
  const [detail, setDetail] = useState("");
  const [amount, setAmount] = useState("");
  const [pointId, setPointId] = useState<number | null>(null);
  const [pointTitle, setPointTitle] = useState("");
  const [busy, setBusy] = useState(false);
  const [openKey, setOpenKey] = useState<string | null>(null);
  const [saving, setSaving] = useState<string | null>(null);

  // Raise query on a point: the question starts as the point's title, its figure as the amount (set during render,
  // as React does for state following a prop); the effect below then clears the request
  const [raisedFrom, setRaisedFrom] = useState<AuditFinding | null | undefined>(undefined);
  if (raiseFor !== raisedFrom) {
    setRaisedFrom(raiseFor);
    if (raiseFor) {
      setFormOpen(true);
      setAudience("CLIENT");
      setTitle(raiseFor.finding_title);
      setDetail("");
      setAmount(Number(raiseFor.quantified_amount) > 0 ? String(Number(raiseFor.quantified_amount)) : "");
      setPointId(raiseFor.id);
      setPointTitle(raiseFor.finding_title);
    }
  }
  useEffect(() => {
    if (raiseFor) onRaiseForUsed?.();
  }, [raiseFor, onRaiseForUsed]);

  const reset = () => {
    setFormOpen(false);
    setTitle("");
    setDetail("");
    setAmount("");
    setPointId(null);
    setPointTitle("");
  };

  const raise = async () => {
    setBusy(true);
    try {
      onData(await api.raiseQuery(engagementId, {
        title, detail, audience, area: area.key, amount: Number(amount) || 0, finding_id: pointId ?? undefined,
      }));
      toast.success(audience === "CLIENT" ? "Query raised: it goes in the client email on the Queries tab" : "Query raised");
      reset();
    } catch (e) {
      toast.error(e instanceof Error ? e.message : "Could not raise the query");
    } finally {
      setBusy(false);
    }
  };

  const save = async (update: QueryUpdate, done?: string) => {
    setSaving(update.key);
    try {
      onData(await api.saveQuery(engagementId, update));
      if (done) toast.success(done);
    } catch (e) {
      toast.error((e as Error).message);
    } finally {
      setSaving(null);
    }
  };

  const remove = async (q: JobQuery) => {
    if (!q.raised_id) return;
    setSaving(q.key);
    try {
      onData(await api.removeRaisedQuery(engagementId, q.raised_id));
      toast.success("Query removed");
    } catch (e) {
      toast.error((e as Error).message);
    } finally {
      setSaving(null);
    }
  };

  const mine = (data?.queries || []).filter((q) => inArea(q, area, pointIds));
  const open = mine.filter(isOpen);
  const done = mine.filter((q) => !isOpen(q));

  const list = (items: JobQuery[]) => (
    <div className="overflow-hidden rounded-xl border border-slate-200 bg-white shadow-2xs">
      {items.map((q) => (
        <div key={q.key} className="relative">
          <QueryRow
            q={q}
            expanded={openKey === q.key}
            onToggle={() => setOpenKey(openKey === q.key ? null : q.key)}
            saving={saving === q.key}
            onSave={save}
            onGoTo={onGoTo}
          />
          {q.source === "raised" && openKey === q.key && (
            <Button variant="ghost" size="sm" className="absolute bottom-3 right-3 h-7 text-[11px] text-slate-500"
                    disabled={saving === q.key} onClick={() => remove(q)}>
              <Trash2 className="mr-1 h-3 w-3" /> Remove
            </Button>
          )}
        </div>
      ))}
    </div>
  );

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <p className="text-xs text-slate-500">
          This account&apos;s queries. Answers saved here show on the Queries tab too, and open client queries go in the
          client email there.
        </p>
        <span className="flex gap-2">
          {onGoToQueries && (
            <Button variant="outline" size="sm" className="h-8 text-xs" onClick={onGoToQueries}>
              All queries <ArrowRight className="ml-1 h-3.5 w-3.5" />
            </Button>
          )}
          {!formOpen && (
            <Button size="sm" className="h-8 text-xs" onClick={() => setFormOpen(true)}>
              <MessageSquarePlus className="mr-1 h-3.5 w-3.5" /> Raise query
            </Button>
          )}
        </span>
      </div>

      {formOpen && (
        <div className="space-y-2.5 rounded-xl border border-teal-200 bg-teal-50/40 p-4 text-xs">
          <p className="font-semibold text-slate-800">
            Raise a query {pointTitle ? <span className="font-normal text-slate-600">on the point: {pointTitle}</span> : `on ${area.label}`}
          </p>
          <label className="block">
            <span className="text-[11px] font-medium text-slate-600">Question</span>
            <input value={title} onChange={(e) => setTitle(e.target.value)} maxLength={300}
                   className="mt-1 h-8 w-full rounded-md border border-slate-200 bg-white px-2 text-xs focus:outline-none focus:ring-2 focus:ring-teal-200" />
          </label>
          <label className="block">
            <span className="text-[11px] font-medium text-slate-600">More detail (optional)</span>
            <textarea value={detail} onChange={(e) => setDetail(e.target.value)} rows={2}
                      className="mt-1 w-full rounded-md border border-slate-200 bg-white px-2 py-1.5 text-xs focus:outline-none focus:ring-2 focus:ring-teal-200" />
          </label>
          <div className="flex flex-wrap items-end gap-3">
            <label>
              <span className="text-[11px] font-medium text-slate-600">For</span>
              <CustomSelect className="mt-1 block" value={audience} onChange={(v) => setAudience(v as QueryAudience)}
                            options={AUDIENCES.map((a) => ({ value: a.id, label: a.label }))} />
            </label>
            <label>
              <span className="text-[11px] font-medium text-slate-600">Amount (optional)</span>
              <input value={amount} onChange={(e) => setAmount(e.target.value.replace(/[^\d.]/g, ""))} inputMode="decimal"
                     className="mt-1 block h-8 w-32 rounded-md border border-slate-200 bg-white px-2 text-right text-xs tabular-nums focus:outline-none focus:ring-2 focus:ring-teal-200" />
            </label>
            <span className="ml-auto flex items-center gap-2">
              {busy && <Loader2 className="h-4 w-4 animate-spin text-slate-400" />}
              <Button variant="outline" size="sm" className="h-8 text-xs" disabled={busy} onClick={reset}>Cancel</Button>
              <Button size="sm" className="h-8 text-xs" disabled={busy || !title.trim()} onClick={raise}>Raise query</Button>
            </span>
          </div>
        </div>
      )}

      {!data ? (
        <p className="flex items-center gap-2 text-xs text-slate-500"><Loader2 className="h-4 w-4 animate-spin" /> Loading the queries…</p>
      ) : mine.length === 0 ? (
        <p className="rounded-xl border border-slate-200 bg-white px-4 py-3 text-xs text-slate-500">No queries on this account.</p>
      ) : (
        <>
          {open.length > 0 && (
            <section>
              <h3 className="mb-2 text-xs font-bold uppercase tracking-wide text-slate-400">Open ({open.length})</h3>
              {list(open)}
            </section>
          )}
          {done.length > 0 && (
            <section>
              <h3 className="mb-2 text-xs font-bold uppercase tracking-wide text-slate-400">Answered or done ({done.length})</h3>
              {list(done)}
            </section>
          )}
        </>
      )}
    </div>
  );
}
