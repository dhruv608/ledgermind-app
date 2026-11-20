// The supplier bills: paid or not, and what each one is.

import { useMemo, useState } from "react";
import { Check, Loader2, RotateCcw } from "lucide-react";
import { usePagination, UsePaginationResult } from "@/hooks/usePagination";
import { BooksBill } from "@/lib/api";
import { formatCurrency, formatDate } from "@/lib/formatters";
import { cn } from "@/lib/utils";
import { Chart, Empty, Pager, matches } from "./common";
import { HeadPicker } from "./HeadPicker";

export function BillsList({ bills, choices, chart, onlyToCheck, search, saving, onChoose }: {
  bills: BooksBill[];
  choices: string[];
  chart: Chart;
  onlyToCheck: boolean;
  search: string;
  saving: string | null;
  onChoose: (key: string, value: Record<string, unknown> | null) => void;
}) {
  const [changing, setChanging] = useState<string | null>(null);
  const shown = useMemo(() => (onlyToCheck ? bills.filter((b) => b.check || b.outstanding > 0.005) : bills)
    .filter((b) => !search || matches(`${b.supplier} ${b.number} ${b.head}`, search))
    .slice().sort((a, b) => Number(b.check) - Number(a.check) || a.date.localeCompare(b.date)), [bills, onlyToCheck, search]);
  const pager = usePagination({ items: shown, initialPageSize: 25, resetDependencies: [onlyToCheck, search] });
  if (!shown.length) return <Empty text={search ? "No bill matches the search." : "Nothing to check: every bill has a type and is paid."} />;
  return (
    <div className="text-xs">
      <div className="hidden grid-cols-[80px_minmax(0,1fr)_90px_90px_220px] gap-3 border-b border-slate-200 bg-slate-50 px-5 py-2.5 text-[11px] font-semibold uppercase tracking-wide text-slate-500 sm:grid">
        <span>Date</span><span>Supplier</span><span className="text-right">Amount</span><span>Status</span><span>What it is</span>
      </div>
      {pager.paginatedItems.map((b) => {
        const busy = saving === b.key;
        const open = !b.last_year && (b.check || changing === b.key);
        return (
          <div key={b.key + b.date} className={cn("grid gap-2 border-b border-slate-100 px-5 py-2.5 transition hover:bg-slate-50/60 sm:grid-cols-[80px_minmax(0,1fr)_90px_90px_220px] sm:gap-3", b.check && "bg-amber-50/60 hover:bg-amber-50")}>
            <span className="text-slate-500">{formatDate(b.date, "short")}</span>
            <div className="min-w-0">
              <p className="truncate font-medium text-slate-800">{b.supplier}</p>
              <p className="text-[11px] text-slate-500">{b.number || "no invoice number"}{b.vat ? ` · VAT £${b.vat.toFixed(2)}` : ""}</p>
            </div>
            <span className="tabular-nums sm:text-right">{formatCurrency(b.amount, { currencySymbol: "" })}</span>
            <span className={cn("font-medium", b.status === "Paid" ? "text-emerald-700" : b.status === "Part-paid" ? "text-amber-700" : "text-rose-700")}>
              {b.status}
            </span>
            <div className="flex items-center gap-1.5">
              {busy ? (
                <Loader2 className="h-4 w-4 animate-spin text-slate-400" />
              ) : open ? (
                <HeadPicker value={b.picked} code={b.code} choices={choices.filter((c) => c !== "Sales (no invoice)" && c !== "Transfer between own accounts")} chart={chart} onPick={(choice) => { setChanging(null); onChoose(b.key, choice); }} />
              ) : (
                <button onClick={() => !b.last_year && setChanging(b.key)} className="flex min-w-0 items-center gap-1 text-left text-emerald-700 hover:underline">
                  <Check className="h-3.5 w-3.5 shrink-0" /> <span className="truncate">{b.head}</span>
                </button>
              )}
              {b.chosen && !busy && (
                <button onClick={() => onChoose(b.key, null)} className="text-slate-400 hover:text-slate-700" title="Undo">
                  <RotateCcw className="h-3.5 w-3.5" />
                </button>
              )}
            </div>
          </div>
        );
      })}
      <Pager p={pager as UsePaginationResult<unknown>} label="bills" />
    </div>
  );
}
