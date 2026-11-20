"use client";

// Documents being read, one at a time: the page with a scan line over it, the steps (scanning, reading figures,
// double-checking) and what was found, then the next file. Which models read it is not shown.
import { useEffect, useState } from "react";
import { AlertTriangle, CheckCircle2, Circle, FileText, Loader2 } from "lucide-react";
import type { SaDocument } from "@/lib/api";

export const SCAN_STEPS = ["Scanning document", "Reading figures", "Double-checking"] as const;

export interface ScanResult {
  name: string;
  file: File;
  docs: SaDocument[];          // what this file became (a zip: several)
}

const money = (v: unknown) =>
  typeof v === "number" ? `£${v.toLocaleString("en-GB", { minimumFractionDigits: 2, maximumFractionDigits: 2 })}` : "—";

function needsLook(docs: SaDocument[]) {
  return docs.some((d) => d.status === "CHECK" || d.status === "UNREADABLE");
}

function Figures({ docs }: { docs: SaDocument[] }) {
  const p60 = docs.find((d) => d.kind === "P60" && d.fields);
  if (!p60?.fields) return null;
  const f = p60.fields;
  const rows: [string, string][] = [["Employer", String(f.employer ?? "—")], ["Pay", money(f.pay_this)],
                                    ["Tax", money(f.tax_this)], ["Tax code", String(f.tax_code ?? "—")]];
  return (
    <dl className="mt-3 grid grid-cols-[auto_1fr] gap-x-4 gap-y-1 text-xs">
      {rows.map(([k, v]) => (
        <div key={k} className="contents">
          <dt className="text-slate-500">{k}</dt>
          <dd className="font-semibold text-slate-900 text-right tabular-nums animate-in fade-in duration-500">{v}</dd>
        </div>
      ))}
    </dl>
  );
}

interface ScanQueueProps {
  file: File | null;           // the one being read now
  step: number;                // 0..2 while reading
  index: number;               // its place in the queue (0-based)
  total: number;
  last: ScanResult | null;     // the file just finished, shown until the next is under way
}

export function ScanQueue({ file, step, index, total, last }: ScanQueueProps) {
  // The photo itself as the page; made and released in one effect, so it survives React running effects twice
  const [picture, setPicture] = useState<string | null>(null);
  const shown = file || last?.file || null;
  useEffect(() => {
    if (!shown || !shown.type.startsWith("image/")) {
      // eslint-disable-next-line react-hooks/set-state-in-effect -- the picture's URL is made and released in this effect (an external resource), so clearing it lives here too
      setPicture(null);
      return;
    }
    const url = URL.createObjectURL(shown);
    setPicture(url);
    return () => URL.revokeObjectURL(url);
  }, [shown]);
  const finished = !file && last;
  const look = last ? needsLook(last.docs) : false;
  const again = !!last && last.docs.length > 0 && last.docs.every((d) => d.status === "DUPLICATE");

  return (
    <div className="rounded-xl border border-teal-200 bg-teal-50/40 p-4">
      <div className="flex items-center justify-between text-[11px] font-semibold text-teal-800">
        <span>{finished && index >= total - 1 ? "Finished" : total > 1 ? `${Math.min(index + 1, total)} of ${total}` : "Reading"}</span>
        <span className="h-1.5 w-32 rounded-full bg-teal-100 overflow-hidden">
          <span className="block h-full bg-teal-600 transition-all duration-500" style={{ width: `${(index / Math.max(total, 1)) * 100}%` }} />
        </span>
      </div>
      <div className="mt-3 flex flex-col sm:flex-row gap-5 items-start">
        {/* The page being read */}
        <div className="relative w-36 h-48 shrink-0 overflow-hidden rounded-lg border border-slate-200 bg-white shadow-sm">
          {picture ? (
            // eslint-disable-next-line @next/next/no-img-element
            <img src={picture} alt="" className="h-full w-full object-cover object-top" />
          ) : (
            <div className="p-3 space-y-2">
              <FileText className="w-5 h-5 text-teal-600" />
              {[80, 60, 90, 45, 70, 85, 50, 65, 40].map((w, i) => (
                <div key={i} className="h-1.5 rounded bg-slate-100" style={{ width: `${w}%` }} />
              ))}
            </div>
          )}
          {file && <div className="scan-beam" />}
          {finished && (
            <div className={`absolute inset-0 flex items-center justify-center ${look ? "bg-amber-50/80" : "bg-emerald-50/80"}`}>
              {look ? <AlertTriangle className="w-8 h-8 text-amber-600" /> : <CheckCircle2 className="w-8 h-8 text-emerald-600" />}
            </div>
          )}
        </div>

        <div className="flex-1 min-w-0">
          <p className="text-xs font-semibold text-slate-800 truncate" title={(file || null)?.name || last?.name}>
            {file?.name || last?.name}
          </p>
          <ol className="mt-2 space-y-1.5">
            {SCAN_STEPS.map((label, i) => {
              const done = finished || (file && i < step);
              const now = file && i === step;
              return (
                <li key={label} className={`flex items-center gap-2 text-xs ${done ? "text-slate-700" : now ? "text-teal-800 font-semibold" : "text-slate-400"}`}>
                  {done ? <CheckCircle2 className="w-3.5 h-3.5 text-teal-600" />
                    : now ? <Loader2 className="w-3.5 h-3.5 animate-spin text-teal-600" />
                    : <Circle className="w-3.5 h-3.5" />}
                  {label}{now ? "..." : ""}
                </li>
              );
            })}
            {finished && (
              <li className={`flex items-center gap-2 text-xs font-semibold ${look ? "text-amber-700" : "text-emerald-700"}`}>
                {look ? <AlertTriangle className="w-3.5 h-3.5" /> : <CheckCircle2 className="w-3.5 h-3.5" />}
                {look ? "Needs a look" : again ? "Already added" : "Done"}
              </li>
            )}
          </ol>
          {finished && last && <Figures docs={last.docs} />}
        </div>
      </div>
    </div>
  );
}
