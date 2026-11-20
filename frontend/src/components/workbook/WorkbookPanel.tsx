"use client";

import { useEffect, useState } from "react";
import { AlertTriangle, ChevronDown, Download, Eye, FileSpreadsheet, History, RefreshCw } from "lucide-react";
import { api, resolveBackendUrl } from "@/lib/api";
import { cn } from "@/lib/utils";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { SectionHeader } from "@/components/ui/section-header";
import { StatusChip } from "@/components/ui/status-chip";
import { EmptyState } from "@/components/common/EmptyState";
import { AuditFinding, LatestWorkpaper, ProposedJournal } from "@/types/engagement";
import type { Reconciliations } from "@/lib/api";
import { IndexTab, WorkpaperIndex } from "./WorkpaperIndex";
import { plural } from "@/lib/formatters";

// Sheets worth jumping to straight away (the viewer opens the first sheet whose name starts with the prefix)
const QUICK_SHEETS = [
  { prefix: "B1", label: "ETB" },
  { prefix: "B2", label: "Journals" },
  { prefix: "H1", label: "Tax computation" },
  { prefix: "A1", label: "General checks" },
];

interface WorkbookPanelProps {
  engagementId: string;
  workpaper: LatestWorkpaper | null;
  downloadUrl: string | null;
  mappingsToReview: number;
  isGenerating: boolean;
  onGenerate: () => void;
  /** Open a workbook in the preview, optionally at a sheet. */
  onView: (workpaper: LatestWorkpaper, sheet?: string) => void;
  onReviewAccounts: () => void;
  /** Built before the latest changes. */
  stale?: boolean;
  /** What must be done before the workbook can be built. */
  buildBlockers?: string[];
  onGoTo?: (tab: "data" | "setup" | "accounts" | "review" | "journals") => void;
  /** For the workpaper index: the review points, journals and balance sheet accounts, and the tab each opens */
  findings?: AuditFinding[];
  journals?: ProposedJournal[];
  recs?: Reconciliations | null;
  reviewRan?: boolean;
  onOpenTab?: (tab: IndexTab) => void;
  onOpenArea?: (key: string) => void;
}

/** The Excel working papers: the last one built, and building a new one. */
// The tab names the sidebar shows, for the "Go to" buttons
const TAB_NAME: Record<"data" | "setup" | "accounts" | "review" | "journals", string> = {
  data: "Files", setup: "Client details", accounts: "Accounts", review: "Review points", journals: "Journals",
};

export function WorkbookPanel({
  engagementId,
  workpaper,
  downloadUrl,
  mappingsToReview,
  isGenerating,
  onGenerate,
  onView,
  onReviewAccounts,
  stale = false,
  buildBlockers = [],
  onGoTo,
  findings = [],
  journals = [],
  recs = null,
  reviewRan = false,
  onOpenTab,
  onOpenArea,
}: WorkbookPanelProps) {
  const blocked = buildBlockers.length > 0;
  const [history, setHistory] = useState<LatestWorkpaper[]>([]);
  const [showHistory, setShowHistory] = useState(false);
  useEffect(() => {
    api.getWorkpaperHistory(engagementId).then(setHistory);
  }, [engagementId, workpaper?.filename, workpaper?.generated_at]);
  const earlier = history.slice(1);
  // Journals still waiting: the workbook holds approved journals only, so these are not in its figures (said here,
  // so a draft with proposed journals left out is not read as one with no journals)
  const waiting = journals.filter((j) => j.status === "PROPOSED").length;

  return (
    <div className="space-y-4">
      <Card className="px-4 py-3.5">
        <SectionHeader
          icon={FileSpreadsheet}
          title="Finish and download" page
          description="Build the Excel working papers from the trial balance, ledger, approved journals, VAT returns and review checks, then download them."
          actions={
            <Button variant="primary" size="sm" onClick={onGenerate} disabled={isGenerating || blocked}>
              <RefreshCw className={`mr-1.5 h-3.5 w-3.5 ${isGenerating ? "animate-spin" : ""}`} />
              {isGenerating ? "Building…" : workpaper ? "Build Excel again" : "Build Excel"}
            </Button>
          }
        />

        {blocked && (
          <div className="mt-4 rounded-lg border border-amber-200 bg-amber-50 p-3">
            <p className="text-xs font-semibold text-amber-900">Before the workbook can be built</p>
            <ul className="mt-2 space-y-1.5">
              {buildBlockers.map((b) => {
                const tab = b.startsWith("Files") || b.startsWith("Data check") ? "data" : b.startsWith("Setup") ? "setup" : b.startsWith("Accounts") ? "accounts" : "review";
                // A Data check reason is long: its heading here, the whole reason on the Data check tab (and on hover)
                const shown = tab === "data" ? b.split(": ").slice(0, 2).join(": ") : b;
                return (
                  <li key={b} className="flex items-center justify-between gap-3 text-xs text-amber-900" title={b}>
                    <span className="flex items-center gap-2">
                      <span className={`h-1.5 w-1.5 shrink-0 rounded-full ${tab === "data" ? "bg-rose-500" : "bg-amber-500"}`} />
                      {shown}
                    </span>
                    {onGoTo && (
                      <button type="button" onClick={() => onGoTo(tab)} className="shrink-0 text-[11px] font-medium text-teal-800 hover:underline">
                        Go to {TAB_NAME[tab]}
                      </button>
                    )}
                  </li>
                );
              })}
            </ul>
          </div>
        )}

        {waiting > 0 && (
          <div className="mt-4 flex flex-wrap items-center justify-between gap-2 rounded-lg border border-amber-200 bg-amber-50 px-3 py-2.5">
            <p className="text-xs text-amber-900">
              <span className="font-semibold">{plural(waiting, "journal")} waiting for your decision</span>, not in the
              workbook&apos;s figures: it holds approved journals only. Approve or reject them, then build again.
            </p>
            {onGoTo && (
              <button type="button" onClick={() => onGoTo("journals")} className="shrink-0 text-[11px] font-semibold text-teal-800 hover:underline">
                Go to Journals
              </button>
            )}
          </div>
        )}

        <div className="mt-5">
          {workpaper && downloadUrl ? (
            <div className="flex flex-col gap-4 rounded-lg border border-slate-200 bg-slate-50/60 p-4 sm:flex-row sm:items-center sm:justify-between">
              <div className="flex min-w-0 items-center gap-3">
                <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-lg bg-emerald-50 text-emerald-600">
                  <FileSpreadsheet className="h-5 w-5" />
                </div>
                <div className="min-w-0">
                  <p className="truncate text-sm font-semibold text-slate-900" title={workpaper.filename}>{workpaper.filename}</p>
                  <div className="mt-1 flex flex-wrap items-center gap-1.5">
                    <StatusChip tone={workpaper.is_draft ? "warning" : "success"}>
                      {workpaper.is_draft ? "Draft" : "Final"}
                    </StatusChip>
                    {stale && <StatusChip tone="warning">Needs refresh</StatusChip>}
                    {workpaper.generated_at && <span className="text-[11px] text-slate-500">Built {workpaper.generated_at}</span>}
                  </div>
                </div>
              </div>
              <div className="flex shrink-0 gap-2">
                <Button variant="outline" size="sm" onClick={() => onView(workpaper)}>
                  <Eye className="mr-1.5 h-3.5 w-3.5" />
                  View
                </Button>
                <a
                  href={downloadUrl}
                  download
                  className="inline-flex h-8 items-center rounded-lg bg-teal-700 px-3 text-xs font-medium text-white shadow-2xs transition hover:bg-teal-800"
                >
                  <Download className="mr-1.5 h-3.5 w-3.5" />
                  Download
                </a>
              </div>
            </div>
          ) : (
            <p className="mt-3 flex items-center gap-2 rounded-lg border border-dashed border-slate-200 px-3 py-2 text-xs text-slate-500">
              <FileSpreadsheet className="h-4 w-4 shrink-0 text-slate-400" />
              No workbook built yet: build it with the button above (about a minute).
            </p>
          )}
          {stale && !blocked && (
            <div className="mt-3 flex flex-col gap-2 rounded-lg border border-amber-200 bg-amber-50 px-3 py-2.5 text-xs text-amber-900 sm:flex-row sm:items-center sm:justify-between">
              <p className="flex items-start gap-2">
                <AlertTriangle className="mt-0.5 h-3.5 w-3.5 shrink-0 text-amber-600" />
                <span>
                  Something changed after this workbook was built: build it again.
                </span>
              </p>
            </div>
          )}
          {workpaper && downloadUrl && (
            <div className="mt-3 flex flex-wrap items-center gap-1.5 text-[11px] text-slate-500">
              <span className="mr-1">Open at:</span>
              {QUICK_SHEETS.map((q) => (
                <button
                  key={q.prefix}
                  type="button"
                  onClick={() => onView(workpaper, q.prefix)}
                  className="rounded-md border border-slate-200 bg-white px-2 py-1 font-medium text-slate-600 transition hover:border-teal-300 hover:text-teal-800"
                >
                  <span className="font-mono text-slate-400">{q.prefix}</span> {q.label}
                </button>
              ))}
            </div>
          )}
        </div>
      </Card>

      {onOpenTab && (
        <WorkpaperIndex
          findings={findings}
          journals={journals}
          recs={recs}
          mappingsToReview={mappingsToReview}
          reviewRan={reviewRan}
          canView={Boolean(workpaper && downloadUrl)}
          onOpenSheet={(prefix) => workpaper && onView(workpaper, prefix)}
          onGoTo={onOpenTab}
          onOpenArea={onOpenArea}
        />
      )}

      {earlier.length > 0 && (
        <Card className="overflow-hidden">
          <button
            type="button"
            onClick={() => setShowHistory(!showHistory)}
            className="flex w-full items-center justify-between px-5 py-3 text-left hover:bg-slate-50"
          >
            <span className="flex items-center gap-2 text-xs font-semibold text-slate-800">
              <History className="h-4 w-4 text-slate-400" />
              Earlier versions
              <span className="font-normal text-slate-400">{earlier.length}</span>
            </span>
            <ChevronDown className={cn("h-4 w-4 text-slate-400 transition", showHistory && "rotate-180")} />
          </button>
          {showHistory && (
            <ul className="divide-y divide-slate-100 border-t border-slate-100">
              {earlier.map((wp) => (
                <li key={wp.id} className="flex items-center justify-between gap-3 px-5 py-2.5">
                  <div className="min-w-0">
                    <p className="truncate text-xs font-medium text-slate-700" title={wp.filename}>{wp.filename}</p>
                    <p className="text-[11px] text-slate-400">
                      {wp.generated_at}
                      {wp.file_size_bytes ? ` · ${Math.round(wp.file_size_bytes / 1024)} KB` : ""}
                    </p>
                  </div>
                  <div className="flex shrink-0 items-center gap-1.5">
                    <StatusChip tone={wp.is_draft ? "warning" : "success"}>{wp.is_draft ? "Draft" : "Final"}</StatusChip>
                    <button
                      type="button"
                      onClick={() => onView(wp)}
                      className="rounded-md p-1.5 text-slate-400 hover:bg-slate-100 hover:text-slate-700"
                      title="Preview"
                    >
                      <Eye className="h-3.5 w-3.5" />
                    </button>
                    <a
                      href={resolveBackendUrl(wp.download_url) || undefined}
                      download
                      className="rounded-md p-1.5 text-slate-400 hover:bg-slate-100 hover:text-emerald-700"
                      title="Download"
                    >
                      <Download className="h-3.5 w-3.5" />
                    </a>
                  </div>
                </li>
              ))}
            </ul>
          )}
        </Card>
      )}
    </div>
  );
}
