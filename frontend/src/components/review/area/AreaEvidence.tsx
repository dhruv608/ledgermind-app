"use client";

import { useRef, useState } from "react";
import { useEvidence, useJobStore } from "@/lib/queries/job";
import { CheckCircle2, CircleDashed, Download, Loader2, Trash2, Upload } from "lucide-react";
import { toast } from "@/lib/notify";
import type { EvidenceByArea, EvidenceDoc } from "@/lib/api";
import type { Area } from "@/lib/areas";
import { api } from "@/lib/api";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";
import { serverDate } from "@/lib/formatters";

export const READ_AS: Record<string, string> = {
  VAT_100: "VAT returns", PAYROLL_P32: "payroll report", FIXED_ASSET_REGISTER: "fixed asset register",
  LOANS_REGISTER: "loans register",
};
const day = (iso: string | null) => (iso ? serverDate(iso).toLocaleDateString("en-GB") : "");
const size = (n: number) => (n >= 1024 * 1024 ? `${(n / 1024 / 1024).toFixed(1)} MB` : `${Math.max(1, Math.round(n / 1024))} KB`);

/** An area page's Evidence tab (an upload box per balance; a missing document never blocks): what the area
 *  needs, whether it is in, and an upload box. Files are kept for the reviewer; the ones the app can read go into
 *  the checks, which then run again. */
export function AreaEvidence({
  engagementId, area, what, reads, onRead,
}: {
  engagementId: string;
  area: Area;
  /** The document this area needs ("The aged debtors report") */
  what: string;
  /** Whether the checks read this area's document (VAT, payroll, fixed assets, loans) */
  reads: boolean;
  /** After a document the checks read: the checks run again */
  onRead?: () => void;
}) {
  // From the job's shared store: the same list the Add document window uploads into
  const evidence = useEvidence(engagementId);
  const docs: EvidenceByArea | null = evidence.data ?? (evidence.isError ? {} : null);
  const setDocs = useJobStore(engagementId).setEvidence;
  const [busy, setBusy] = useState(false);
  const [over, setOver] = useState(false);
  const input = useRef<HTMLInputElement>(null);

  const mine = (docs || {})[area.key] || [];

  const add = async (files: File[]) => {
    if (!files.length) return;
    setBusy(true);
    try {
      const next = await api.addEvidence(engagementId, area.key, files);
      setDocs(next);
      const read = (next[area.key] || []).filter((d) => files.some((f) => f.name === d.filename) && d.read_as).length;
      toast.success(read ? "Uploaded and read into the checks: they run again" : "Uploaded and kept with this area");
      if (read) onRead?.();
    } catch (e) {
      toast.error(e instanceof Error ? e.message : "Could not upload");
    } finally {
      setBusy(false);
    }
  };

  const remove = async (doc: EvidenceDoc) => {
    if (doc.id === null) return;
    setBusy(true);
    try {
      setDocs(await api.removeEvidence(engagementId, doc.id));
      toast.success("Removed from this area");
    } catch (e) {
      toast.error(e instanceof Error ? e.message : "Could not remove");
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-start justify-between gap-3 rounded-xl border border-slate-200 bg-white p-4 text-xs shadow-2xs">
        <div className="min-w-0">
          <p className="font-semibold text-slate-800">{what}</p>
          <p className="mt-1 text-slate-500">
            {reads ? "Upload it here: the app keeps it for the reviewer and reads it into this area's checks."
              : "Upload it here: the app keeps it with this area for the reviewer. A missing document does not stop the work."}
          </p>
        </div>
        {docs !== null && (
          <span className={cn("inline-flex shrink-0 items-center gap-1 rounded-full px-2 py-0.5 text-[11px] font-bold",
                              mine.length ? "bg-emerald-50 text-emerald-700" : "bg-slate-100 text-slate-600")}>
            {mine.length ? <CheckCircle2 className="h-3.5 w-3.5" /> : <CircleDashed className="h-3.5 w-3.5" />}
            {mine.length ? "In" : "Not in yet"}
          </span>
        )}
      </div>

      <div
        onDragOver={(e) => { e.preventDefault(); setOver(true); }}
        onDragLeave={() => setOver(false)}
        onDrop={(e) => { e.preventDefault(); setOver(false); add(Array.from(e.dataTransfer.files)); }}
        className={cn("flex flex-col items-center justify-center gap-2 rounded-xl border-2 border-dashed px-4 py-6 text-center text-xs",
                      over ? "border-teal-500 bg-teal-50/60" : "border-slate-200 bg-white")}
      >
        {busy ? <Loader2 className="h-5 w-5 animate-spin text-slate-400" /> : <Upload className="h-5 w-5 text-slate-400" />}
        <p className="text-slate-600">Drop the file here, or</p>
        <Button size="sm" variant="outline" className="h-8 text-xs" disabled={busy} onClick={() => input.current?.click()}>
          Choose a file
        </Button>
        <input ref={input} type="file" multiple className="hidden"
               onChange={(e) => { add(Array.from(e.target.files || [])); e.target.value = ""; }} />
        <p className="text-[11px] text-slate-400">Excel, CSV or PDF</p>
      </div>

      {mine.length > 0 && (
        <ul className="divide-y divide-slate-100 overflow-hidden rounded-xl border border-slate-200 bg-white text-xs shadow-2xs">
          {mine.map((d, i) => (
            <li key={d.id ?? `old-${i}`} className="flex flex-wrap items-center justify-between gap-2 px-4 py-2.5">
              <span className="min-w-0">
                <span className="block truncate font-medium text-slate-800" title={d.filename}>{d.filename}</span>
                <span className="text-[11px] text-slate-500">
                  {[day(d.at), d.size ? size(d.size) : "",
                    d.read_as ? `read as the ${READ_AS[d.read_as] || d.read_as}${d.records ? ` (${d.records} rows)` : ""}` : "kept for the reviewer",
                    d.kept ? "" : "read before files were kept here"].filter(Boolean).join(" · ")}
                </span>
              </span>
              {d.kept && d.id !== null && (
                <span className="flex gap-1.5">
                  <Button size="sm" variant="outline" className="h-7 text-xs" disabled={busy}
                          onClick={() => api.openEvidence(engagementId, d).catch((e) => toast.error(e.message))}>
                    <Download className="mr-1 h-3.5 w-3.5" /> Open
                  </Button>
                  <Button size="sm" variant="ghost" className="h-7 text-xs text-slate-500" disabled={busy} onClick={() => remove(d)}
                          aria-label={`Remove ${d.filename}`}>
                    <Trash2 className="h-3.5 w-3.5" />
                  </Button>
                </span>
              )}
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
