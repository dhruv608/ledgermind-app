"use client";

import { Fragment, useState } from "react";
import type { AssetFigures } from "@/lib/api";
import { SkeletonRows } from "@/components/common/SkeletonRows";
import { EmptyState } from "@/components/common/EmptyState";
import { wp } from "@/components/review/area/WorkpaperParts";
import { jobKeys, useAssetRegister } from "@/lib/queries/job";
import { useQueryClient } from "@tanstack/react-query";
import { toast } from "@/lib/notify";
import { api } from "@/lib/api";
import { cn } from "@/lib/utils";

/**
 * The asset register asset by asset: date, description, cost, depreciation with this year's charge by the asset's
 * rate and method, NBV; a total per class.
 */
const { money, th, num } = wp;
const COLS: { key: keyof AssetFigures; label: string; strong?: boolean }[] = [
  { key: "cost_bf", label: "Cost b/f" },
  { key: "additions", label: "Additions" },
  { key: "disposals", label: "Disposals" },
  { key: "cost_cf", label: "Cost c/f", strong: true },
  { key: "dep_bf", label: "Depn b/f" },
  { key: "charge", label: "Charge" },
  { key: "dep_disposal", label: "Depn on disposal" },
  { key: "dep_cf", label: "Depn c/f", strong: true },
  { key: "nbv", label: "NBV", strong: true },
  { key: "nbv_bf", label: "NBV last year" },
];
const day = (iso: string | null) => (iso ? new Date(`${iso}T00:00:00`).toLocaleDateString("en-GB") : "-");

export function AssetRegister({ engagementId }: { engagementId: string }) {
  const q = useAssetRegister(engagementId);
  const qc = useQueryClient();
  const save = async (id: number, body: { residual_value: number | null; useful_life_years: number | null }) => {
    try {
      await api.saveAssetDetails(engagementId, id, body);
      await qc.invalidateQueries({ queryKey: jobKeys.assetRegister(engagementId) });
    } catch (e) {
      toast.error((e as Error).message);
    }
  };
  if (q.error) return <p className="text-[11px] text-rose-700">{(q.error as Error).message}</p>;
  if (!q.data) return <div className="rounded-xl border border-slate-200 bg-white p-4"><SkeletonRows rows={6} /></div>;
  const r = q.data;
  if (!r.classes.length) {
    return (
      <EmptyState art="upload" title="No asset register yet" description="Upload the client's register, or last year's final working paper, on Evidence." />
    );
  }
  const figures = (f: AssetFigures, strongRow = false) =>
    COLS.map((c) => <td key={c.key} className={cn(num, "py-1.5", (c.strong || strongRow) && "font-semibold text-slate-900", !f[c.key] && !strongRow && "text-slate-300")}>{money(f[c.key])}</td>);
  return (
    <div className="overflow-hidden rounded-xl border border-slate-200 bg-white shadow-2xs">
      <div className="border-b border-teal-100 bg-linear-to-r from-teal-50/70 to-white px-4 py-3">
        <h3 className="text-sm font-bold text-teal-900">Asset register</h3>
        <p className="text-[11px] text-slate-500">Each asset, with this year&apos;s charge worked out from its rate and method (straight line or reducing balance).</p>
      </div>
      <div className="max-h-[36rem] overflow-auto">
        <table className="w-full min-w-[80rem] text-xs">
          <thead className="sticky top-0 z-10 border-b border-teal-100 bg-teal-50 text-[10.5px] uppercase tracking-wide text-teal-800">
            <tr>
              <th className={cn(th, "w-24 pl-4 text-left")}>Date</th>
              <th className={cn(th, "text-left")}>Description</th>
              <th className={cn(th, "w-24 text-left")}>Rate</th>
              <th className={cn(th, "w-24 text-right")}>Residual value</th>
              <th className={cn(th, "w-20 text-right")}>Useful life</th>
              {COLS.map((c) => <th key={c.key} className={cn(th, "text-right")}>{c.label}</th>)}
            </tr>
          </thead>
          <tbody className="divide-y divide-slate-100">
            {r.classes.map((cls) => (
              <Fragment key={cls.name}>
                <tr><td colSpan={5 + COLS.length} className="bg-slate-50/70 px-4 py-1.5 text-[10.5px] font-semibold uppercase tracking-wide text-slate-500">{cls.name}</td></tr>
                {cls.assets.map((a) => (
                  <tr key={a.id}>
                    <td className="whitespace-nowrap py-1.5 pl-4 text-slate-500">{day(a.date)}</td>
                    <td className="max-w-80 truncate px-3 py-1.5 text-slate-800" title={a.description}>{a.description}</td>
                    <td className="whitespace-nowrap px-3 py-1.5 text-slate-500">{a.rate ? `${Math.round(a.rate * 1000) / 10}% ${a.method}` : "-"}</td>
                    <td className="px-2 py-1"><AssetNumber value={a.residual_value} label={`Residual value of ${a.description}`} onSave={(v) => save(a.id, { residual_value: v, useful_life_years: a.useful_life_years })} /></td>
                    <td className="px-2 py-1"><AssetNumber value={a.useful_life_years} label={`Useful life of ${a.description} (years)`} suffix="yrs" onSave={(v) => save(a.id, { residual_value: a.residual_value, useful_life_years: v })} /></td>
                    {figures(a)}
                  </tr>
                ))}
                <tr className="bg-teal-50/40">
                  <td className="py-1.5 pl-4 font-semibold text-teal-900" colSpan={5}>Total {cls.name}</td>
                  {figures(cls.total, true)}
                </tr>
              </Fragment>
            ))}
          </tbody>
          <tfoot className="sticky bottom-0 border-t-2 border-teal-200 bg-teal-50 font-bold text-teal-900">
            <tr><td className="py-2 pl-4" colSpan={5}>Total per register</td>{COLS.map((c) => <td key={c.key} className={num}>{money(r.total[c.key])}</td>)}</tr>
          </tfoot>
        </table>
      </div>
    </div>
  );
}

/** A number typed on the register row, saved when the box is left */
function AssetNumber({ value, label, suffix, onSave }: { value: number | null; label: string; suffix?: string; onSave: (v: number | null) => void }) {
  const [v, setV] = useState(value === null ? "" : String(value));
  return (
    <span className="inline-flex items-center gap-1">
      <input aria-label={label} type="number" step="any" value={v} onChange={(e) => setV(e.target.value)}
             onBlur={() => { const n = v === "" ? null : parseFloat(v); if (n !== value) onSave(Number.isNaN(n as number) ? null : n); }}
             className="h-6 w-full rounded border border-slate-200 bg-white px-1.5 text-right font-mono text-[11px] text-slate-700 focus:outline-none focus:ring-2 focus:ring-teal-200" />
      {suffix && <span className="text-[10px] text-slate-400">{suffix}</span>}
    </span>
  );
}
