// The year on one account: opening, this year's lines by type, journals and closing, checked against the trial balance.
import { useEffect, useState } from "react";
import { AlertTriangle, CheckCircle2 } from "lucide-react";
import { SkeletonRows } from "@/components/common/SkeletonRows";
import { api, Rollforward } from "@/lib/api";
import { cn } from "@/lib/utils";
import { money } from "@/components/control-accounts/reconciliations/shared";

/** The account's year: opening + this year's ledger lines by type + approved journals = closing, and whether the
 *  opening and the lines come to the trial balance (as the workbook's B3 sheet checks). */
export function RollforwardBox({ engagementId, codes, books }: { engagementId: string; codes: number[]; books: number }) {
  const [rf, setRf] = useState<Rollforward | null>(null);
  const [error, setError] = useState<string | null>(null);
  const key = codes.join(",");
  // Another job or account: clear the old figures at once (during render), then load the new ones
  const [shownFor, setShownFor] = useState(`${engagementId}|${key}`);
  if (`${engagementId}|${key}` !== shownFor) {
    setShownFor(`${engagementId}|${key}`);
    setRf(null);
    setError(null);
  }
  useEffect(() => {
    api.getRollforward(engagementId, key.split(",").map(Number)).then(setRf).catch((e) => setError(e.message));
  }, [engagementId, key]);

  if (error) return <p className="text-[11px] text-rose-700">{error}</p>;
  if (!rf) return <SkeletonRows rows={3} />;
  const line = "flex items-baseline justify-between gap-3 py-1";
  const amount = "whitespace-nowrap font-mono";
  return (
    <div className="rounded-md border border-slate-200 text-xs">
      <p className="border-b border-slate-100 bg-slate-50 px-3 py-1.5 text-[11px] font-semibold uppercase tracking-wide text-slate-500">
        The year on this account
      </p>
      <div className="divide-y divide-slate-100 px-3">
        <div className={line}>
          <span className="text-slate-700">
            Opening balance
            <span className="ml-1.5 text-[11px] text-slate-400">
              {rf.opening_source ? `from ${rf.opening_source}` : "worked out: closing less this year's lines"}
            </span>
          </span>
          <span className={amount}>{money(rf.opening)}</span>
        </div>
        {rf.movements.map((m) => (
          <div key={m.type} className={line}>
            <span className="text-slate-600">
              {m.type}
              <span className="ml-1.5 text-[11px] text-slate-400">{m.lines} line{m.lines === 1 ? "" : "s"}</span>
            </span>
            <span className={amount}>{money(m.net)}</span>
          </div>
        ))}
        {rf.lines === 0 && (
          <div className={line}>
            <span className="text-slate-400">No ledger lines this year</span>
            <span className={amount}>-</span>
          </div>
        )}
        {rf.journal_lines
          ? rf.journal_lines.map((j) => (
              <div key={j.label} className={line}>
                <span className={j.label === "Depreciation for the year" ? "font-medium text-slate-800" : "text-slate-600"}>
                  {j.label}
                  {j.note && <span className="ml-1.5 text-[11px] text-amber-700">{j.note}</span>}
                </span>
                <span className={amount}>{j.amount === null ? "-" : money(j.amount)}</span>
              </div>
            ))
          : Math.abs(rf.journals) >= 0.005 && (
              <div className={line}>
                <span className="text-slate-600">Journals approved in the app</span>
                <span className={amount}>{money(rf.journals)}</span>
              </div>
            )}
        <div className={cn(line, "font-semibold text-slate-900")}>
          <span>Closing balance</span>
          <span className={amount}>{money(rf.closing)}</span>
        </div>
      </div>
      {rf.difference === null ? (
        <p className="border-t border-slate-100 px-3 py-1.5 text-[11px] text-slate-500">
          No opening balance to check against: enter last year&apos;s job or upload a trial balance with opening balances.
        </p>
      ) : Math.abs(rf.difference) < 0.01 ? (
        <p className="border-t border-slate-100 px-3 py-1.5 text-[11px] text-emerald-700">
          <CheckCircle2 className="mr-1 inline h-3 w-3" />
          Opening + this year&apos;s lines = the trial balance
        </p>
      ) : (
        <p className="border-t border-rose-100 bg-rose-50 px-3 py-1.5 text-[11px] font-medium text-rose-700">
          <AlertTriangle className="mr-1 inline h-3 w-3" />
          Opening + lines is {money(rf.difference)} away from the trial balance ({money(rf.tb_closing)}): lines missing from
          the ledger, or the opening balance is not last year&apos;s closing.
        </p>
      )}
      {Math.abs(Math.abs(rf.closing) - Math.abs(books)) >= 0.01 && (
        <p className="border-t border-slate-100 px-3 py-1.5 text-[11px] text-slate-500">
          The closing here is the account code&apos;s balance; the row above shows {money(books)}.
        </p>
      )}
    </div>
  );
}
