"use client";

import { RefreshCw } from "lucide-react";
import type { CheckRun } from "@/lib/api/checks";

/**
 * While LM checks the client again after a change: a big change (new files, the client details) covers the whole
 * page; a small one (one mapping, one journal) covers only the parts being redone (the points, journals and papers),
 * so the rest of the page stays usable. The bar is LM's own progress: the step it is on, never a spinner with no end.
 */
export function UpdatingBar({ checks }: { checks: CheckRun }) {
  const total = checks.steps_total || 1;
  const at = Math.min((checks.steps_done ?? 0) + 1, total);
  return (
    <div role="status" aria-live="polite" className="w-full max-w-sm rounded-xl border border-teal-100 bg-white px-4 py-3 shadow-md">
      <div className="flex items-center justify-between gap-3 text-xs">
        <span className="flex items-center gap-1.5 font-bold text-slate-800">
          <RefreshCw className="h-3.5 w-3.5 animate-spin text-teal-700" aria-hidden="true" /> Updating
        </span>
        <span className="truncate text-slate-500">{checks.step_label || "Checking"} · step {at} of {total}</span>
      </div>
      <div className="mt-2 h-1.5 overflow-hidden rounded-full bg-slate-100">
        <div className="h-full rounded-full bg-teal-600 transition-all duration-500" style={{ width: `${(100 * at) / total}%` }} />
      </div>
      <p className="mt-1.5 text-[11px] text-slate-500">LM is checking the client again after your change. This part updates by itself when it is done.</p>
    </div>
  );
}

/** Covers its parent (which must be relative) with a blur and the bar; clicks on what is under it wait */
export function UpdatingCover({ checks, whole = false }: { checks: CheckRun; whole?: boolean }) {
  return (
    <div className={whole
      ? "fixed inset-0 z-40 grid place-items-center bg-white/50 p-4 backdrop-blur-[2px]"
      : "absolute inset-0 z-20 flex items-start justify-center rounded-xl bg-white/50 p-4 pt-10 backdrop-blur-[2px]"}>
      <UpdatingBar checks={checks} />
    </div>
  );
}
