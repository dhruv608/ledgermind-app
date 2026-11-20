"use client";

import { useState } from "react";
import { Check, FileText, HelpCircle, Loader2, MessageSquare, X, XCircle } from "lucide-react";
import { assistantApi, type ChatAction, type ChatMessage } from "@/lib/api/assistant";
import { cn } from "@/lib/utils";
import { formatCurrency } from "@/lib/formatters";

const ICON = { propose_journal: FileText, journal_decision: FileText, clear_point: Check, raise_query: HelpCircle,
               add_note: MessageSquare };
const money = (n: number) => formatCurrency(n);

/** Work the assistant prepared, shown for the accountant to check: nothing happens until they press Confirm. After a
 *  decision the card says what was done (and the page's figures are read again). */
export function ActionCard({ messageId, action, onDecided }: {
  messageId: number | string; action: ChatAction; onDecided: (m: ChatMessage) => void;
}) {
  const [busy, setBusy] = useState<"CONFIRM" | "CANCEL" | null>(null);
  const [error, setError] = useState("");
  const Icon = ICON[action.kind] || FileText;
  const waiting = action.status === "WAITING";

  const decide = async (decision: "CONFIRM" | "CANCEL") => {
    setBusy(decision);
    setError("");
    try {
      onDecided(await assistantApi.decideAction(messageId, action.id, decision));
      if (decision === "CONFIRM") window.dispatchEvent(new CustomEvent("assistant-action"));
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(null);
    }
  };

  return (
    <div className={cn("mt-3 overflow-hidden rounded-lg border text-[12.5px]",
                       waiting ? "border-amber-300 bg-amber-50/40" : "border-slate-200 bg-slate-50/60")}>
      <div className="flex items-start gap-2 px-3 py-2">
        <Icon className={cn("mt-0.5 h-3.5 w-3.5 shrink-0", waiting ? "text-amber-700" : "text-slate-400")} />
        <div className="min-w-0 flex-1">
          <p className="font-semibold text-slate-800">
            {action.title}
            {action.point && <span className="ml-1.5 font-normal text-slate-500">on {action.point}</span>}
          </p>
          <p className="mt-0.5 text-slate-700">{action.text}</p>
          {action.why && <p className="mt-0.5 text-slate-500">{action.why}</p>}
        </div>
        {!action.lines && action.total ? <span className="shrink-0 font-medium tabular-nums text-slate-700">{money(action.total)}</span> : null}
      </div>
      {action.lines && (
        <table className="w-full border-t border-slate-200 bg-white text-[12px]">
          <thead>
            <tr className="text-left text-[10.5px] uppercase tracking-wide text-slate-400">
              <th className="px-3 py-1 font-medium">Account</th>
              <th className="px-3 py-1 text-right font-medium">Dr</th>
              <th className="px-3 py-1 text-right font-medium">Cr</th>
            </tr>
          </thead>
          <tbody>
            {action.lines.map((l, i) => (
              <tr key={i} className="border-t border-slate-100">
                <td className="px-3 py-1 text-slate-700"><span className="tabular-nums text-slate-400">{l.account_code}</span> {l.account_name}</td>
                <td className="px-3 py-1 text-right tabular-nums">{l.debit ? money(l.debit) : ""}</td>
                <td className="px-3 py-1 text-right tabular-nums">{l.credit ? money(l.credit) : ""}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
      <div className="flex items-center gap-2 border-t border-slate-200 px-3 py-2">
        {waiting ? (
          <>
            <span className="flex-1 text-[11px] text-amber-800">Nothing is done until you confirm.</span>
            <button type="button" disabled={busy !== null} onClick={() => decide("CANCEL")}
                    className="rounded-md px-2.5 py-1 text-xs font-medium text-slate-600 hover:bg-slate-100 disabled:opacity-50">
              Cancel
            </button>
            <button type="button" disabled={busy !== null} onClick={() => decide("CONFIRM")}
                    className="inline-flex items-center gap-1 rounded-md bg-teal-700 px-2.5 py-1 text-xs font-semibold text-white hover:bg-teal-800 disabled:opacity-50">
              {busy === "CONFIRM" ? <Loader2 className="h-3 w-3 animate-spin" /> : <Check className="h-3 w-3" />}
              Confirm
            </button>
          </>
        ) : (
          <p className={cn("flex flex-1 items-center gap-1.5 text-[11.5px]",
                           action.status === "DONE" ? "text-teal-800" : action.status === "FAILED" ? "text-red-700" : "text-slate-500")}>
            {action.status === "DONE" ? <Check className="h-3 w-3" /> : action.status === "FAILED" ? <XCircle className="h-3 w-3" /> : <X className="h-3 w-3" />}
            {action.status === "CANCELLED" ? "Cancelled" : action.result}
            {action.decided_by && <span className="text-slate-400">· {action.decided_by}</span>}
          </p>
        )}
      </div>
      {error && <p className="border-t border-red-100 bg-red-50 px-3 py-1.5 text-[11.5px] text-red-700">{error}</p>}
    </div>
  );
}
