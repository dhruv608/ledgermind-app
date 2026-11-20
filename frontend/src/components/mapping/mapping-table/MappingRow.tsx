// One account row of the mappings table: balances, last year, its code and actions, and the AI's top codes under it.
import React from "react";
import { Pencil, Check, Sparkles, Loader2 } from "lucide-react";
import { TBRecord } from "@/types/engagement";
import { LastYear } from "@/lib/api";
import { cn } from "@/lib/utils";
import { getMappingStatusBadge } from "@/lib/badges";
import { formatCurrency } from "@/lib/formatters";

type MappingOption = { std_code: number; std_name: string; confidence: number; reason: string };

export function MappingRow({
  rec,
  columns,
  showDrCr,
  hasLastYear,
  lastYear,
  ticked,
  toggleTick,
  confirmingAccount,
  optionsFor,
  setOptionsFor,
  options,
  loadingOptions,
  setSelectedDrawerAccount,
  setIsDrawerOpen,
  handleSingleConfirm,
  handleOpenReassign,
  showOptions,
  chooseOption,
}: {
  rec: TBRecord;
  columns: number;
  showDrCr: boolean;
  hasLastYear: boolean;
  lastYear: LastYear | null;
  ticked: Set<string>;
  toggleTick: (name: string) => void;
  confirmingAccount: string | null;
  optionsFor: string | null;
  setOptionsFor: (name: string | null) => void;
  options: MappingOption[];
  loadingOptions: boolean;
  setSelectedDrawerAccount: (rec: TBRecord | null) => void;
  setIsDrawerOpen: (open: boolean) => void;
  handleSingleConfirm: (e: React.MouseEvent, rec: TBRecord) => void;
  handleOpenReassign: (e: React.MouseEvent, rec: TBRecord) => void;
  showOptions: (e: React.MouseEvent, rec: TBRecord) => void;
  chooseOption: (rec: TBRecord, code: number, name: string) => void;
}) {
  const debit = Number(rec.debit_amount || 0);
  const credit = Number(rec.credit_amount || 0);
  const net = Number(rec.net_amount || 0);
  const status = getMappingStatusBadge(rec.mapping_status);
  const canConfirm = rec.std_code !== null && rec.mapping_status !== "MATCHED";

  return (
    <React.Fragment key={rec.id}>
    <tr
      onClick={() => {
        setSelectedDrawerAccount(rec);
        setIsDrawerOpen(true);
      }}
      className="group cursor-pointer transition hover:bg-teal-50/40"
      title="Click to see the ledger lines"
    >
      <td className="py-2 pl-5" onClick={(e) => e.stopPropagation()}>
        {canConfirm && (
          <input
            type="checkbox"
            checked={ticked.has(rec.raw_account_name)}
            onChange={() => toggleTick(rec.raw_account_name)}
            className="h-4 w-4 cursor-pointer rounded border-slate-300 accent-teal-700"
            aria-label={`Tick ${rec.raw_account_name}`}
          />
        )}
      </td>
      <td className="min-w-[200px] py-2 pl-3 pr-3 font-medium text-slate-900">{rec.raw_account_name}</td>
      {showDrCr && (
        <>
          <td className="whitespace-nowrap px-3 py-2 text-right font-mono text-slate-500">{debit > 0 ? formatCurrency(debit) : "—"}</td>
          <td className="whitespace-nowrap px-3 py-2 text-right font-mono text-slate-500">{credit > 0 ? formatCurrency(credit) : "—"}</td>
        </>
      )}
      <td className="whitespace-nowrap px-3 py-2 text-right font-mono font-semibold text-slate-900">{formatCurrency(net)}</td>
      {hasLastYear && (() => {
        const ly = lastYear?.accounts[rec.raw_account_name];
        const before = ly?.last_year;
        if (before === null || before === undefined)
          return (
            <>
              <td className="px-3 py-2 text-right text-slate-300">–</td>
              <td className="px-3 py-2 text-right text-slate-300">–</td>
            </>
          );
        const change = net - before;
        const pct = Math.abs(before) >= 0.005 ? Math.round((Math.abs(change) / Math.abs(before)) * 100) : null;
        return (
          <>
            <td className="whitespace-nowrap px-3 py-2 text-right font-mono text-slate-500">{formatCurrency(before)}</td>
            <td
              className={cn("whitespace-nowrap px-3 py-2 text-right font-mono", ly?.big ? "font-semibold text-orange-700" : "text-slate-500")}
              title={ly?.big ? "A big change: put to the client on the Review tab" : undefined}
            >
              {Math.abs(change) < 0.005 ? "—" : formatCurrency(change)}
              {Math.abs(change) >= 0.005 && (
                <span className="block text-[10px] font-normal">{pct === null ? "new" : Math.abs(net) < 0.005 ? "gone" : `${pct}%`}</span>
              )}
            </td>
          </>
        );
      })()}
      <td className="px-3 py-2">
        <div className="min-w-[220px] max-w-md" title={rec.mapping_reason || ""}>
          <div className="flex min-w-0 items-center gap-1.5">
            {rec.std_code !== null ? (
              <>
                <span className="shrink-0 rounded border border-teal-200 bg-teal-50 px-1.5 py-px font-mono text-[11px] font-bold text-teal-800">
                  {String(rec.std_code).padStart(4, "0")}
                </span>
                <span className="min-w-0 truncate font-medium text-slate-800">{rec.std_name}</span>
              </>
            ) : (
              <span className="italic text-slate-400">Not mapped</span>
            )}
            <span className={`shrink-0 rounded border px-1.5 py-px text-[10.5px] font-semibold ${status.className}`}>
              {status.label}
            </span>
          </div>
          {rec.mapping_reason && rec.mapping_status === "NEEDS_REVIEW" && (
            <p className="mt-0.5 truncate text-[11px] text-slate-500">{rec.mapping_reason}</p>
          )}
        </div>
      </td>
      <td className="sticky right-0 bg-white py-2 pl-3 pr-5 shadow-[-6px_0_6px_-6px_rgba(0,0,0,0.12)] group-hover:bg-teal-50">
        <div className="flex items-center justify-end gap-1">
          {canConfirm && (
            <button
              type="button"
              onClick={(e) => handleSingleConfirm(e, rec)}
              disabled={confirmingAccount === rec.raw_account_name}
              className="inline-flex h-7 items-center gap-1 rounded-md border border-emerald-200 bg-white px-2 text-[11px] font-medium text-emerald-700 transition hover:bg-emerald-50 disabled:opacity-50"
              title="The code is right: confirm it"
            >
              <Check className="h-3 w-3" /> Confirm
            </button>
          )}
          <button
            type="button"
            onClick={(e) => handleOpenReassign(e, rec)}
            className="inline-flex h-7 w-7 items-center justify-center rounded-md border border-slate-200 bg-white text-slate-600 transition hover:border-teal-300 hover:text-teal-800"
            title="Change the code" aria-label={`Change the code of ${rec.raw_account_name}`}
          >
            <Pencil className="h-3.5 w-3.5" />
          </button>
          {canConfirm && (
            <button
              type="button"
              onClick={(e) => showOptions(e, rec)}
              className="inline-flex h-7 w-7 items-center justify-center rounded-md border border-slate-200 bg-white text-slate-600 transition hover:border-teal-300 hover:text-teal-800"
              title="The top 3 suggested codes for this account" aria-label={`The top 3 suggested codes for ${rec.raw_account_name}`}
            >
              <Sparkles className="h-3.5 w-3.5" />
            </button>
          )}
        </div>
      </td>
    </tr>
    {optionsFor === rec.raw_account_name && (
      <tr className="bg-teal-50/40">
        <td colSpan={columns} className="px-5 py-2">
          {loadingOptions ? (
            <span className="inline-flex items-center gap-1.5 text-[11px] text-slate-500">
              <Loader2 className="h-3.5 w-3.5 animate-spin" /> Finding the top 3 codes…
            </span>
          ) : (
            <div className="sticky left-5 flex max-w-[calc(100vw-6rem)] flex-wrap items-center gap-2 lg:max-w-4xl">
              <span className="text-[11px] text-slate-500">Pick one:</span>
              {options.map((o) => (
                <button
                  key={o.std_code}
                  type="button"
                  onClick={() => chooseOption(rec, o.std_code, o.std_name)}
                  title={o.reason}
                  className="inline-flex items-center gap-1.5 rounded-lg border border-slate-200 bg-white px-2.5 py-1.5 text-left text-[11px] transition hover:border-emerald-400 hover:bg-emerald-50"
                >
                  <span className="font-mono font-bold text-teal-800">{String(o.std_code).padStart(4, "0")}</span>
                  <span className="text-slate-800">{o.std_name}</span>
                  <span className="font-mono text-slate-400">{Math.round(o.confidence * 100)}%</span>
                  {o.std_code === rec.std_code && <span className="text-emerald-700">(current)</span>}
                </button>
              ))}
              <button type="button" onClick={() => setOptionsFor(null)} className="text-[11px] text-slate-500 hover:underline">
                Close
              </button>
            </div>
          )}
        </td>
      </tr>
    )}
    </React.Fragment>
  );
}
