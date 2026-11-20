"use client";

import { useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { Loader2, Paperclip, Plus, Trash2 } from "lucide-react";
import { toast } from "@/lib/notify";
import type { StockLine, StockLines } from "@/lib/api";
import { api } from "@/lib/api";
import { SkeletonRows } from "@/components/common/SkeletonRows";
import { Button } from "@/components/ui/button";
import { CustomSelect } from "@/components/ui/custom-select";
import { wp } from "@/components/review/area/WorkpaperParts";
import { jobKeys, useStockLines } from "@/lib/queries/job";
import { cn } from "@/lib/utils";

/**
 * The closing stock line by line: stock type, description, amount, impairment, the net figure and last year; who
 * verified the count (us or the client) with its document; the total against the books.
 */
const { money, th, num } = wp;
const TYPES = ["Materials", "Finished goods", "Work in progress", "Goods for resale"].map((t) => ({ value: t, label: t }));
const blank = (): StockLine => ({ code: 4300, stock_type: "Finished goods", description: "", amount: 0, impairment: 0, last_year: null, note: "" });
const field = "w-full rounded-md border border-slate-300 bg-white px-2 py-1 text-xs text-slate-800 focus:outline-none focus:ring-2 focus:ring-teal-200";

export function StockLinesPanel({ engagementId, onAttach }: { engagementId: string; onAttach: () => void }) {
  const qc = useQueryClient();
  const q = useStockLines(engagementId);
  const [lines, setLines] = useState<StockLine[]>([]);
  const [verified, setVerified] = useState<StockLines["verified_by"]>("");
  const [saving, setSaving] = useState(false);
  // New figures from the server replace the edits (set during render, as React does for state following a prop)
  const [syncedFrom, setSyncedFrom] = useState<StockLines | undefined>(undefined);
  if (q.data !== syncedFrom) {
    setSyncedFrom(q.data);
    if (q.data) { setLines(q.data.lines); setVerified(q.data.verified_by); }
  }
  if (q.error) return <p className="text-[11px] text-rose-700">{(q.error as Error).message}</p>;
  if (!q.data) return <div className="rounded-xl border border-slate-200 bg-white p-4"><SkeletonRows rows={3} /></div>;
  const dirty = JSON.stringify(lines) !== JSON.stringify(q.data.lines) || verified !== q.data.verified_by;
  const total = lines.reduce((s, l) => s + (l.amount || 0) - (l.impairment || 0), 0);
  const diff = lines.length ? q.data.books - total : null;
  const change = (i: number, patch: Partial<StockLine>) => setLines(lines.map((l, j) => (j === i ? { ...l, ...patch } : l)));
  const save = async () => {
    setSaving(true);
    try {
      qc.setQueryData(jobKeys.stockLines(engagementId), await api.saveStockLines(engagementId, lines, verified));
      toast.success("Stock lines saved");
    } catch (e) {
      toast.error((e as Error).message);
    } finally {
      setSaving(false);
    }
  };
  return (
    <div className="overflow-hidden rounded-xl border border-slate-200 bg-white shadow-2xs">
      <div className="flex flex-wrap items-end justify-between gap-3 border-b border-teal-100 bg-linear-to-r from-teal-50/70 to-white px-4 py-3">
        <div>
          <h3 className="text-sm font-bold text-teal-900">Closing stock, line by line</h3>
          <p className="text-[11px] text-slate-500">
            Each stock line at the year end, less any impairment. The books hold {money(q.data.books)}
            {diff !== null && (Math.abs(diff) >= 0.005 ? <span className="text-rose-700">: {money(diff)} more than the lines</span> : ": the lines agree")}.
          </p>
        </div>
        <Button variant="primary" size="sm" className="h-8 text-xs" disabled={!dirty || saving} onClick={save}>
          {saving && <Loader2 className="mr-1.5 h-3.5 w-3.5 animate-spin" />} Save
        </Button>
      </div>
      <table className="w-full table-fixed text-xs">
        {lines.length > 0 && (
          <thead className="border-b border-teal-100 bg-teal-50/80 text-[10.5px] uppercase tracking-wide text-teal-800">
            <tr>
              <th className={cn(th, "w-40 pl-4 text-left")}>Stock type</th>
              <th className={cn(th, "text-left")}>Description</th>
              <th className={cn(th, "w-28 text-right")}>Amount</th>
              <th className={cn(th, "w-28 text-right")}>Impairment</th>
              <th className={cn(th, "w-28 text-right")}>Total</th>
              <th className={cn(th, "w-28 text-right")}>Last year</th>
              <th className="w-10" />
            </tr>
          </thead>
        )}
        <tbody className="divide-y divide-slate-100">
          {lines.map((l, i) => (
            <tr key={i}>
              <td className="py-1 pl-4 pr-2"><CustomSelect fullWidth size="sm" value={l.stock_type} options={TYPES} onChange={(v) => change(i, { stock_type: String(v) })} /></td>
              <td className="px-2 py-1"><input aria-label="Description" value={l.description} placeholder="e.g. Shop stock at cost" className={field} onChange={(e) => change(i, { description: e.target.value })} /></td>
              <td className="px-2 py-1"><input aria-label="Amount" type="number" step="any" value={l.amount || ""} className={cn(field, "text-right")} onChange={(e) => change(i, { amount: parseFloat(e.target.value) || 0 })} /></td>
              <td className="px-2 py-1"><input aria-label="Impairment" type="number" step="any" value={l.impairment || ""} className={cn(field, "text-right")} onChange={(e) => change(i, { impairment: parseFloat(e.target.value) || 0 })} /></td>
              <td className={cn(num, "font-semibold")}>{money((l.amount || 0) - (l.impairment || 0))}</td>
              <td className="px-2 py-1"><input aria-label="Last year" type="number" step="any" value={l.last_year ?? ""} className={cn(field, "text-right")} onChange={(e) => change(i, { last_year: e.target.value === "" ? null : parseFloat(e.target.value) })} /></td>
              <td className="pr-3 text-right">
                <button type="button" aria-label="Remove the line" onClick={() => setLines(lines.filter((_, j) => j !== i))}
                        className="rounded p-1 text-slate-400 hover:bg-rose-50 hover:text-rose-600"><Trash2 className="h-3.5 w-3.5" /></button>
              </td>
            </tr>
          ))}
        </tbody>
        {lines.length > 0 && (
          <tfoot className="border-t-2 border-teal-200 bg-teal-50/70 font-bold text-teal-900">
            <tr><td className="py-2 pl-4" colSpan={4}>Total</td><td className={num}>{money(total)}</td>
              <td className={num}>{money(lines.reduce((s, l) => s + (l.last_year ?? 0), 0))}</td><td /></tr>
          </tfoot>
        )}
      </table>
      <div className="flex flex-wrap items-center justify-between gap-3 border-t border-slate-100 px-4 py-2.5">
        <button type="button" onClick={() => setLines([...lines, blank()])}
                className="inline-flex items-center gap-1 text-[11px] font-medium text-teal-700 hover:underline">
          <Plus className="h-3.5 w-3.5" /> Add a stock line
        </button>
        <div className="flex items-center gap-2 text-[11px] text-slate-600">
          Count verified by
          <div className="flex rounded-md border border-slate-200 bg-white p-0.5">
            {([["US", "Us"], ["CLIENT", "The client"], ["", "Not yet"]] as [StockLines["verified_by"], string][]).map(([v, label]) => (
              <button key={label} type="button" onClick={() => setVerified(v)}
                      className={cn("rounded px-2 py-0.5 font-medium", verified === v ? "bg-teal-50 text-teal-800" : "text-slate-500 hover:text-slate-800")}>
                {label}
              </button>
            ))}
          </div>
          <Button variant="outline" size="sm" className="h-7 text-[11px]" onClick={onAttach}><Paperclip className="mr-1 h-3 w-3" /> Attach the count</Button>
        </div>
      </div>
    </div>
  );
}
