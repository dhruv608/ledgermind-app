"use client";

import { AlertTriangle, ChevronDown, Loader2, Lock, ShieldCheck } from "lucide-react";
import { SetupStatus } from "@/types/engagement";
import { cn } from "@/lib/utils";
import { plural } from "@/lib/formatters";

/** The live panel beside the setup steps: what still blocks the review, warnings, and which checks are switched on. */
export function SetupStatusPanel({ status, loading }: { status: SetupStatus | null; loading: boolean }) {
  if (!status) {
    return loading ? (
      <div className="flex items-start gap-2 rounded-xl border border-slate-200 bg-white p-3 text-xs text-slate-600" aria-busy="true">
        <Loader2 className="mt-0.5 h-3.5 w-3.5 shrink-0 animate-spin text-teal-600" />
        <span>
          <span className="block font-semibold text-slate-800">Working out the checks…</span>
          Which checks run for this client, and what the review still waits for.
        </span>
      </div>
    ) : (
      <div className="rounded-xl border border-slate-200 bg-slate-50 p-4 text-xs text-slate-500">No status yet.</div>
    );
  }
  const on = status.activated.filter((a) => a.state === "on");
  const unknown = status.activated.filter((a) => a.state === "unknown");
  return (
    <div className={cn("space-y-3 transition-opacity", loading && "opacity-60")}>
      {status.gaps.length > 0 ? (
        <div className="rounded-xl border border-rose-200 bg-rose-50 p-3">
          <p className="mb-1.5 flex items-center gap-1.5 text-xs font-semibold text-rose-800">
            <Lock className="h-3.5 w-3.5" /> The review waits for {plural(status.gaps.length, "answer")}
          </p>
          <ul className="space-y-1 text-[11px] text-rose-900">
            {status.gaps.map((g) => (
              <li key={g} className="flex gap-1.5"><span>•</span>{g}</li>
            ))}
          </ul>
        </div>
      ) : (
        <div className="flex items-center gap-1.5 rounded-xl border border-emerald-200 bg-emerald-50 p-3 text-xs font-semibold text-emerald-800">
          <ShieldCheck className="h-4 w-4" /> Setup complete: the review can run
        </div>
      )}

      {status.warnings.length > 0 && (
        <div className="rounded-xl border border-amber-200 bg-amber-50 p-3">
          <p className="mb-1.5 flex items-center gap-1.5 text-xs font-semibold text-amber-800">
            <AlertTriangle className="h-3.5 w-3.5" /> Warnings
          </p>
          <ul className="space-y-1 text-[11px] text-amber-900">
            {status.warnings.map((w) => (
              <li key={w} className="flex gap-1.5"><span>•</span>{w}</li>
            ))}
          </ul>
        </div>
      )}

      <details className="group rounded-xl border border-slate-200 bg-white">
        <summary className="flex cursor-pointer list-none items-center justify-between px-3 py-2.5 text-xs font-semibold text-slate-800">
          <span>
            Checks that will run <span className="font-normal text-slate-400">{on.length + unknown.length}</span>
          </span>
          <ChevronDown className="h-3.5 w-3.5 text-slate-400 transition group-open:rotate-180" />
        </summary>
        <ul className="space-y-2 border-t border-slate-100 px-3 py-2.5">
          {on.map((a) => (
            <li key={a.id} className="text-[11px]" title={a.rules}>
              <span className="flex items-center gap-1.5 font-medium text-slate-800">
                <span className="h-1.5 w-1.5 shrink-0 rounded-full bg-emerald-500" />
                {a.engine}
              </span>
              <span className="block pl-3 text-slate-500">{a.reason}</span>
            </li>
          ))}
          {unknown.map((a) => (
            <li key={a.id} className="text-[11px]" title={a.rules}>
              <span className="flex items-center gap-1.5 font-medium text-slate-800">
                <span className="h-1.5 w-1.5 shrink-0 rounded-full bg-amber-400" />
                {a.engine}
              </span>
              <span className="block pl-3 text-slate-500">Runs until the setup says it is not needed</span>
            </li>
          ))}
        </ul>
      </details>
    </div>
  );
}
