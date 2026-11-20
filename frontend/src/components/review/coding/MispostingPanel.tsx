"use client";

import { useEffect, useMemo, useState } from "react";
import { toast } from "@/lib/notify";
import { ArrowRight, ChevronDown, ChevronRight, EyeOff, Loader2, RotateCcw } from "lucide-react";
import { api } from "@/lib/api";
import type { MispostingGroup, Mispostings } from "@/lib/api";
import { Button } from "@/components/ui/button";
import { CustomSelect } from "@/components/ui/custom-select";
import { SkeletonRows } from "@/components/common/SkeletonRows";
import { cn } from "@/lib/utils";
import { formatCurrency } from "@/lib/formatters";

interface MispostingPanelProps {
  engagementId: string;
  /** After a move or an undo: the journals and balances change */
  onChanged: () => void;
  onLoaded?: (m: Mispostings) => void;
}

type View = "recommended" | "ignored" | "all";

const money = (n: number) => formatCurrency(n);
const day = (d: string | null) => (d ? new Date(d).toLocaleDateString("en-GB") : "");

/** The misposting review: every supplier whose lines sit in more than one profit and loss account, whatever the
 *  amount, highlighted for the accountant. Tick lines and move them to another account with a remark (an approved
 *  journal), or ignore the supplier with the reason; both are kept on the file and can be undone. */
export function MispostingPanel({ engagementId, onChanged, onLoaded }: MispostingPanelProps) {
  const [data, setData] = useState<Mispostings | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [view, setView] = useState<View>("recommended");
  const [openKey, setOpenKey] = useState<string | null>(null);
  const [chart, setChart] = useState<{ std_code: number; std_name: string }[]>([]);

  const loaded = (m: Mispostings) => {
    setData(m);
    onLoaded?.(m);
  };
  // Another job: clear the old error at once (during render); the effect below loads
  const [loadedFor, setLoadedFor] = useState(engagementId);
  if (engagementId !== loadedFor) {
    setLoadedFor(engagementId);
    setError(null);
  }
  useEffect(() => {
    api.getMispostings(engagementId).then(loaded).catch((e) => setError(e.message));
    api.getMasterCOA().then((c) => setChart(c.map(({ std_code, std_name }) => ({ std_code, std_name })))).catch(() => setChart([]));
    // eslint-disable-next-line react-hooks/exhaustive-deps -- loads once per job: loaded (and the parent's onLoaded) is recreated each render
  }, [engagementId]);

  const shown = useMemo(() => (data?.groups || []).filter((g) =>
    view === "ignored" ? g.status === "IGNORED"
      : view === "recommended" ? g.recommended && (g.status === "OPEN" || g.status === "PART")
      : true), [data, view]);

  if (error) return <p className="rounded-xl border border-rose-200 bg-rose-50 px-4 py-3 text-xs text-rose-800">{error}</p>;
  if (!data) return <div className="rounded-xl border border-slate-200 bg-white p-4"><SkeletonRows rows={5} /></div>;

  const views: { id: View; label: string; count: number }[] = [
    { id: "recommended", label: "Recommended", count: data.summary.recommended },
    { id: "ignored", label: "Ignored", count: data.summary.ignored },
    { id: "all", label: "All", count: data.summary.all },
  ];

  return (
    <div className="space-y-4">
      <div className="rounded-xl border border-slate-200 bg-white p-4 shadow-2xs">
        <h2 className="text-sm font-bold text-slate-900">Misposting review</h2>
        <p className="mt-0.5 text-xs text-slate-500">
          Suppliers whose costs sit in more than one account. When most lines are in one account, the few elsewhere are
          probably posted wrong. Tick them and move them with a remark (an approved journal), or ignore the supplier.
          Recommended shows the clear cases; All shows every split.
        </p>
      </div>

      <div role="tablist" aria-label="Misposting views" className="flex flex-wrap gap-1 border-b border-slate-200">
        {views.map((v) => (
          <button key={v.id} type="button" role="tab" aria-selected={view === v.id} onClick={() => setView(v.id)}
                  className={cn("-mb-px border-b-2 px-3 py-2 text-xs font-semibold",
                                view === v.id ? "border-teal-600 text-teal-700" : "border-transparent text-slate-500 hover:text-slate-800")}>
            {v.label}
            <span className="ml-1.5 rounded-full bg-slate-100 px-1.5 py-px text-[10px] text-slate-600">{v.count}</span>
          </button>
        ))}
      </div>

      {shown.length === 0 ? (
        <p className="rounded-xl border border-slate-200 bg-white px-4 py-3 text-xs text-slate-500">
          {view === "recommended" ? "No clear mispostings left to look at." : view === "ignored" ? "Nothing ignored." : "No supplier is split across accounts."}
        </p>
      ) : (
        <ul className="space-y-2">
          {shown.map((g) => (
            <SupplierRow key={g.key} engagementId={engagementId} g={g} chart={chart} open={openKey === g.key}
                         onToggle={() => setOpenKey(openKey === g.key ? null : g.key)}
                         onData={(m, changed) => { loaded(m); if (changed) onChanged(); }} />
          ))}
        </ul>
      )}
    </div>
  );
}

const STATUS: Record<MispostingGroup["status"], { text: string; tone: string } | null> = {
  OPEN: null,
  PART: { text: "Part moved", tone: "bg-sky-100 text-sky-800" },
  MOVED: { text: "Moved", tone: "bg-emerald-50 text-emerald-700" },
  IGNORED: { text: "Ignored", tone: "bg-slate-100 text-slate-600" },
};

function SupplierRow({ engagementId, g, chart, open, onToggle, onData }: {
  engagementId: string;
  g: MispostingGroup;
  chart: { std_code: number; std_name: string }[];
  open: boolean;
  onToggle: () => void;
  onData: (m: Mispostings, changed: boolean) => void;
}) {
  // The minority lines start ticked: the suggested move to the supplier's main account
  const suggested = g.accounts.filter((a) => !a.main).flatMap((a) => a.lines.filter((l) => !l.moved_to).map((l) => l.key));
  const [ticked, setTicked] = useState<Set<string>>(new Set(g.recommended ? suggested : []));
  const [to, setTo] = useState<number>(g.main_code);
  const [remark, setRemark] = useState("");
  const [busy, setBusy] = useState(false);
  const status = STATUS[g.status];

  const send = async (action: "MOVE" | "IGNORE" | "UNDO") => {
    setBusy(true);
    try {
      const m = await api.decideMisposting(engagementId, {
        merchant_key: g.key, action, line_keys: action === "MOVE" ? Array.from(ticked) : undefined,
        to_code: action === "MOVE" ? to : undefined, remark,
      });
      toast.success(action === "MOVE" ? `${ticked.size} line${ticked.size === 1 ? "" : "s"} moved: journal posted`
        : action === "IGNORE" ? `${g.merchant} ignored, kept on the file` : `${g.merchant}: moves and ignore undone`);
      setRemark("");
      onData(m, action !== "IGNORE");
    } catch (e) {
      toast.error(e instanceof Error ? e.message : "Could not save");
    } finally {
      setBusy(false);
    }
  };

  const toggle = (key: string) => setTicked((prev) => {
    const next = new Set(prev);
    if (next.has(key)) next.delete(key); else next.add(key);
    return next;
  });
  const others = chart.filter((c) => !g.accounts.some((a) => a.code === c.std_code));

  return (
    <li className="rounded-xl border border-slate-200 bg-white shadow-2xs">
      <button type="button" onClick={onToggle} className="flex w-full items-start gap-3 px-4 py-3 text-left hover:bg-slate-50/70">
        {open ? <ChevronDown className="mt-0.5 h-4 w-4 shrink-0 text-slate-400" /> : <ChevronRight className="mt-0.5 h-4 w-4 shrink-0 text-slate-400" />}
        <span className="min-w-0 flex-1">
          <span className="flex flex-wrap items-center gap-2 text-[13px] font-semibold text-slate-900">
            {g.merchant}
            {status && <span className={cn("rounded-full px-1.5 py-px text-[10px] font-bold", status.tone)}>{status.text}</span>}
          </span>
          <span className="mt-0.5 block text-xs text-slate-600">
            {g.accounts.map((a) => `${a.count} in ${a.name || a.code}`).join(" · ")}
          </span>
          <span className="mt-0.5 block text-[11px] text-slate-500">{g.reason}</span>
        </span>
        <span className="shrink-0 text-right text-xs">
          <span className="block font-semibold tabular-nums text-slate-800">{money(g.minority_total)}</span>
          <span className="text-[11px] text-slate-500">{g.minority_lines} line{g.minority_lines === 1 ? "" : "s"} outside the main account</span>
        </span>
      </button>

      {open && (
        <div className="space-y-3 border-t border-slate-100 px-4 pb-4 pt-3">
          {g.accounts.map((a) => (
            <div key={a.code} className="overflow-hidden rounded-lg border border-slate-200">
              <p className="flex flex-wrap items-center justify-between gap-2 bg-slate-50 px-3 py-1.5 text-[11px] font-semibold text-slate-700">
                <span>{a.code} {a.name}{a.main ? " (main account)" : ""}</span>
                <span className="tabular-nums">{a.count} line{a.count === 1 ? "" : "s"} · {money(a.total)}</span>
              </p>
              <table className="w-full table-fixed text-xs">
                <tbody className="divide-y divide-slate-100">
                  {a.lines.map((l) => (
                    <tr key={l.key} className={cn(l.moved_to && "text-slate-400")}>
                      <td className="w-8 px-3 py-1.5">
                        <input type="checkbox" aria-label={`Tick ${l.description}`} disabled={Boolean(l.moved_to) || busy}
                               checked={ticked.has(l.key)} onChange={() => toggle(l.key)} className="h-3.5 w-3.5 accent-teal-600" />
                      </td>
                      <td className="w-24 py-1.5 tabular-nums">{day(l.date)}</td>
                      <td className="truncate py-1.5" title={l.description}>{l.description}</td>
                      <td className="w-28 py-1.5 pr-3 text-right font-mono tabular-nums">{money(l.amount)}</td>
                      <td className="w-28 py-1.5 pr-3 text-right text-[11px]">{l.moved_to ? `moved to ${l.moved_to}` : ""}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          ))}

          {g.moves.length > 0 && (
            <ul className="space-y-1 text-[11px] text-slate-600">
              {g.moves.map((m, i) => (
                <li key={i}>Moved {m.lines.length} line{m.lines.length === 1 ? "" : "s"} ({money(m.total)}) to {m.to}: {m.remark}</li>
              ))}
            </ul>
          )}
          {g.ignored && <p className="text-[11px] text-slate-600">Ignored{g.ignored.remark ? `: ${g.ignored.remark}` : ""}</p>}

          <div className="flex flex-wrap items-end gap-2 rounded-lg bg-slate-50 px-3 py-2.5 text-xs">
            <label className="min-w-0">
              <span className="block text-[11px] font-medium text-slate-600">Move the {ticked.size} ticked line{ticked.size === 1 ? "" : "s"} to</span>
              <CustomSelect className="mt-1 block" buttonClassName="max-w-[18rem]" value={to} onChange={(v) => setTo(Number(v))}
                            searchable={others.length > 0} searchPlaceholder="Account name or code"
                            options={[
                              ...g.accounts.map((a) => ({ value: a.code, label: `${a.code} ${a.name}${a.main ? " (main)" : ""}`,
                                                          group: others.length > 0 ? "This supplier's accounts" : undefined })),
                              ...others.map((c) => ({ value: c.std_code, label: `${c.std_code} ${c.std_name}`, group: "Another account" })),
                            ]} />
            </label>
            <label className="min-w-[12rem] flex-1">
              <span className="block text-[11px] font-medium text-slate-600">Remark (why; kept with the journal)</span>
              <input value={remark} onChange={(e) => setRemark(e.target.value)} placeholder="e.g. fuel, posted to cost of sales in error"
                     className="mt-1 h-8 w-full rounded-md border border-slate-200 bg-white px-2 text-xs focus:outline-none focus:ring-2 focus:ring-teal-200" />
            </label>
            <span className="flex items-center gap-2">
              {busy && <Loader2 className="h-4 w-4 animate-spin text-slate-400" />}
              <Button size="sm" className="h-8 text-xs" disabled={busy || ticked.size === 0 || !remark.trim()} onClick={() => send("MOVE")}>
                <ArrowRight className="mr-1 h-3.5 w-3.5" /> Move
              </Button>
              {g.status !== "IGNORED" && (
                <Button variant="outline" size="sm" className="h-8 text-xs" disabled={busy} onClick={() => send("IGNORE")}>
                  <EyeOff className="mr-1 h-3.5 w-3.5" /> Ignore
                </Button>
              )}
              {(g.moves.length > 0 || g.ignored) && (
                <Button variant="ghost" size="sm" className="h-8 text-xs" disabled={busy} onClick={() => send("UNDO")}>
                  <RotateCcw className="mr-1 h-3.5 w-3.5" /> Undo
                </Button>
              )}
            </span>
          </div>
        </div>
      )}
    </li>
  );
}
