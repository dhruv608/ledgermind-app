"use client";

// The figures to enter in TaxCalc, form by form and box by box (HMRC's 2025-26 forms), with the result the software
// should agree with. Each figure can be copied; a figure from a document opens it.
import { useEffect, useState } from "react";
import { toast } from "@/lib/notify";
import { Copy, FileText, Info } from "lucide-react";
import { api, SaBoxes as Data, SaBoxRow } from "@/lib/api";
import { NUM, SaHead, TABLE_WRAP, THEAD, TROW, text } from "@/components/sa/SaChrome";
import { cn } from "@/lib/utils";

const money = (v: number) => `${v < 0 ? "-" : ""}£${Math.abs(v).toLocaleString("en-GB", { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
const shown = (v: SaBoxRow["value"]) => (typeof v === "number" ? money(v) : v || "—");

export function SaBoxes({ jobId, onOpenDoc }: { jobId: string; onOpenDoc?: (id: number) => void }) {
  const [data, setData] = useState<Data | null>(null);
  useEffect(() => { api.getSaBoxes(jobId).then(setData).catch(() => {}); }, [jobId]);
  if (!data) return <div className="skeleton h-48 rounded-xl" />;

  const copy = async (v: SaBoxRow["value"]) => {
    if (v === null || v === "") return;
    try { await navigator.clipboard.writeText(typeof v === "number" ? v.toFixed(2) : v); toast.success("Copied"); }
    catch { toast.error("Could not copy"); }
  };
  const r = data.result;

  return (
    <div className="space-y-4">
      <SaHead title="TaxCalc figures"
              state={data.pages.length ? { text: `${data.pages.length} page${data.pages.length > 1 ? "s" : ""}`, tone: "info" } : { text: "No figures yet", tone: "empty" }}
              meta="Each figure under its form and box number on HMRC's 2025-26 forms, to enter in TaxCalc. After entering them, TaxCalc's result should match the figures here."
              figures={[
                { label: "Income tax due", value: money(r.income_tax_due) },
                { label: "Class 4 NIC", value: money(r.class4) },
                { label: "Tax deducted", value: money(r.tax_deducted) },
                { label: "Balance to pay", value: money(r.balance), tone: r.balance < 0 ? "text-teal-700" : undefined },
              ]} />
      {data.left.length > 0 && (
        <div className="rounded-xl border border-amber-200 bg-amber-50 px-4 py-2.5 text-xs text-amber-900">
          {data.left.map((l) => <p key={l} className="flex gap-1.5"><Info className="mt-px h-3.5 w-3.5 shrink-0" />{l}</p>)}
        </div>
      )}
      {data.pages.map((p) => (
        <section key={p.form + p.title} className={TABLE_WRAP}>
          <div className="flex flex-wrap items-baseline gap-2 border-b border-slate-200 px-4 py-3">
            <span className="rounded bg-teal-50 px-1.5 py-px text-[10.5px] font-bold text-teal-800">{p.form}</span>
            <p className={text.card}>{p.title}</p>
            {p.note && <p className="text-[11px] text-slate-500">{p.note}</p>}
          </div>
          <table className="w-full table-fixed text-xs">
            <thead className={THEAD}>
              <tr className="text-left">
                <th className="w-16 px-4 py-2 font-semibold">Box</th>
                <th className="px-3 py-2 font-semibold">What</th>
                <th className="w-36 px-3 py-2 text-right font-semibold">Figure</th>
                <th className="w-16" />
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-100">
              {p.rows.map((row, i) => (
                <tr key={row.box + i} className={cn(TROW, "align-top")}>
                  <td className="px-4 py-2 font-semibold text-slate-500">{row.box}</td>
                  <td className="px-3 py-2">
                    <p className="text-slate-800">{row.label}</p>
                    {row.note && <p className="text-[11px] text-slate-400">{row.note}</p>}
                  </td>
                  <td className={cn("px-3 py-2 text-right text-slate-900", typeof row.value === "number" && NUM)}>{shown(row.value)}</td>
                  <td className="px-2 py-1.5 text-right">
                    <span className="inline-flex gap-1">
                      {row.doc_id && onOpenDoc && (
                        <button type="button" title="Open the document" onClick={() => onOpenDoc(row.doc_id!)} className="rounded p-1 text-slate-400 hover:bg-slate-100 hover:text-teal-700 cursor-pointer"><FileText className="h-3.5 w-3.5" /></button>
                      )}
                      {row.value !== null && row.value !== "" && (
                        <button type="button" title="Copy" onClick={() => copy(row.value)} className="rounded p-1 text-slate-400 hover:bg-slate-100 hover:text-teal-700 cursor-pointer"><Copy className="h-3.5 w-3.5" /></button>
                      )}
                    </span>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </section>
      ))}
    </div>
  );
}
