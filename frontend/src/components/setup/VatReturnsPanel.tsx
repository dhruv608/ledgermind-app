"use client";

import { Fragment, useCallback, useEffect, useRef, useState } from "react";
import { AlertCircle, CalendarPlus, CheckCircle2, ChevronDown, Loader2, Plus, Receipt, Trash2, Upload } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { SectionHeader } from "@/components/ui/section-header";
import { toast } from "@/lib/notify";
import { api } from "@/lib/api";
import { formatCurrency, formatDate } from "@/lib/formatters";
import { cn } from "@/lib/utils";
import { VAT100Record, VatReturnInput } from "@/types/engagement";
import { SkeletonRows } from "@/components/common/SkeletonRows";

interface VatReturnsPanelProps {
  engagementId: string;
  periodEndDate: string; // the client's year end, dd/mm/yyyy or yyyy-mm-dd
  onSaved?: () => void;
}

type BoxKey = "box1" | "box2" | "box4" | "box6" | "box7" | "box8" | "box9";

interface ReturnDraft {
  id: number;             // the row's key on screen
  period_end: string;
  box1: string;
  box2: string;
  box4: string;
  box6: string;
  box7: string;
  box8: string;
  box9: string;
  bfwd_outstanding: string;
}

// The EU boxes (2, 8, 9) are nearly always 0 since 2021: under a small link on each row
const EU_BOXES: { key: BoxKey; label: string }[] = [
  { key: "box2", label: "Box 2: VAT on goods from the EU" },
  { key: "box8", label: "Box 8: goods sold to the EU" },
  { key: "box9", label: "Box 9: goods bought from the EU" },
];

let nextId = 1;
const emptyDraft = (period_end = ""): ReturnDraft => ({
  id: nextId++, period_end, box1: "", box2: "", box4: "", box6: "", box7: "", box8: "", box9: "", bfwd_outstanding: "",
});

const num = (v: string): number => parseFloat(v.replace(/[£,\s]/g, "")) || 0;
const show = (v: number | null | undefined): string => (v ? String(v) : "");
const money = (v: number) => formatCurrency(v);

const fromRecord = (r: VAT100Record): ReturnDraft => ({
  id: nextId++,
  period_end: r.period_end ?? "",
  box1: show(r.box1_vat_due_sales),
  box2: show(r.box2_vat_due_acquisitions),
  box4: show(r.box4_vat_reclaimed),
  box6: show(r.box6_total_sales_ex_vat),
  box7: show(r.box7_total_purchases_ex_vat),
  box8: show(r.box8_supplies_to_eu),
  box9: show(r.box9_acquisitions_from_eu),
  bfwd_outstanding: r.bfwd_outstanding == null ? "" : String(r.bfwd_outstanding),
});

/** The engagement's year end arrives as dd/mm/yyyy (or ISO); compare dates as yyyy-mm-dd. */
const toIsoDate = (value: string): string => {
  const uk = value.match(/^(\d{1,2})\/(\d{1,2})\/(\d{4})$/);
  return uk ? `${uk[3]}-${uk[2].padStart(2, "0")}-${uk[1].padStart(2, "0")}` : value.slice(0, 10);
};

/** A date so many months on (back when negative); a month end stays a month end (30 Jun + 3 = 30 Sep). */
const addMonths = (iso: string, months: number): string => {
  const [y, m, d] = iso.split("-").map(Number);
  const lastDay = (yy: number, mm: number) => new Date(yy, mm, 0).getDate();
  const total = y * 12 + (m - 1) + months;
  const ny = Math.floor(total / 12);
  const nm = (total % 12) + 1;
  const day = d === lastDay(y, m) ? lastDay(ny, nm) : Math.min(d, lastDay(ny, nm));
  return `${ny}-${String(nm).padStart(2, "0")}-${String(day).padStart(2, "0")}`;
};

type Paid = Record<string, { owed: number; paid: number | null; unpaid: number | null }>;

export function VatReturnsPanel({ engagementId, periodEndDate, onSaved }: VatReturnsPanelProps) {
  const [rows, setRows] = useState<ReturnDraft[]>([]);
  const [loading, setLoading] = useState(true);
  const [state, setState] = useState<"saved" | "saving" | "dirty">("saved");
  const [paid, setPaid] = useState<Paid>({});
  const [paidSource, setPaidSource] = useState<string>("");
  // Last year's return picked from the payments by the app (not typed): the summary's first line
  const [opening, setOpening] = useState<{ period_end: string; owed: number; paid: number | null; unpaid: number | null; note?: string } | null>(null);
  const [euOpen, setEuOpen] = useState<Set<number>>(new Set());
  const rowsRef = useRef<ReturnDraft[]>([]);
  useEffect(() => { rowsRef.current = rows; }, [rows]);
  const saving = useRef<Promise<void>>(Promise.resolve());

  const yearEnd = toIsoDate(periodEndDate);
  const lastYearEnd = addMonths(yearEnd, -12);

  const loadPaid = useCallback(() => {
    api
      .getVatReturnsPaid(engagementId)
      .then((p) => {
        setPaidSource(p.source);
        setOpening(p.returns.find((r) => r.opening) || null);
        setPaid(Object.fromEntries(p.returns.filter((r) => !r.opening).map((r) => [r.period_end, { owed: r.owed, paid: r.paid, unpaid: r.unpaid }])));
      })
      .catch(() => { setPaid({}); setOpening(null); });
  }, [engagementId]);

  useEffect(() => {
    api
      .getVatReturns(engagementId)
      .then((records) => setRows(records.map(fromRecord)))
      .catch((err) => toast.error("VAT returns not loaded", { description: err.message }))
      .finally(() => setLoading(false));
    loadPaid();
  }, [engagementId, loadPaid]);

  const isLastYear = (r: ReturnDraft) => !!r.period_end && r.period_end <= lastYearEnd;
  const netVat = (r: ReturnDraft) => num(r.box1) + num(r.box2) - num(r.box4);

  const problemsOf = (list: ReturnDraft[]): string[] => {
    const out: string[] = [];
    if (list.some((r) => !r.period_end)) out.push("Type the period end date of every return");
    const ends = list.map((r) => r.period_end).filter(Boolean);
    if (new Set(ends).size !== ends.length) out.push("Two returns have the same period end date");
    if (list.some((r) => r.period_end > yearEnd)) out.push("A return ends after the year end: it belongs to next year");
    return out;
  };
  const problems = problemsOf(rows);

  // Saved as soon as a box is left (one save at a time, the latest figures each time); nothing to press
  const save = () => {
    saving.current = saving.current.then(async () => {
      const list = rowsRef.current;
      if (problemsOf(list).length) return;
      setState("saving");
      try {
        const payload: VatReturnInput[] = list.map((r) => ({
          period_end: r.period_end,
          box1: num(r.box1), box2: num(r.box2), box4: num(r.box4), box6: num(r.box6),
          box7: num(r.box7), box8: num(r.box8), box9: num(r.box9),
          bfwd_outstanding: isLastYear(r) && r.bfwd_outstanding.trim() ? num(r.bfwd_outstanding) : null,
        }));
        await api.saveVatReturns(engagementId, payload);
        setState(rowsRef.current === list ? "saved" : "dirty");
        loadPaid();
        onSaved?.();
      } catch (err: any) {
        setState("dirty");
        toast.error("VAT returns not saved", { description: err.message });
      }
    });
  };

  const update = (id: number, field: keyof ReturnDraft, value: string) => {
    setRows((prev) => prev.map((r) => (r.id === id ? { ...r, [field]: value } : r)));
    setState("dirty");
  };
  const change = (next: ReturnDraft[]) => {
    rowsRef.current = next;
    setRows(next);
    setState("dirty");
    save();
  };

  // The year's returns: quarters stepped from a return already typed (VAT quarters need not end with the year),
  // else ending with the year end; only the ones not there yet are added
  const addYearQuarters = () => {
    const anchor = rows.find((r) => r.period_end && !isLastYear(r))?.period_end || yearEnd;
    const ends = new Set<string>();
    for (let k = -8; k <= 8; k++) {
      const e = addMonths(anchor, 3 * k);
      if (e > lastYearEnd && e <= yearEnd) ends.add(e);
    }
    const have = new Set(rows.map((r) => r.period_end));
    const added = [...ends].filter((e) => !have.has(e)).map((e) => emptyDraft(e));
    if (!added.length) {
      toast.message("Every quarter of the year is already there");
      return;
    }
    change([...rows, ...added].sort((a, b) => (a.period_end || "9999").localeCompare(b.period_end || "9999")));
  };
  const addReturn = () => {
    const last = [...rows].filter((r) => r.period_end).sort((a, b) => a.period_end.localeCompare(b.period_end)).pop();
    const next = last ? addMonths(last.period_end, 3) : "";
    const row = emptyDraft(next && next <= yearEnd ? next : "");
    rowsRef.current = [...rows, row];
    setRows(rowsRef.current);
    setState("dirty");
  };

  // The client's VAT summary (a row per return: output, input, due, paid, date, sales): read into the returns
  const [importing, setImporting] = useState(false);
  const handleSummary = async (file: File) => {
    setImporting(true);
    try {
      const res = await api.uploadSupplementaryDocuments(engagementId, [file], "VAT_100");
      const records = await api.getVatReturns(engagementId);
      setRows(records.map(fromRecord));
      setState("saved");
      loadPaid();
      onSaved?.();
      (res?.warnings || []).forEach((w: string) => toast.warning(w, { duration: 12000 }));
      const read = res?.uploaded_documents?.[0]?.parsed_records_count ?? records.length;
      if (read) {
        toast.success(`${read} VAT return(s) read from ${file.name}`, {
          description: "They replace the returns entered before.",
        });
      } else {
        toast.error("No VAT returns found in this file", {
          description: "Expected a row per return with Output and Input columns, or type the returns below.",
        });
      }
    } catch (err: any) {
      toast.error("VAT summary not read", { description: err.message });
    } finally {
      setImporting(false);
    }
  };

  const ordered = [...rows].sort((a, b) => (a.period_end || "9999").localeCompare(b.period_end || "9999"));
  const thisYear = rows.filter((r) => r.period_end && !isLastYear(r) && r.period_end <= yearEnd);
  const sum = (f: (r: ReturnDraft) => number) => thisYear.reduce((s, r) => s + f(r), 0);
  const paidKnown = paidSource !== "" && state === "saved";
  const unpaidTotal = Object.entries(paid).reduce((s, [, p]) => s + (p.unpaid || 0), 0);

  const input = "w-full min-w-[84px] rounded border border-slate-200 bg-white px-2 py-1 text-right font-mono text-xs focus:outline-none focus:ring-2 focus:ring-teal-200";
  const th = "whitespace-nowrap px-2 py-2 text-right font-semibold";
  const box = (r: ReturnDraft, key: BoxKey) => (
    <input
      inputMode="decimal"
      value={r[key]}
      placeholder="0.00"
      onChange={(e) => update(r.id, key, e.target.value)}
      onBlur={() => state === "dirty" && save()}
      className={input}
    />
  );

  return (
    <Card className="overflow-hidden">
      <SectionHeader
        icon={Receipt}
        title="VAT returns"
        description="Upload the client's VAT summary, or type the boxes from each return. Saved as you type."
        className="border-b border-slate-100 p-5"
        actions={
          <>
            <label
              className={cn(
                "inline-flex h-8 cursor-pointer items-center rounded-lg border border-slate-200 bg-white px-3 text-xs font-medium text-slate-700 hover:bg-slate-50",
                importing && "pointer-events-none opacity-60",
              )}
            >
              <Upload className="mr-1 h-3.5 w-3.5" /> {importing ? "Reading…" : "Upload VAT summary"}
              <input
                type="file"
                accept=".xlsx,.xls,.csv"
                className="hidden"
                onChange={(e) => {
                  const f = e.target.files?.[0];
                  e.target.value = "";
                  if (f) handleSummary(f);
                }}
              />
            </label>
            <Button variant="outline" size="sm" onClick={addYearQuarters} title="Adds a row for each quarter of the year, dates filled in">
              <CalendarPlus className="mr-1 h-3.5 w-3.5" /> Add the year&apos;s quarters
            </Button>
          </>
        }
      />

      {loading ? (
        <SkeletonRows rows={4} columns={4} label="Loading VAT returns" />
      ) : rows.length === 0 ? (
        <div className="flex flex-col items-center gap-2 p-10 text-center">
          <Receipt className="h-6 w-6 text-slate-300" />
          <p className="text-xs font-medium text-slate-700">No VAT returns yet</p>
          <p className="max-w-sm text-xs text-slate-500">
            Upload the client&apos;s VAT summary, or click Add the year&apos;s quarters and type the boxes from each return.
          </p>
        </div>
      ) : (
        <div className="overflow-x-auto">
          <table className="w-full text-xs">
            <thead className="border-b border-slate-200 bg-slate-50 text-[11px] uppercase tracking-wide text-slate-500">
              <tr>
                <th className="whitespace-nowrap px-2 py-2 pl-5 text-left font-semibold">Period end</th>
                <th className={th}>VAT on sales<span className="block font-normal normal-case text-slate-400">Box 1</span></th>
                <th className={th}>VAT reclaimed<span className="block font-normal normal-case text-slate-400">Box 4</span></th>
                <th className={th}>Net VAT<span className="block font-normal normal-case text-slate-400">Box 5</span></th>
                <th className={th}>Sales<span className="block font-normal normal-case text-slate-400">Box 6</span></th>
                <th className={th}>Purchases<span className="block font-normal normal-case text-slate-400">Box 7</span></th>
                <th className={th}>
                  Paid
                  <span className="block font-normal normal-case text-slate-400">
                    {paidSource === "summary" ? "per VAT summary" : paidSource ? "per ledger" : ""}
                  </span>
                </th>
                <th className={th}>Unpaid</th>
                <th className="w-16 px-2 pr-4" />
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-100">
              {opening && (
                <tr className="bg-slate-50 align-middle" title={opening.note}>
                  <td className="whitespace-nowrap py-2 pl-5 pr-2">
                    <span className="text-xs text-slate-700">{formatDate(opening.period_end, "short")}</span>
                    <span className="ml-1.5 rounded-full bg-slate-200 px-1.5 py-0.5 text-[10px] font-medium text-slate-600">Opening</span>
                  </td>
                  <td colSpan={2} className="px-2 py-2 text-[11px] text-slate-500">{opening.note}</td>
                  <td className="whitespace-nowrap px-2 py-2 text-right font-mono font-semibold text-slate-900">{money(opening.owed)}</td>
                  <td colSpan={2} />
                  <td className="whitespace-nowrap px-2 py-2 text-right font-mono text-slate-600">{opening.paid !== null ? money(opening.paid) : "-"}</td>
                  <td className="whitespace-nowrap px-2 py-2 text-right font-mono">
                    {opening.unpaid !== null && Math.abs(opening.unpaid) >= 0.01
                      ? <span className="font-semibold text-amber-700">{money(opening.unpaid)}</span>
                      : <span className="text-emerald-700">Paid</span>}
                  </td>
                  <td />
                </tr>
              )}
              {ordered.map((r) => {
                const lastYear = isLastYear(r);
                const p = r.period_end ? paid[r.period_end] : undefined;
                const euShown = euOpen.has(r.id) || EU_BOXES.some((b) => num(r[b.key]) !== 0);
                return (
                  <Fragment key={r.id}>
                    <tr className={cn("align-middle", lastYear && "bg-slate-50")}>
                      <td className="whitespace-nowrap py-1.5 pl-5 pr-2">
                        <input
                          type="date"
                          value={r.period_end}
                          max={yearEnd}
                          onChange={(e) => update(r.id, "period_end", e.target.value)}
                          onBlur={() => state === "dirty" && save()}
                          className={cn(
                            "rounded border px-1.5 py-1 text-xs focus:outline-none focus:ring-2 focus:ring-teal-200",
                            r.period_end ? "border-slate-200" : "border-amber-300 bg-amber-50/40",
                          )}
                        />
                        {lastYear && <span className="ml-1.5 rounded-full bg-slate-200 px-1.5 py-0.5 text-[10px] font-medium text-slate-600">Last year</span>}
                      </td>
                      <td className="px-2 py-1.5">{box(r, "box1")}</td>
                      <td className="px-2 py-1.5">{box(r, "box4")}</td>
                      <td className="whitespace-nowrap px-2 py-1.5 text-right font-mono font-semibold text-slate-900">{money(netVat(r))}</td>
                      <td className="px-2 py-1.5">{box(r, "box6")}</td>
                      <td className="px-2 py-1.5">{box(r, "box7")}</td>
                      <td className="whitespace-nowrap px-2 py-1.5 text-right font-mono text-slate-600">
                        {paidKnown && p && p.paid !== null ? money(p.paid) : "-"}
                      </td>
                      <td className="whitespace-nowrap px-2 py-1.5 text-right font-mono">
                        {lastYear ? (
                          <input
                            inputMode="decimal"
                            value={r.bfwd_outstanding}
                            placeholder={money(netVat(r))}
                            title="Still unpaid at the start of this year"
                            onChange={(e) => update(r.id, "bfwd_outstanding", e.target.value)}
                            onBlur={() => state === "dirty" && save()}
                            className={input}
                          />
                        ) : paidKnown && p && p.unpaid !== null && (Math.abs(p.owed) >= 0.01 || Math.abs(p.paid || 0) >= 0.01) ? (
                          <span className={cn(Math.abs(p.unpaid) >= 0.01 ? "font-semibold text-amber-700" : "text-emerald-700")}>
                            {Math.abs(p.unpaid) >= 0.01 ? money(p.unpaid) : "Paid"}
                          </span>
                        ) : (
                          "-"
                        )}
                      </td>
                      <td className="whitespace-nowrap px-2 py-1.5 pr-4 text-right">
                        <button
                          type="button"
                          onClick={() => setEuOpen((prev) => {
                            const n = new Set(prev);
                            if (n.has(r.id)) n.delete(r.id); else n.add(r.id);
                            return n;
                          })}
                          className="mr-1 rounded p-1 text-slate-400 hover:bg-slate-100 hover:text-slate-700"
                          title="EU boxes (2, 8, 9), usually 0"
                        >
                          <ChevronDown className={cn("h-3.5 w-3.5 transition", euShown && "rotate-180")} />
                        </button>
                        <button
                          type="button"
                          onClick={() => change(rows.filter((x) => x.id !== r.id))}
                          className="rounded p-1 text-slate-400 hover:bg-rose-50 hover:text-rose-600"
                          title="Remove this return"
                        >
                          <Trash2 className="h-3.5 w-3.5" />
                        </button>
                      </td>
                    </tr>
                    {euShown && (
                      <tr className={cn(lastYear && "bg-slate-50")}>
                        <td />
                        <td colSpan={8} className="px-2 pb-2">
                          <div className="flex flex-wrap gap-3">
                            {EU_BOXES.map((b) => (
                              <label key={b.key} className="w-44">
                                <span className="block text-[10px] text-slate-500">{b.label}</span>
                                {box(r, b.key)}
                              </label>
                            ))}
                          </div>
                        </td>
                      </tr>
                    )}
                  </Fragment>
                );
              })}
            </tbody>
            <tfoot className="border-t-2 border-slate-200 bg-slate-50 font-semibold text-slate-900">
              <tr>
                <td className="whitespace-nowrap py-2 pl-5 pr-2">This year ({thisYear.length})</td>
                <td className="whitespace-nowrap px-2 text-right font-mono">{money(sum((r) => num(r.box1)))}</td>
                <td className="whitespace-nowrap px-2 text-right font-mono">{money(sum((r) => num(r.box4)))}</td>
                <td className="whitespace-nowrap px-2 text-right font-mono">{money(sum(netVat))}</td>
                <td className="whitespace-nowrap px-2 text-right font-mono">{money(sum((r) => num(r.box6)))}</td>
                <td className="whitespace-nowrap px-2 text-right font-mono">{money(sum((r) => num(r.box7)))}</td>
                <td />
                <td className={cn("whitespace-nowrap px-2 text-right font-mono", paidKnown && unpaidTotal >= 0.01 && "text-amber-700")}>
                  {paidKnown ? money(unpaidTotal) : "-"}
                </td>
                <td />
              </tr>
            </tfoot>
          </table>
        </div>
      )}

      <div className="flex flex-wrap items-center justify-between gap-2 border-t border-slate-100 px-5 py-2.5 text-xs">
        <Button variant="ghost" size="sm" className="h-7 text-xs" onClick={addReturn}>
          <Plus className="mr-1 h-3.5 w-3.5" /> Add one return
        </Button>
        {problems.length > 0 ? (
          <span className="inline-flex items-center gap-1 text-amber-700">
            <AlertCircle className="h-3.5 w-3.5" /> {problems[0]}
          </span>
        ) : state === "saving" ? (
          <span className="inline-flex items-center gap-1 text-slate-500">
            <Loader2 className="h-3.5 w-3.5 animate-spin" /> Saving…
          </span>
        ) : state === "saved" && rows.length > 0 ? (
          <span className="inline-flex items-center gap-1 text-emerald-700">
            <CheckCircle2 className="h-3.5 w-3.5" /> Saved
            {!paidSource && " · no VAT payments found in the ledger to match"}
          </span>
        ) : null}
      </div>
    </Card>
  );
}
