"use client";

import { useEffect, useRef, useState } from "react";
import { ArrowRight, CheckCircle2, FileSpreadsheet, MoreHorizontal, RefreshCw, Trash2 } from "lucide-react";
import { Button } from "@/components/ui/button";
import { getAccountingSystemBadge, getIndustryBadge } from "@/lib/badges";
import { cn } from "@/lib/utils";
import { ClientProfile, EngagementData } from "@/types/engagement";

export type WorkbookState = "none" | "draft" | "final";

/** The one next thing to do on the job (worked out on the client page) */
export interface NextStep {
  text: string;
  tone: "todo" | "stop" | "done";
  /** The step builds the workbook */
  build?: boolean;
}

interface EngagementHeaderProps {
  engagement: EngagementData;
  workbook: WorkbookState;
  /** What must be done before the workbook can be built. */
  buildBlockers?: string[];
  isGenerating: boolean;
  onGenerate: () => void;
  onDelete: () => void;
  next: NextStep;
  /** The tab the next step is done on ("" when it is the tab already open) and a way there */
  nextTabLabel?: string;
  onGoToNext?: () => void;
  onOpenWorkbook: () => void;
  /** Classes for the client's name in the line: shown only while the side checklist (which names the client) is
   * folded to its icons */
  nameClassName?: string;
  /** "side": the compact block in the left checklist (the next step under the job's progress) instead of a bar over
   * every tab */
  variant?: "bar" | "side";
}

/** The client's facts in a line: year end, system, industry (once confirmed), VAT, payroll */
export function clientFacts(engagement: EngagementData, profile: ClientProfile | null): string[] {
  const confirmedIndustry = (profile?.confirmed_fields || []).includes("industry_code");
  return [
    `Year end ${engagement.period_end_date}`,
    getAccountingSystemBadge(engagement.source_system).label,
    confirmedIndustry ? getIndustryBadge(profile?.industry_code).label : "Industry not set",
    profile?.is_vat_registered ? "VAT registered" : "Not VAT registered",
    profile?.has_payroll ? "Payroll" : "No payroll",
  ].filter(Boolean) as string[];
}

/** One line over the open section: the one next thing to do, with its button, and the job's actions. Who the client
 * is and where each section stands are on the side checklist. */
export function EngagementHeader({
  engagement,
  workbook,
  buildBlockers = [],
  isGenerating,
  onGenerate,
  onDelete,
  next,
  nextTabLabel,
  onGoToNext,
  onOpenWorkbook,
  nameClassName,
  variant = "bar",
}: EngagementHeaderProps) {
  // Seconds since "Build" was pressed (the server builds and recalculates the whole workbook: about a minute)
  const [elapsed, setElapsed] = useState(0);
  // Back to 0 when the build ends (set while rendering, not in an effect)
  const [wasGenerating, setWasGenerating] = useState(isGenerating);
  if (wasGenerating !== isGenerating) {
    setWasGenerating(isGenerating);
    if (!isGenerating) setElapsed(0);
  }
  useEffect(() => {
    if (!isGenerating) return;
    const start = Date.now();
    const timer = setInterval(() => setElapsed(Math.floor((Date.now() - start) / 1000)), 1000);
    return () => clearInterval(timer);
  }, [isGenerating]);

  const [menuOpen, setMenuOpen] = useState(false);
  const menuRef = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (!menuOpen) return;
    const close = (e: MouseEvent) => {
      if (menuRef.current && !menuRef.current.contains(e.target as Node)) setMenuOpen(false);
    };
    document.addEventListener("mousedown", close);
    return () => document.removeEventListener("mousedown", close);
  }, [menuOpen]);

  const blocked = buildBlockers.length > 0;
  const tone = {
    todo: { text: "text-slate-800", icon: "text-teal-600" },
    stop: { text: "text-rose-800", icon: "text-rose-600" },
    done: { text: "text-emerald-800", icon: "text-emerald-600" },
  }[next.tone];

  const stepButton = (
    <>
        {next.build || isGenerating ? (
          <Button variant="primary" size="sm" onClick={onGenerate} disabled={isGenerating || blocked} className="h-8 shrink-0 text-xs">
            {isGenerating ? <RefreshCw className="mr-1.5 h-3.5 w-3.5 animate-spin" /> : <FileSpreadsheet className="mr-1.5 h-3.5 w-3.5" />}
            {isGenerating ? `Building… ${elapsed}s` : workbook === "none" ? "Build Excel" : "Build Excel again"}
          </Button>
        ) : next.tone === "done" ? (
          <Button variant="outline" size="sm" onClick={onOpenWorkbook} className="h-8 shrink-0 bg-white text-xs">
            <FileSpreadsheet className="mr-1.5 h-3.5 w-3.5" /> Open workbook
          </Button>
        ) : (
          nextTabLabel &&
          onGoToNext && (
            <Button variant="outline" size="sm" onClick={onGoToNext} className="h-8 shrink-0 bg-white text-xs">
              Go to {nextTabLabel} <ArrowRight className="ml-1 h-3.5 w-3.5" />
            </Button>
          )
        )}
    </>
  );
  const menu = (
        <div className="relative" ref={menuRef}>
          <button
            type="button"
            onClick={() => setMenuOpen(!menuOpen)}
            className="rounded-md p-1.5 text-slate-400 transition hover:bg-slate-100 hover:text-slate-700"
            aria-label="More actions"
            title="More actions"
          >
            <MoreHorizontal className="h-4 w-4" />
          </button>
          {menuOpen && (
            <div className="absolute right-0 top-full z-40 mt-1 w-56 overflow-hidden rounded-lg border border-slate-200 bg-white py-1 text-xs shadow-lg">
              <button
                type="button"
                disabled={blocked || isGenerating}
                title={blocked ? `Before building:\n${buildBlockers.join("\n")}` : undefined}
                onClick={() => {
                  setMenuOpen(false);
                  onGenerate();
                }}
                className="flex w-full items-center gap-2 px-3 py-2 text-left text-slate-700 hover:bg-slate-50 disabled:cursor-not-allowed disabled:text-slate-400"
              >
                <FileSpreadsheet className="h-3.5 w-3.5" />
                {workbook === "none" ? "Build Excel" : "Build Excel again"}
                {blocked && <span className="ml-auto text-[10px]">not yet</span>}
              </button>
              <button
                type="button"
                onClick={() => {
                  setMenuOpen(false);
                  onDelete();
                }}
                className="flex w-full items-center gap-2 px-3 py-2 text-left text-rose-600 hover:bg-rose-50"
              >
                <Trash2 className="h-3.5 w-3.5" />
                Delete this client
              </button>
            </div>
          )}
        </div>
  );

  if (variant === "side") {
    return (
      <div className="rounded-lg border border-slate-200 bg-white px-2.5 py-2.5 shadow-2xs">
        <div className="flex items-start justify-between gap-1">
          <p className={cn("min-w-0 text-[11px] leading-snug", tone.text)}>
            {next.tone !== "done" && <span className="font-semibold">Next: </span>}
            {isGenerating ? `Building the workbook (${elapsed}s): it is worked out and recalculated, usually about a minute.` : next.text}
          </p>
          {menu}
        </div>
        {/* The one thing to do: the terra button (the accent is kept for it alone) */}
        <div className="mt-2 flex [&_button]:h-7 [&_button]:w-full [&_button]:justify-center [&_button]:border-terra-500 [&_button]:bg-terra-500 [&_button]:text-white [&_button:hover]:bg-terra-600">{stepButton}</div>
      </div>
    );
  }

  return (
    <div
      className={cn(
        "flex flex-col gap-2 rounded-xl border px-4 py-2.5 shadow-2xs sm:min-h-12 sm:flex-row sm:items-center sm:justify-between",
        next.tone === "stop" ? "border-rose-100 bg-rose-50/60" : next.tone === "done" ? "border-emerald-100 bg-emerald-50/50" : "border-slate-200 bg-white",
      )}
    >
      <p className={cn("flex min-w-0 items-center gap-2 text-xs", tone.text)}>
        <span className={cn("shrink-0 font-bold text-slate-900", nameClassName)}>
          {engagement.client_name}
          <span className="mx-2 font-normal text-slate-300">|</span>
        </span>
        {next.tone === "done" ? (
          <CheckCircle2 className={cn("h-4 w-4 shrink-0", tone.icon)} />
        ) : (
          <ArrowRight className={cn("h-4 w-4 shrink-0", tone.icon)} />
        )}
        <span>
          {next.tone !== "done" && <span className="font-semibold">Next: </span>}
          {isGenerating ? `Building the workbook (${elapsed}s): it is worked out and recalculated, usually about a minute.` : next.text}
        </span>
      </p>
      <div className="flex shrink-0 items-center gap-1">
        {stepButton}
        {menu}
      </div>
    </div>
  );
}
