"use client";

import { getAccountingSystemBadge } from "@/lib/badges";

import { useEffect, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import { useQuery } from "@tanstack/react-query";
import { ChevronDown, FileSpreadsheet, FileUp, Search } from "lucide-react";
import { api } from "@/lib/api";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";

// The year end as "31 Mar 2026", whether it comes as 2026-03-31 or 31/03/2026
const yearOf = (d: string) => {
  const uk = /^(\d{1,2})\/(\d{1,2})\/(\d{4})$/.exec(d || "");
  const date = uk ? new Date(+uk[3], +uk[2] - 1, +uk[1]) : new Date(d);
  return isNaN(date.getTime()) ? d : date.toLocaleDateString("en-GB", { day: "numeric", month: "short", year: "numeric" });
};

/**
 * The bar over every screen of a job: the screen's name, the client (switch to another client's job
 * from here), Add document and Download Excel. It downloads the workbook when it is up to date; otherwise it opens
 * Finish and download, where it is built.
 */
export function JobTopBar({ title, engagementId, clientName, yearEnd, source, downloadUrl, onBuild, onAddDocument }: {
  title: string;
  /** The accounting software the books came from (a "QuickBooks data" tag by the client) */
  source?: string;
  engagementId: string;
  clientName: string;
  yearEnd: string;
  /** The workbook to download, when it is built and up to date */
  downloadUrl: string | null;
  onBuild: () => void;
  onAddDocument: () => void;
}) {
  return (
    <div className="flex flex-wrap items-center gap-x-4 gap-y-2 rounded-xl border border-slate-200 bg-white px-4 py-2.5 shadow-2xs">
      <h1 className="text-sm font-bold text-slate-900">{title}</h1>
      <ClientPicker engagementId={engagementId} clientName={clientName} yearEnd={yearEnd} />
      {source && (() => {
        const b = getAccountingSystemBadge(source);
        return <span className={cn("rounded-full border px-2 py-0.5 text-[11px] font-semibold", b.className)}>{b.label} data</span>;
      })()}
      <span className="flex-1" />
      <Button variant="outline" size="sm" className="h-8 text-xs" onClick={onAddDocument}>
        <FileUp className="mr-1.5 h-3.5 w-3.5" /> Add document
      </Button>
      {downloadUrl ? (
        <a href={downloadUrl} download
           className="inline-flex h-8 items-center rounded-md bg-teal-700 px-3 text-xs font-semibold text-white shadow-xs transition hover:bg-teal-800">
          <FileSpreadsheet className="mr-1.5 h-3.5 w-3.5" /> Download Excel
        </a>
      ) : (
        <Button size="sm" className="h-8 text-xs" onClick={onBuild} title="The Excel file is not built, or the work changed since: Finish and download builds it">
          <FileSpreadsheet className="mr-1.5 h-3.5 w-3.5" /> Download Excel
        </Button>
      )}
    </div>
  );
}

/** The client of this job, and every other client's job a click away (searched by name) */
function ClientPicker({ engagementId, clientName, yearEnd }: { engagementId: string; clientName: string; yearEnd: string }) {
  const router = useRouter();
  const [open, setOpen] = useState(false);
  const [q, setQ] = useState("");
  const box = useRef<HTMLDivElement>(null);
  // Asked for only when the list is opened, then kept in the shared store
  const clients = useQuery({ queryKey: ["clients"], queryFn: () => api.listClients(), enabled: open });
  useEffect(() => {
    if (!open) return;
    const away = (e: MouseEvent) => { if (box.current && !box.current.contains(e.target as Node)) setOpen(false); };
    document.addEventListener("mousedown", away);
    return () => document.removeEventListener("mousedown", away);
  }, [open]);
  const list = (clients.data || []).filter((c) => c.client_name.toLowerCase().includes(q.toLowerCase())).slice(0, 50);
  return (
    <div ref={box} className="relative">
      <button type="button" onClick={() => setOpen(!open)}
              className="inline-flex items-center gap-1.5 rounded-lg border border-slate-200 px-2.5 py-1 text-xs text-slate-700 transition hover:border-teal-200 hover:bg-slate-50">
        <span className="max-w-[16rem] truncate font-semibold">{clientName}</span>
        <span className="text-slate-400">{yearOf(yearEnd)}</span>
        <ChevronDown className="h-3.5 w-3.5 text-slate-400" />
      </button>
      {open && (
        <div className="absolute left-0 top-full z-40 mt-1 w-80 overflow-hidden rounded-xl border border-slate-200 bg-white shadow-lg">
          <div className="flex items-center gap-2 border-b border-slate-100 px-3 py-2">
            <Search className="h-3.5 w-3.5 text-slate-400" />
            <input autoFocus value={q} onChange={(e) => setQ(e.target.value)} placeholder="Find a client"
                   className="w-full text-xs outline-none placeholder:text-slate-400" />
          </div>
          <ul className="max-h-72 overflow-y-auto py-1">
            {clients.isLoading && <li className="px-3 py-2 text-xs text-slate-400">Loading…</li>}
            {list.map((c) => (
              <li key={c.engagement_id}>
                <button type="button" onClick={() => { setOpen(false); router.push(`/clients/${c.engagement_id}`); }}
                        className={cn("flex w-full items-center justify-between gap-2 px-3 py-1.5 text-left text-xs hover:bg-teal-50/60",
                                      c.engagement_id === engagementId && "bg-teal-50 font-semibold text-teal-800")}>
                  <span className="truncate">{c.client_name}</span>
                  <span className="shrink-0 text-[11px] text-slate-400">{yearOf(c.period_end_date)}</span>
                </button>
              </li>
            ))}
            {clients.data && !list.length && <li className="px-3 py-2 text-xs text-slate-400">No client by that name</li>}
          </ul>
        </div>
      )}
    </div>
  );
}
