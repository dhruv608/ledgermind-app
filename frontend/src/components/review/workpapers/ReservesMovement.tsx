"use client";

import type { ReservesYear } from "@/lib/api";
import { SkeletonRows } from "@/components/common/SkeletonRows";
import { wp } from "@/components/review/area/WorkpaperParts";
import { useReserves } from "@/lib/queries/job";
import { cn } from "@/lib/utils";

/**
 * Retained earnings: profit and loss account brought forward, the profit for the year, the dividends and carried
 * forward, this year beside last year.
 */
const { money, th, num } = wp;
const ROWS: { key: keyof ReservesYear; label: string; strong?: boolean; minus?: boolean }[] = [
  { key: "bf", label: "Profit and loss account brought forward" },
  { key: "profit", label: "Profit / (loss) for the year" },
  { key: "dividends", label: "Dividends during the year", minus: true },
  { key: "cf", label: "Carried forward", strong: true },
];

export function ReservesMovement({ engagementId }: { engagementId: string }) {
  const q = useReserves(engagementId);
  if (q.error) return <p className="text-[11px] text-rose-700">{(q.error as Error).message}</p>;
  if (!q.data) return <div className="rounded-xl border border-slate-200 bg-white p-4"><SkeletonRows rows={4} /></div>;
  const { this_year: cy, last_year: ly, difference } = q.data;
  const show = (y: ReservesYear | null, r: (typeof ROWS)[number]) => (y === null ? "-" : money(r.minus ? -y[r.key] : y[r.key]));
  return (
    <div className="overflow-hidden rounded-xl border border-slate-200 bg-white shadow-2xs">
      <div className="border-b border-teal-100 bg-linear-to-r from-teal-50/70 to-white px-4 py-3">
        <h3 className="text-sm font-bold text-teal-900">Reserves</h3>
        <p className="text-[11px] text-slate-500">
          Retained earnings this year and last.
          {difference !== null && Math.abs(difference) >= 1 && <span className="text-rose-700"> Brought forward differs from last year&apos;s carried forward by {money(difference)}.</span>}
        </p>
      </div>
      <table className="w-full table-fixed text-xs">
        <thead className="border-b border-teal-100 bg-teal-50/80 text-[10.5px] uppercase tracking-wide text-teal-800">
          <tr>
            <th className={cn(th, "pl-4 text-left")}>Retained earnings</th>
            <th className={cn(th, "w-36 text-right")}>Current year</th>
            <th className={cn(th, "w-36 pr-4 text-right")}>Previous year</th>
          </tr>
        </thead>
        <tbody className="divide-y divide-slate-100">
          {ROWS.map((r) => (
            <tr key={r.key} className={cn(r.strong && "border-t-2 border-teal-200 bg-teal-50/70 font-bold text-teal-900")}>
              <td className="py-2 pl-4 pr-3">{r.label}</td>
              <td className={cn(num, r.strong && "font-bold")}>{show(cy, r)}</td>
              <td className={cn(num, "pr-4 text-slate-500", r.strong && "font-bold text-teal-900")}>{show(ly, r)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
