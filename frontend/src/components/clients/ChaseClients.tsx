"use client";

// The returns waiting on client answers, each with the message asking for them (the Queries page's own wording), ready
// to copy into an email or WhatsApp. Nothing is sent from here.
import { useState } from "react";
import { ArrowRight, Check, Copy } from "lucide-react";
import { Modal } from "@/components/ui/dialog";
import type { SaJob, SaJobStatus } from "@/lib/api";
import { plural } from "@/lib/formatters";

export function ChaseClients({ open, onClose, jobs, status, onOpenReturn }: {
  open: boolean;
  onClose: () => void;
  jobs: SaJob[];
  status: Record<string, SaJobStatus> | null;
  onOpenReturn: (id: string) => void;
}) {
  const [copied, setCopied] = useState<string | null>(null);
  const waiting = jobs.filter((j) => status?.[j.id]?.message).sort((a, b) => a.person_name.localeCompare(b.person_name));

  const copy = async (id: string, text: string) => {
    try {
      await navigator.clipboard.writeText(text);
      setCopied(id);
      setTimeout(() => setCopied((c) => (c === id ? null : c)), 1600);
    } catch { /* no clipboard: the text can still be selected */ }
  };

  return (
    <Modal isOpen={open} onClose={onClose} title="Chase client answers"
           description={`${plural(waiting.length, "return is", "returns are")} waiting on the client. Copy each message into an email or WhatsApp.`}>
      <div className="space-y-3">
        {waiting.map((j) => {
          const s = status![j.id];
          return (
            <div key={j.id} className="rounded-xl border border-slate-200">
              <div className="flex items-center justify-between gap-2 border-b border-slate-100 px-4 py-2.5">
                <div className="min-w-0">
                  <p className="truncate text-sm font-semibold text-slate-900">{j.person_name}</p>
                  <p className="text-[11.5px] text-slate-500">{j.tax_year}, {plural(s.client || 0, "question")}</p>
                </div>
                <div className="flex shrink-0 items-center gap-1">
                  <button type="button" onClick={() => copy(j.id, s.message!)}
                          className="inline-flex items-center gap-1 rounded-lg border border-slate-200 px-2.5 py-1 text-xs text-slate-700 transition hover:border-teal-300 hover:text-teal-800">
                    {copied === j.id ? <Check className="h-3.5 w-3.5 text-teal-700" /> : <Copy className="h-3.5 w-3.5" />}
                    {copied === j.id ? "Copied" : "Copy"}
                  </button>
                  <button type="button" onClick={() => onOpenReturn(j.id)} title="Open the return's Queries"
                          className="inline-flex items-center gap-1 rounded-lg px-2 py-1 text-xs text-slate-500 transition hover:bg-slate-100 hover:text-slate-800">
                    Open <ArrowRight className="h-3 w-3" />
                  </button>
                </div>
              </div>
              <pre className="max-h-48 overflow-y-auto whitespace-pre-wrap px-4 py-3 font-sans text-[12.5px] leading-relaxed text-slate-700">{s.message}</pre>
            </div>
          );
        })}
      </div>
    </Modal>
  );
}
