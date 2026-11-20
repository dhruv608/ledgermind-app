"use client";

import { wp } from "@/components/review/area/WorkpaperParts";
import { cn } from "@/lib/utils";

/**
 * The HMRC VAT account (date, description, amount): every payment to or from HMRC on the VAT account this year,
 * last year's returns paid this year, and the interest or penalties HMRC charged (not VAT).
 */
const { money, th, num } = wp;
type Line = { date: string | null; description: string; amount: number; kind: "payment" | "earlier" | "charge" };
const KIND: Record<Line["kind"], string> = { payment: "", earlier: "last year's return", charge: "interest / penalty, not VAT" };
const day = (iso: string | null) => (iso ? new Date(`${iso}T00:00:00`).toLocaleDateString("en-GB") : "-");

export function VatHmrcAccount({ lines }: { lines: Line[] }) {
  if (!lines.length) return null;
  const total = lines.reduce((s, l) => s + l.amount, 0);
  return (
    <div className="overflow-hidden rounded-xl border border-slate-200 bg-white shadow-2xs">
      <div className="border-b border-teal-100 bg-linear-to-r from-teal-50/70 to-white px-4 py-3">
        <h3 className="text-sm font-bold text-teal-900">HMRC VAT account</h3>
        <p className="text-[11px] text-slate-500">Payments to HMRC (and repayments from HMRC, as minus) on the VAT account this year.</p>
      </div>
      <table className="w-full table-fixed text-xs">
        <thead className="border-b border-teal-100 bg-teal-50/80 text-[10.5px] uppercase tracking-wide text-teal-800">
          <tr>
            <th className={cn(th, "w-28 pl-4 text-left")}>Date</th>
            <th className={cn(th, "text-left")}>Description</th>
            <th className={cn(th, "w-36 pr-4 text-right")}>Amount</th>
          </tr>
        </thead>
        <tbody className="divide-y divide-slate-100">
          {lines.map((l, i) => (
            <tr key={`${l.date}-${i}`}>
              <td className="whitespace-nowrap py-1.5 pl-4 text-slate-500">{day(l.date)}</td>
              <td className="truncate px-3 py-1.5 text-slate-800" title={l.description}>
                {l.description || "HMRC"}
                {KIND[l.kind] && <span className="ml-2 rounded-full bg-slate-100 px-1.5 py-px text-[10px] text-slate-500">{KIND[l.kind]}</span>}
              </td>
              <td className={cn(num, "py-1.5 pr-4", l.kind === "charge" && "text-orange-700")}>{money(l.amount)}</td>
            </tr>
          ))}
        </tbody>
        <tfoot className="border-t-2 border-teal-200 bg-teal-50/70 font-bold text-teal-900">
          <tr><td className="py-2 pl-4" colSpan={2}>Total</td><td className={cn(num, "pr-4")}>{money(total)}</td></tr>
        </tfoot>
      </table>
    </div>
  );
}
