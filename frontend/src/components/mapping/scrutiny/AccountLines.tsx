// One account code's ledger lines in GL scrutiny: filters, status tabs, the lines a page at a time and their totals.
import { useCallback, useEffect, useMemo, useState } from "react";
import { toast } from "@/lib/notify";
import { api, ScrutinyLines } from "@/lib/api";
import { cn } from "@/lib/utils";
import { Tabs } from "@/components/ui/tabs";
import { Button } from "@/components/ui/button";
import { text } from "@/lib/ui";
import { SkeletonRows } from "@/components/common/SkeletonRows";
import { formatCurrency } from "@/lib/formatters";
import { usePagination } from "@/hooks/usePagination";
import { PageControls } from "@/components/common/Pagination";
import { ChartCode, codeLabel, isChecked, Show } from "@/components/mapping/scrutiny/shared";
import { LineRow } from "@/components/mapping/scrutiny/LineRow";

export function AccountLines({
  engagementId,
  codeKey,
  chart,
  onChanged,
  onQueriesChanged,
}: {
  engagementId: string;
  codeKey: string;
  chart: ChartCode[];
  onChanged: (journalChanged: boolean) => void;
  onQueriesChanged: () => void;
}) {
  const [data, setData] = useState<ScrutinyLines | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [show, setShow] = useState<Show>("ALL");
  const [dateQ, setDateQ] = useState("");
  const [textQ, setTextQ] = useState("");
  const [minAmount, setMinAmount] = useState("");
  const [busy, setBusy] = useState<string | null>(null);
  const [moving, setMoving] = useState<string | null>(null);

  const load = useCallback(() => {
    api.getScrutinyLines(engagementId, codeKey).then(setData).catch((e) => setError(e.message));
  }, [engagementId, codeKey]);
  useEffect(load, [load]);

  const lines = useMemo(() => {
    const t = textQ.trim().toLowerCase();
    const d = dateQ.trim();
    const min = parseFloat(minAmount) || 0;
    return (data?.lines || []).filter((l) => {
      if (show === "FLAGGED" && l.flags.length === 0) return false;
      if (show === "OPEN" && isChecked(l)) return false;
      if (show === "OK" && l.decision?.status !== "OK") return false;
      if (show === "MOVED" && l.decision?.status !== "MOVED") return false;
      if (show === "ASKED" && !l.decision?.question) return false;
      if (d && !(l.date || "").split("-").reverse().join("/").includes(d)) return false;
      if (t && ![l.description, l.reference, l.account, l.source].some((s) => s.toLowerCase().includes(t))) return false;
      return Math.abs(l.net) >= min;
    });
  }, [data, show, dateQ, textQ, minAmount]);
  const open = lines.filter((l) => !isChecked(l) && l.decision?.status !== "MOVED");
  // The lines a page at a time (a big account has hundreds): back to page 1 when the account or a filter changes
  const page = usePagination({ items: lines, initialPageSize: 50, resetDependencies: [codeKey, show, dateQ, textQ, minAmount] });
  const all = data?.lines || [];
  const counts: Record<Show, number> = {
    ALL: all.length,
    FLAGGED: all.filter((l) => l.flags.length).length,
    OPEN: all.filter((l) => !isChecked(l)).length,
    OK: all.filter((l) => l.decision?.status === "OK").length,
    MOVED: all.filter((l) => l.decision?.status === "MOVED").length,
    ASKED: all.filter((l) => l.decision?.question).length,
  };

  const run = async (key: string, task: () => Promise<unknown>, journalChanged: boolean, done?: string) => {
    setBusy(key);
    try {
      await task();
      if (done) toast.success(done);
      load();
      onChanged(journalChanged);
    } catch (e) {
      toast.error((e as Error).message);
    } finally {
      setBusy(null);
    }
  };

  if (error) return <p className="px-5 py-6 text-sm text-rose-700">{error}</p>;
  if (!data) return <div className="p-5"><SkeletonRows rows={6} /></div>;

  const th = "px-3 py-2 font-semibold";
  const filterInput = "h-7 w-full rounded border border-slate-200 bg-white px-2 text-[11px] font-normal normal-case tracking-normal text-slate-700";
  const sum = lines.reduce((t, l) => t + l.net, 0);
  // The GL scrutiny analysis columns: Type, Debit, Credit and VAT (when the ledger has it)
  const hasVat = data.lines.some((l) => Boolean(l.vat));
  return (
    <div>
      <div className="px-4 pt-3">
        <p className={text.section}>
          <span className="font-mono text-teal-800">{codeLabel(data.code)}</span> {data.name}
        </p>
        <Tabs
          className="mt-1"
          label="Lines by status"
          value={show}
          onChange={setShow}
          items={([["ALL", "All"], ["FLAGGED", "Flagged"], ["OPEN", "Not checked"], ["OK", "OK"], ["MOVED", "Moved"],
                   ["ASKED", "Asked"]] as [Show, string][]).map(([id, label]) => ({ id, label, count: counts[id] }))}
          actions={open.length > 0 ? (
            <Button size="sm" variant="outline" className="h-8 border-teal-200 text-xs text-teal-800 hover:bg-teal-50"
                    disabled={busy !== null}
                    onClick={() => run("all", () => api.checkScrutinyLines(engagementId, open.map((l) => l.key)), false,
                                       `${open.length} lines marked OK`)}>
              Mark {open.length} shown OK
            </Button>
          ) : undefined}
        />
      </div>
      {data.code === null && (
        <p className="mx-4 mb-3 rounded-md border border-amber-200 bg-amber-50 px-3 py-2 text-xs text-amber-900">
          These lines&apos; accounts have no code yet. Give the account a code on the client accounts view before moving a line.
        </p>
      )}
      <div className="overflow-x-auto border-t border-slate-100">
        <table className="w-full min-w-[42rem] table-fixed text-xs">
          <thead className="border-b border-slate-200 bg-slate-50 text-[11px] uppercase tracking-wide text-slate-500">
            <tr className="text-left">
              <th className={cn(th, "w-[6.5rem] pl-4")}>Date</th>
              <th className={cn(th, "w-28")}>Type</th>
              <th className={th}>Description</th>
              <th className={cn(th, "w-28 text-right")}>Debit</th>
              <th className={cn(th, "w-28 text-right")}>Credit</th>
              {hasVat && <th className={cn(th, "w-20 text-right")}>VAT</th>}
              <th className={cn(th, "w-60 pr-4")}>Decision</th>
            </tr>
            <tr>
              <th className="px-3 pb-2 pl-4"><input value={dateQ} onChange={(e) => setDateQ(e.target.value)} placeholder="dd/mm" className={filterInput} /></th>
              <th />
              <th className="px-3 pb-2"><input value={textQ} onChange={(e) => setTextQ(e.target.value)} placeholder="Search text" className={filterInput} /></th>
              <th colSpan={2} className="px-3 pb-2"><input value={minAmount} onChange={(e) => setMinAmount(e.target.value)} placeholder="Min £" inputMode="decimal" className={cn(filterInput, "text-right")} /></th>
              {hasVat && <th />}
              <th />
            </tr>
          </thead>
          <tbody className="divide-y divide-slate-100">
            {page.paginatedItems.map((l) => (
              <LineRow
                key={l.key}
                l={l}
                hasVat={hasVat}
                chart={chart}
                canMove={data.code !== null}
                fromCode={data.code}
                fromName={data.name}
                busy={busy === l.key}
                moving={moving === l.key}
                setMoving={(on) => setMoving(on ? l.key : null)}
                onOk={(ok) => run(l.key, () => api.checkScrutinyLines(engagementId, [l.key], ok), false)}
                onMove={(code) =>
                  run(l.key, async () => {
                    const j = await api.moveScrutinyLine(engagementId, l.key, code);
                    setMoving(null);
                    toast.success(`Journal ${j.journal_ref} proposed`, { description: "Approve it on the Journals tab." });
                  }, true)
                }
                onUndo={() => run(l.key, () => api.undoScrutinyMove(engagementId, l.key), true, "Move taken back")}
                onAsk={(question) =>
                  run(l.key, async () => {
                    await api.askScrutinyLine(engagementId, l.key, question);
                    onQueriesChanged();
                  }, false, question ? "Question added to the Queries tab" : "Question taken off the Queries tab")
                }
              />
            ))}
            {lines.length === 0 && (
              <tr>
                <td colSpan={hasVat ? 7 : 6} className="px-4 py-6 text-center text-slate-400">No lines match.</td>
              </tr>
            )}
          </tbody>
          <tfoot className="border-t-2 border-slate-200 bg-slate-50 font-semibold text-slate-900">
            <tr>
              <td className="py-2 pl-4" colSpan={3}>
                {lines.length} line{lines.length === 1 ? "" : "s"}{lines.length !== data.lines.length ? ` (of ${data.lines.length})` : ""}
              </td>
              <td className="px-3 py-2 text-right font-mono">{formatCurrency(lines.reduce((t, l) => t + Math.max(l.net, 0), 0))}</td>
              <td className="px-3 py-2 text-right font-mono" title={`Net ${formatCurrency(sum)}`}>{formatCurrency(lines.reduce((t, l) => t + Math.max(-l.net, 0), 0))}</td>
              {hasVat && <td />}
              <td />
            </tr>
          </tfoot>
        </table>
      </div>
      <PageControls page={page} itemLabel="lines" sizes={[50, 100, 200]} />
    </div>
  );
}
