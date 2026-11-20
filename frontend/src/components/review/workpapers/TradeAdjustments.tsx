"use client";

import { useState } from "react";
import { ChevronDown, ChevronRight } from "lucide-react";
import type { TradeAdjustment } from "@/lib/api";
import { AskLedge } from "@/components/assistant/AskLedge";
import { SkeletonRows } from "@/components/common/SkeletonRows";
import { wp } from "@/components/review/area/WorkpaperParts";
import { useTradeAdjustments } from "@/lib/queries/job";
import { cn } from "@/lib/utils";

/**
 * The Adjustments block under the trade debtors / creditors T: duplicates, receipts or payments recorded directly
 * while the invoice or bill is open, cash sales or payments, and the opening variance. Each line opens to its items.
 */
const { money, th, num } = wp;

export function TradeAdjustments({ engagementId, side }: { engagementId: string; side: "customer" | "supplier" }) {
  const q = useTradeAdjustments(engagementId, side);
  if (q.error) return <p className="text-[11px] text-rose-700">{(q.error as Error).message}</p>;
  if (!q.data) return <div className="rounded-xl border border-slate-200 bg-white p-4"><SkeletonRows rows={4} /></div>;
  return (
    <div className="overflow-hidden rounded-xl border border-slate-200 bg-white shadow-2xs">
      <table className="w-full table-fixed text-xs">
        <thead className="border-b border-teal-100 bg-teal-50/80 text-[10.5px] uppercase tracking-wide text-teal-800">
          <tr>
            <th className={cn(th, "pl-4 text-left")}>Adjustments</th>
            <th className={cn(th, "w-72 text-left")}>Ref</th>
            <th className={cn(th, "w-32 pr-4 text-right")}>Amount</th>
          </tr>
        </thead>
        <tbody className="divide-y divide-slate-100">
          {q.data.lines.map((l) => <Line key={l.key} line={l} side={side} />)}
        </tbody>
      </table>
    </div>
  );
}

function Line({ line: l, side }: { line: TradeAdjustment; side: "customer" | "supplier" }) {
  const [open, setOpen] = useState(false);
  const found = l.count > 0 && l.key !== "direct";
  const ref = l.key === "opening" ? l.note
    : l.count === 0 ? "none found"
    : `${l.count} item${l.count === 1 ? "" : "s"}${l.note ? ` · ${l.note}` : ""}`;
  const canOpen = l.details.length > 0;
  return (
    <>
      <tr className={cn("group", canOpen && "cursor-pointer hover:bg-teal-50/40")} onClick={() => canOpen && setOpen(!open)}>
        <td className={cn("py-2 pl-4 pr-3", found ? "font-medium text-rose-700" : "text-slate-800")}>
          <span className="inline-flex items-center gap-1">
            {canOpen ? (open ? <ChevronDown className="h-3.5 w-3.5 text-slate-400" /> : <ChevronRight className="h-3.5 w-3.5 text-slate-400" />)
              : <span className="w-3.5" />}
            {l.label}
          </span>
        </td>
        <td className="truncate px-3 py-2 text-[11px] text-slate-500" title={ref}>{ref}</td>
        <td className={cn(num, "pr-4", found && "font-semibold text-rose-700", l.amount === 0 && "text-slate-300")}>
          <span className="inline-flex items-center justify-end gap-1">
            {l.amount === null ? "-" : money(l.amount)}
            {found && (
              <AskLedge icon label="Ask Ledge" question={`On trade ${side === "customer" ? "debtors" : "creditors"}: "${l.label}" comes to ${money(l.amount)} (${l.count} items: ${l.details.slice(0, 3).join("; ")}). What should I check, and what journal would put it right?`} />
            )}
          </span>
        </td>
      </tr>
      {open && (
        <tr>
          <td colSpan={3} className="bg-slate-50/60 px-4 py-2">
            <ul className="space-y-0.5 pl-5 text-[11px] text-slate-600">
              {l.details.map((d) => <li key={d} className="list-disc">{d}</li>)}
              {l.more > 0 && <li className="list-none text-slate-400">and {l.more} more</li>}
            </ul>
          </td>
        </tr>
      )}
    </>
  );
}
