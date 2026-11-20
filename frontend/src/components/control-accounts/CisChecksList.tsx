"use client";

import { useEffect, useState } from "react";
import { AlertTriangle, CheckCircle2, ChevronDown, CircleDashed, Info } from "lucide-react";
import { StatusChip, type ChipTone } from "@/components/ui/status-chip";
import { api, CisCheck, CisChecks } from "@/lib/api";
import { formatCurrency } from "@/lib/formatters";
import { cn } from "@/lib/utils";

const TONE: Record<CisCheck["status"], { tone: ChipTone; icon: typeof CheckCircle2; label: string }> = {
  PASS: { tone: "success", icon: CheckCircle2, label: "Pass" },
  FAIL: { tone: "danger", icon: AlertTriangle, label: "Fail" },
  INFO: { tone: "info", icon: Info, label: "Info" },
  "NOT RUN": { tone: "neutral", icon: CircleDashed, label: "Not run" },
};

const cell = (v: unknown) =>
  typeof v === "number" ? formatCurrency(v, { accountingStyle: true }) : v === null || v === undefined ? "-" : String(v);

/** The CIS tests T1-T10 and the timing items that explain the books against HMRC at the year end.
 * refreshKey: changes after the HMRC figures are saved, so the tests run again. */
export function CisChecksList({ engagementId, refreshKey }: { engagementId: string; refreshKey: number }) {
  const [data, setData] = useState<CisChecks | null>(null);
  const [open, setOpen] = useState<string | null>(null);

  useEffect(() => {
    api.getCisChecks(engagementId).then(setData).catch(() => setData(null));
  }, [engagementId, refreshKey]);

  if (!data?.on || !data.checks) return null;
  const failing = data.checks.filter((c) => c.status === "FAIL").length;

  return (
    <div className="border-t border-slate-100">
      <div className="flex items-center justify-between px-5 py-3">
        <p className="text-xs font-bold text-slate-800">CIS checks against HMRC</p>
        <span className="text-[11px] text-slate-500">{failing ? `${failing} failing: each is a review point` : "No failing check"}</span>
      </div>
      <ul className="divide-y divide-slate-100">
        {data.checks.map((c) => {
          const t = TONE[c.status];
          const columns = c.rows.length ? Object.keys(c.rows[0]).filter((k) => k !== "tax_month") : [];
          return (
            <li key={c.ref}>
              <button type="button" onClick={() => setOpen(open === c.ref ? null : c.ref)}
                className="flex w-full items-start gap-3 px-5 py-2.5 text-left hover:bg-slate-50">
                <span className="w-9 shrink-0 font-mono text-[11px] font-semibold text-slate-500">{c.ref}</span>
                <span className="min-w-0 flex-1">
                  <span className="block text-xs font-medium text-slate-800">{c.name}</span>
                  <span className="block text-[11px] text-slate-500">{c.summary}</span>
                </span>
                <StatusChip tone={t.tone} icon={t.icon}>{t.label}</StatusChip>
                <ChevronDown className={cn("mt-0.5 h-4 w-4 shrink-0 text-slate-400 transition", open === c.ref && "rotate-180")} />
              </button>
              {open === c.ref && (
                <div className="space-y-2 bg-slate-50/70 px-5 pb-3 pt-1">
                  {c.status === "FAIL" && c.query && (
                    <p className="rounded-md border border-rose-200 bg-rose-50 px-3 py-2 text-[11px] text-rose-800">
                      Query to the {c.query_to.toLowerCase()}: {c.query}
                    </p>
                  )}
                  {columns.length > 0 && (
                    <div className="overflow-x-auto rounded-md border border-slate-200 bg-white">
                      <table className="w-full text-[11px]">
                        <thead className="bg-slate-50 text-slate-500">
                          <tr>{columns.map((k) => <th key={k} className="whitespace-nowrap px-3 py-1.5 text-left font-semibold">{k.replace(/_/g, " ")}</th>)}</tr>
                        </thead>
                        <tbody className="divide-y divide-slate-100">
                          {c.rows.slice(0, 60).map((r, i) => (
                            <tr key={i} className={cn(typeof r.difference === "number" && Math.abs(r.difference) >= 1 && !r.note && "bg-rose-50/60")}>
                              {columns.map((k) => <td key={k} className={cn("px-3 py-1.5", typeof r[k] === "number" ? "text-right font-mono" : "text-slate-700")}>{cell(r[k])}</td>)}
                            </tr>
                          ))}
                        </tbody>
                      </table>
                    </div>
                  )}
                </div>
              )}
            </li>
          );
        })}
      </ul>
      {data.timing && data.timing.length > 0 && (
        <div className="border-t border-slate-100 px-5 py-3">
          <p className="mb-1 text-xs font-bold text-slate-800">Timing items at the year end</p>
          <ul className="space-y-0.5 text-[11px] text-slate-600">
            {data.timing.map((t) => (
              <li key={t.item} className="flex justify-between gap-3"><span>{t.item}</span><span className="font-mono">{formatCurrency(t.amount)}</span></li>
            ))}
          </ul>
        </div>
      )}
    </div>
  );
}
