"use client";

import { Sparkles } from "lucide-react";
import { cn } from "@/lib/utils";

/**
 * Ask Ledge (the assistant) about something on the screen: the panel opens and asks the question, with the figures on
 * the screen written into it so the answer is about this job and this figure. Every screen asks through here (the
 * assistant panel listens for the 'assistant-ask' event), so asking works the same everywhere.
 */
export function askLedge(question: string) {
  window.dispatchEvent(new CustomEvent("assistant-ask", { detail: question }));
}

/** The Ask Ledge button: a labelled one (beside a working paper's figures) or a small icon (on a row) */
export function AskLedge({ question, label = "Ask Ledge", icon = false, className }: {
  question: string;
  label?: string;
  /** Only the icon (rows: a difference, a ledger line) */
  icon?: boolean;
  className?: string;
}) {
  return (
    <button type="button" title={icon ? label : undefined} aria-label={label}
            onClick={(e) => { e.stopPropagation(); askLedge(question); }}
            className={cn(icon
              ? "inline-flex h-6 w-6 items-center justify-center rounded-md text-slate-400 transition hover:bg-teal-50 hover:text-teal-700"
              : "inline-flex h-7 items-center gap-1 rounded-md px-2 text-xs font-medium text-slate-500 transition hover:bg-teal-50 hover:text-teal-800",
              className)}>
      <Sparkles className="h-3.5 w-3.5" />{!icon && label}
    </button>
  );
}
