"use client";

// A business's books from the bank statements (backend sa/books/): each line of the period under an SA103 heading by
// the firm's bank rules, or out of the business (drawings, capital, own transfers); the accountant changes any line,
// the AI suggests a heading for the lines no rule sorts, and the totals go into the business in one click.
import { useEffect, useMemo, useState } from "react";
import { toast } from "@/lib/notify";
import { AlertTriangle, ArrowDownToLine, Landmark, Sparkles } from "lucide-react";
import { api, SaBankBooks, SaBankBookLine, SaTradeView } from "@/lib/api";
import { Button } from "@/components/ui/button";
import { CustomSelect } from "@/components/ui/custom-select";
import { NUM, PILL, THEAD, TROW, text } from "@/components/sa/SaChrome";
import { cn } from "@/lib/utils";

const money = (v: number) => `£${Math.abs(v).toLocaleString("en-GB", { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
const day = (iso: string) => { const [y, m, d] = iso.split("-"); return `${d}/${m}/${y.slice(2)}`; };
const OUTSIDE = new Set(["DRAWINGS", "CAPITAL", "TRANSFER", "NOT_TRADE", "LOAN", "LOAN_IN", "VAT", "ASSET", "TAX", "ASK",
                         "UNSORTED"]);

// A mixed-use cost's business %: saved on leaving the box; only the business share is allowed
function MixedUse({ m, onSave }: { m: NonNullable<SaBankBooks["mixed"]>[number]; onSave: (pct: number | null) => void }) {
  const [v, setV] = useState(m.business_pct === null || m.business_pct === undefined ? "" : String(m.business_pct));
  return (
    <label className="flex items-center gap-2 text-xs text-slate-700">
      <span className="min-w-44">{m.label} <span className={NUM}>{money(m.amount)}</span></span>
      <input type="number" min="0" max="100" step="1" value={v} placeholder="%"
             onChange={(e) => setV(e.target.value)}
             onBlur={() => onSave(v === "" ? null : Math.min(100, Math.max(0, Number(v))))}
             className="h-7 w-16 rounded-md border border-slate-200 px-2 text-right text-xs" />
      <span className="text-slate-500">% business use{m.business_pct !== null && m.business_pct !== undefined
        ? ` · ${money(m.disallowed)} not allowed` : " · not given yet"}</span>
    </label>
  );
}

export function SaTradeBank({ jobId, businessId, onPosted }: { jobId: string; businessId: number; onPosted: (v: SaTradeView) => void }) {
  const [data, setData] = useState<SaBankBooks | null>(null);
  const [show, setShow] = useState<string>("check");
  const [busy, setBusy] = useState("");
  useEffect(() => { api.getSaTradeBank(jobId, businessId).then(setData).catch(() => {}); }, [jobId, businessId]);

  const options = useMemo(() => (data?.headings || []).map((h) => ({
    value: h.heading, label: h.label, group: OUTSIDE.has(h.heading) ? "Out of the business" : "SA103 headings",
  })), [data]);

  if (!data) return <div className="skeleton h-24 rounded-lg m-4" />;
  if (data.lines.length === 0) {
    return <p className="px-4 py-3 text-xs text-slate-500">No bank statements read yet: add them on Documents and their lines are sorted here.</p>;
  }

  const lines = data.lines.filter((l) => show === "all" || (show === "check" ? !l.sure : l.heading === show));
  const toCheck = data.lines.filter((l) => !l.sure).length;
  const unsorted = data.lines.filter((l) => l.heading === "UNSORTED" && !l.suggestion).length;

  const choose = async (keys: string[], heading: string | null) => {
    try { setData(await api.chooseSaTradeBank(jobId, businessId, keys, heading)); } catch (e: any) { toast.error("Not saved", { description: e.message }); }
  };
  const run = async (what: string, fn: () => Promise<void>) => {
    setBusy(what);
    try { await fn(); } catch (e: any) { toast.error("Not done", { description: e.message }); } finally { setBusy(""); }
  };
  // One suggestion is for a payee: using it puts every line of that payee under the heading
  const samePayee = (l: SaBankBookLine) => data.lines.filter((x) => x.suggestion && x.suggestion.reason === l.suggestion?.reason && x.heading === "UNSORTED").map((x) => x.key);

  return (
    <div className="border-t border-slate-200">
      <div className="flex flex-wrap items-center justify-between gap-2 px-4 py-3">
        <div className="flex items-center gap-2">
          <Landmark className="h-4 w-4 text-teal-700" />
          <p className={text.card}>From the bank statements</p>
          <span className="text-xs text-slate-500">{day(data.period.start)} to {day(data.period.end)} · {data.lines.length} lines</span>
          {toCheck > 0 && <span className={cn("rounded-full px-2 py-px text-[10.5px] font-bold", PILL.look)}>{toCheck} to check</span>}
        </div>
        <div className="flex gap-2">
          {unsorted > 0 && (
            <Button size="sm" variant="outline" className="h-8 text-xs" disabled={!!busy}
                    onClick={() => run("ai", async () => setData(await api.suggestSaTradeBank(jobId, businessId)))}>
              <Sparkles className="mr-1 h-3.5 w-3.5" /> {busy === "ai" ? "Asking…" : "Suggest headings"}
            </Button>
          )}
          <Button size="sm" className="h-8 text-xs" disabled={!!busy}
                  onClick={() => run("post", async () => { onPosted(await api.postSaTradeBank(jobId, businessId)); toast.success("Totals put into the business"); })}>
            <ArrowDownToLine className="mr-1 h-3.5 w-3.5" /> Use these totals
          </Button>
        </div>
      </div>

      {data.accounts.some((a) => a.checks.length) && (
        <div className="mx-4 mb-3 space-y-1 rounded-lg border border-amber-200 bg-amber-50 px-3 py-2">
          {data.accounts.flatMap((a) => a.checks.map((c) => (
            <p key={a.account + c} className="flex gap-1.5 text-xs text-amber-900"><AlertTriangle className="mt-px h-3.5 w-3.5 shrink-0" />{c}</p>
          )))}
        </div>
      )}

      {(data.mixed || []).length > 0 && (
        <div className="mx-4 mb-3 space-y-1.5 rounded-lg border border-slate-200 bg-slate-50 px-3 py-2">
          <p className="text-[11px] font-semibold text-slate-600">Private use (only the business share is allowed)</p>
          {(data.mixed || []).map((m) => (
            <MixedUse key={m.kind + String(m.business_pct)} m={m} onSave={async (pct) => {
              try { setData(await api.putSaPrivateUse(jobId, businessId, m.kind, pct)); }
              catch (e: any) { toast.error("Not saved", { description: e.message }); }
            }} />
          ))}
        </div>
      )}

      {/* Totals per heading: a click shows that heading's lines */}
      <div className="flex flex-wrap gap-1.5 px-4 pb-3">
        {[{ heading: "check", label: "To check", amount: null as number | null, lines: toCheck },
          ...data.totals.map((t) => ({ heading: t.heading, label: t.label, amount: t.amount as number | null, lines: t.lines })),
          { heading: "all", label: "All lines", amount: null, lines: data.lines.length }].map((t) => (
          <button key={t.heading} type="button" onClick={() => setShow(t.heading)}
                  className={cn("rounded-lg border px-2.5 py-1 text-left text-[11.5px] cursor-pointer",
                    show === t.heading ? "border-teal-600 bg-teal-50 text-teal-900" : "border-slate-200 bg-white text-slate-600 hover:bg-slate-50")}>
            <span className="font-medium">{t.label}</span>
            <span className="ml-1.5 text-slate-400">{t.lines}</span>
            {t.amount !== null && <span className={cn("ml-1.5 font-semibold text-slate-800", NUM)}>{money(t.amount)}</span>}
          </button>
        ))}
      </div>

      <div className="max-h-[28rem] overflow-y-auto border-t border-slate-100">
        <table className="w-full table-fixed text-xs">
          <thead className={cn(THEAD, "sticky top-0 z-10")}>
            <tr className="text-left">
              <th className="w-20 px-4 py-2 font-semibold">Date</th>
              <th className="px-3 py-2 font-semibold">Description</th>
              <th className="w-24 px-3 py-2 text-right font-semibold">In</th>
              <th className="w-24 px-3 py-2 text-right font-semibold">Out</th>
              <th className="w-60 px-3 py-2 font-semibold">Heading</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-slate-100">
            {lines.length === 0 && <tr><td colSpan={5} className="px-4 py-3 text-slate-500">Nothing here.</td></tr>}
            {lines.map((l) => (
              <tr key={l.key} className={cn(TROW, "align-top")}>
                <td className={cn("px-4 py-2 text-slate-600", NUM)}>{day(l.on)}</td>
                <td className="px-3 py-2">
                  <p className="truncate text-slate-800" title={l.description}>{l.description}</p>
                  <p className={cn("truncate text-[11px]", l.sure ? "text-slate-400" : "text-amber-700")} title={l.how}>{l.how}</p>
                  {l.suggestion && l.heading === "UNSORTED" && (
                    <p className="mt-0.5 flex items-center gap-1.5 text-[11px] text-sky-800">
                      <Sparkles className="h-3 w-3 shrink-0" />
                      {l.suggestion.heading === "UNSORTED" ? (
                        <span className="truncate" title={l.suggestion.reason}>Ask the client: {l.suggestion.reason}</span>
                      ) : <>
                        <span className="truncate" title={l.suggestion.reason}>{l.suggestion.label} ({l.suggestion.sure}): {l.suggestion.reason}</span>
                        <button type="button" className="shrink-0 font-semibold text-teal-700 hover:underline cursor-pointer"
                                onClick={() => choose(samePayee(l), l.suggestion!.heading)}>Use</button>
                      </>}
                    </p>
                  )}
                </td>
                <td className={cn("px-3 py-2 text-right", NUM, l.in ? "text-slate-900" : "text-slate-300")}>{l.in ? money(l.in) : "—"}</td>
                <td className={cn("px-3 py-2 text-right", NUM, l.out ? "text-slate-900" : "text-slate-300")}>{l.out ? money(l.out) : "—"}</td>
                <td className="px-3 py-1.5">
                  <div className="flex items-center gap-1">
                    <div className="min-w-0 flex-1">
                      <CustomSelect size="sm" fullWidth searchable value={l.heading} options={options}
                                    onChange={(v) => v !== l.heading && choose([l.key], v)} />
                    </div>
                    {l.chosen && (
                      <button type="button" title="Back to the rules" onClick={() => choose([l.key], null)}
                              className="shrink-0 rounded px-1 text-[11px] text-slate-400 hover:bg-slate-100 hover:text-slate-700 cursor-pointer">↺</button>
                    )}
                  </div>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
