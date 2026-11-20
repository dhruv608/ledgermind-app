"use client";

import type { FixedAssetFigures, FixedAssetSchedule as Schedule } from "@/lib/api";
import { SkeletonRows } from "@/components/common/SkeletonRows";
import { wp } from "@/components/review/area/WorkpaperParts";
import { useFixedAssetSchedule } from "@/lib/queries/job";
import { cn } from "@/lib/utils";

/**
 * The fixed asset schedule (tangible and intangible assets): one column per asset class and a total, rows from
 * cost b/f to NBV, as the fixed assets note in the accounts.
 */
const { money, th, num } = wp;
type Row = { key: keyof FixedAssetFigures; label: string; strong?: boolean; gap?: boolean };
const rows = (word: "Depreciation" | "Amortisation"): Row[] => [
  { key: "cost_bf", label: "Cost b/f" },
  { key: "additions", label: "Additions" },
  { key: "disposals", label: "Disposals" },
  { key: "cost_cf", label: "Cost c/f", strong: true },
  { key: "dep_bf", label: `${word} b/f`, gap: true },
  { key: "charge", label: "Charge for the year" },
  { key: "elimination", label: "Elimination on disposals" },
  { key: "dep_cf", label: `${word} c/f`, strong: true },
  { key: "nbv", label: "NBV this year", strong: true, gap: true },
  { key: "nbv_bf", label: "NBV last year" },
];

export function FixedAssetSchedule({ engagementId }: { engagementId: string }) {
  const q = useFixedAssetSchedule(engagementId);
  if (q.error) return <p className="text-[11px] text-rose-700">{(q.error as Error).message}</p>;
  if (!q.data) return <div className="rounded-xl border border-slate-200 bg-white p-4"><SkeletonRows rows={6} /></div>;
  const s: Schedule = q.data;
  if (!s.tangible.classes.length && !s.intangible.classes.length) return null;
  const from = s.opening_source ? `B/f from ${s.opening_source}.` : "B/f from the b/fwd accounts in the trial balance.";
  return (
    <div className="space-y-4">
      {s.tangible.classes.length > 0 && <Grid title="Tangible fixed assets" word="Depreciation" part={s.tangible} from={from} />}
      {s.intangible.classes.length > 0 && <Grid title="Intangible assets" word="Amortisation" part={s.intangible} from={from} />}
    </div>
  );
}

function Grid({ title, word, part, from }: { title: string; word: "Depreciation" | "Amortisation"; part: Schedule["tangible"]; from: string }) {
  const many = part.classes.length > 1;
  return (
    <div className="overflow-hidden rounded-xl border border-slate-200 bg-white shadow-2xs">
      <div className="border-b border-teal-100 bg-linear-to-r from-teal-50/70 to-white px-4 py-3">
        <h3 className="text-sm font-bold text-teal-900">{title}</h3>
        <p className="text-[11px] text-slate-500">Each class&apos;s cost and {word.toLowerCase()} for the year, as the fixed assets note. {from} This year&apos;s figures include the journals approved in the app.</p>
      </div>
      <div className="overflow-x-auto">
        <table className="w-full text-xs">
          <thead className="border-b border-teal-100 bg-teal-50/80 text-[10.5px] uppercase tracking-wide text-teal-800">
            <tr>
              <th className={cn(th, "w-48 pl-4 text-left")}>Description</th>
              {part.classes.map((c) => (
                <th key={c.name} className={cn(th, "min-w-28 text-right")} title={`Codes ${c.codes.join(", ")}`}>{c.name}</th>
              ))}
              {many && <th className={cn(th, "min-w-28 pr-4 text-right")}>Total</th>}
            </tr>
          </thead>
          <tbody>
            {rows(word).map((r) => (
              <tr key={r.key} className={cn(r.gap && "border-t-8 border-white", r.strong && "bg-slate-50/70 font-semibold text-slate-900")}>
                <td className={cn("py-1.5 pl-4 pr-3", r.strong ? "text-slate-900" : "text-slate-700")}>{r.label}</td>
                {part.classes.map((c) => (
                  <td key={c.name} className={cn(num, "py-1.5", !r.strong && c[r.key] === 0 && "text-slate-300")}>{money(c[r.key])}</td>
                ))}
                {many && <td className={cn(num, "py-1.5 pr-4 font-semibold")}>{money(part.total[r.key])}</td>}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
