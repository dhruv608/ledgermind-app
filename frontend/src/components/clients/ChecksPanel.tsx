"use client";

import { useState } from "react";
import { AlertCircle, CheckCircle2, ChevronDown, ChevronRight, Circle, FileText, Loader2, XCircle } from "lucide-react";
import type { CheckRun } from "@/lib/api";
import { Modal } from "@/components/ui/dialog";
import { cn } from "@/lib/utils";
import { plural, formatCurrency, serverDate } from "@/lib/formatters";

const money = (n: number) => formatCurrency(n, { showPence: false });
const WHY: Record<string, string> = {
  setup: "the setup was saved",
  upload: "new files were uploaded",
  accountant: "Run review",
  change: "a change during the last run",
  test: "a test",
};
const when = (iso?: string | null) =>
  iso ? serverDate(iso).toLocaleString("en-GB", { day: "numeric", month: "short", hour: "2-digit", minute: "2-digit" }) : "";

/** The area of the year-end screen a step's points and journals are in (lib/areas.ts keys) */
export const STEP_AREA: Record<string, string> = {
  books: "general", general: "general", industry: "general", opening: "opening", cis: "payroll", dla: "dla",
  fixed_assets: "fixed", stock: "stock", accruals: "accruals", payroll: "payroll", loans: "loans", vat: "vat", ct: "tax",
};

/** What the background checks found on this client, a summary only: the work itself stays in
 * the areas and tabs. Done: the steps that found something first, each opening its area; the steps that found nothing
 * folded into one line. Running: every step waiting, checking or done. Then the earlier runs and why each ran. */
export function ChecksPanel({ run, open, onClose, onOpenStep }: {
  run: CheckRun | null;
  open: boolean;
  onClose: () => void;
  /** Open the area a step's results are in */
  onOpenStep?: (key: string) => void;
}) {
  const [showQuiet, setShowQuiet] = useState(false);
  if (!run || run.status === "NONE") {
    return (
      <Modal isOpen={open} onClose={onClose} title="Checks on this client">
        <p className="text-xs text-slate-600">The checks have not run yet: they start once the client setup is complete.</p>
      </Modal>
    );
  }
  const keys = run.step_keys || [];
  const steps = (run.steps || []).map((label, i) => ({ key: keys[i], label })).filter((s) => s.key && s.key !== "save");
  const results = run.summary?.results || {};
  const running = run.status === "RUNNING";
  const failed = run.status === "FAILED";
  const current = keys.indexOf(run.step || "");
  const said = (key: string) => {
    const r = results[key];
    return [r?.points ? `${plural(r.points, "point")} to look at` : "",
            r?.journals ? `${plural(r.journals, "journal")} (${money(r.amount)})` : ""].filter(Boolean).join(", ");
  };
  const openStep = (key: string) => {
    onOpenStep?.(key);
    onClose();
  };

  const description = running ? "Running now: the areas are checked one after another."
    : `Last run ${when(run.started_at)}${run.summary?.seconds != null ? `, took ${run.summary.seconds}s` : ""}.`
      + (run.status === "DONE" ? ` ${plural(run.summary?.points ?? 0, "point")} to look at, ${plural(run.summary?.journals ?? 0, "journal")} proposed.` : "");

  // While running (or stopped): every step and where it is
  const progress = (
    <ol className="divide-y divide-slate-100 rounded-lg border border-slate-200 text-xs">
      {steps.map((s) => {
        const i = keys.indexOf(s.key);
        const state = failed && i === current ? "failed" : i < current ? "done" : i === current && running ? "running" : "waiting";
        return (
          <li key={s.key} className="flex items-center gap-2.5 px-3 py-1.5">
            {state === "done" ? <CheckCircle2 className="h-4 w-4 shrink-0 text-emerald-600" />
              : state === "running" ? <Loader2 className="h-4 w-4 shrink-0 animate-spin text-sky-600" />
              : state === "failed" ? <XCircle className="h-4 w-4 shrink-0 text-rose-600" />
              : <Circle className="h-4 w-4 shrink-0 text-slate-300" />}
            <span className={cn("flex-1", state === "waiting" ? "text-slate-400" : "font-medium text-slate-800")}>{s.label}</span>
            <span className="text-[11px] text-slate-500">
              {state === "running" ? "checking…" : state === "failed" ? "stopped here" : state === "waiting" ? "waiting" : ""}
            </span>
          </li>
        );
      })}
    </ol>
  );

  // Done: what found something, most to look at first; the rest in one line
  const weight = (key: string) => (results[key]?.journals || 0) * 1000 + (results[key]?.points || 0);
  const found = steps.filter((s) => weight(s.key) > 0).sort((a, b) => weight(b.key) - weight(a.key));
  const quiet = steps.filter((s) => weight(s.key) === 0);
  const summary = (
    <>
      {found.length > 0 && (
        <>
          <p className="mb-1 text-[11px] text-slate-500">Found something: click to open the area</p>
          <ul className="divide-y divide-slate-100 rounded-lg border border-slate-200 text-xs">
            {found.map((s) => {
              const r = results[s.key];
              return (
                <li key={s.key}>
                  <button type="button" onClick={() => openStep(s.key)} disabled={!onOpenStep}
                          className="flex w-full items-center gap-2.5 px-3 py-2 text-left enabled:hover:bg-slate-50">
                    {r.journals ? <FileText className="h-4 w-4 shrink-0 text-sky-600" />
                      : <AlertCircle className="h-4 w-4 shrink-0 text-orange-500" />}
                    <span className="w-44 shrink-0 font-medium text-slate-800">{s.label}</span>
                    <span className={cn("min-w-0 flex-1 truncate", r.journals ? "text-sky-800" : "text-orange-700")}>{said(s.key)}</span>
                    {onOpenStep && <ChevronRight className="h-4 w-4 shrink-0 text-slate-400" />}
                  </button>
                </li>
              );
            })}
          </ul>
        </>
      )}
      {quiet.length > 0 && (
        <div className="mt-2 rounded-lg bg-emerald-50 text-xs text-emerald-800">
          <button type="button" onClick={() => setShowQuiet(!showQuiet)}
                  className="flex w-full items-center gap-2.5 px-3 py-2 text-left">
            <CheckCircle2 className="h-4 w-4 shrink-0 text-emerald-600" />
            <span className="flex-1 font-medium">
              {found.length ? `${plural(quiet.length, "area")}: nothing found` : "Every area checked: nothing found"}
            </span>
            <ChevronDown className={cn("h-4 w-4 shrink-0 transition-transform", showQuiet && "rotate-180")} />
          </button>
          {showQuiet && <p className="px-3 pb-2 pl-9 text-[11px] text-emerald-700">{quiet.map((s) => s.label).join(", ")}</p>}
        </div>
      )}
    </>
  );

  return (
    <Modal isOpen={open} onClose={onClose} title="Checks on this client" description={description}>
      {run.status === "DONE" ? summary : progress}
      {failed && run.error && (
        <p className="mt-2 rounded-md bg-rose-50 px-3 py-2 text-[11px] text-rose-800">The checks stopped: {run.error}</p>
      )}
      {run.history && run.history.length > 1 && (
        <div className="mt-4">
          <p className="mb-1 text-[11px] font-semibold text-slate-500">Earlier runs</p>
          <ul className="space-y-0.5 text-[11px] text-slate-600">
            {run.history.slice(1).map((h) => (
              <li key={h.id} className="flex gap-2">
                <span className="w-32 shrink-0 tabular-nums">{when(h.started_at)}</span>
                <span className="flex-1">after {WHY[h.trigger || ""] || h.trigger || "a run"}</span>
                <span className={cn(h.status === "FAILED" ? "text-rose-600" : "text-slate-400")}>
                  {h.status === "FAILED" ? "stopped" : h.seconds != null ? `${h.seconds}s` : h.status.toLowerCase()}
                </span>
              </li>
            ))}
          </ul>
        </div>
      )}
    </Modal>
  );
}
