// Small shared parts of the Books tab: the view and chart types, the stat tile, search match, pager and empty text.

import { Pagination } from "@/components/common/Pagination";
import { UsePaginationResult } from "@/hooks/usePagination";
import { BooksData } from "@/lib/api";
import { formatCurrency } from "@/lib/formatters";
import { cn } from "@/lib/utils";

export type View = "bank" | "ai" | "sales" | "bills" | "opening" | "questions";

export type Chart = BooksData["chart"];

export function Stat({ label, value, warn }: { label: string; value: string; warn?: boolean }) {
  return (
    <div className={cn("rounded-xl border px-3 py-2.5", warn ? "border-amber-200 bg-amber-50/60" : "border-slate-100 bg-slate-50")}>
      <p className="text-[11px] text-slate-500">{label}</p>
      <p className={cn("text-lg font-semibold tabular-nums", warn ? "text-amber-700" : "text-slate-900")}>{value}</p>
    </div>
  );
}

export function amount(r: { money_in: number; money_out: number }) {
  return r.money_in ? `+${formatCurrency(r.money_in, { currencySymbol: "" })}` : `-${formatCurrency(r.money_out, { currencySymbol: "" })}`;
}

/** Lines matching the search: every word somewhere in the row's text. */
export function matches(text: string, search: string) {
  const t = text.toLowerCase();
  return search.toLowerCase().split(/\s+/).filter(Boolean).every((w) => t.includes(w));
}

export function Pager({ p, label }: { p: UsePaginationResult<unknown>; label: string }) {
  if (p.totalItems <= 25) return null;
  return (
    <Pagination
      currentPage={p.currentPage} pageSize={p.pageSize} totalPages={p.totalPages} totalItems={p.totalItems}
      startIndex={p.startIndex} endIndex={p.endIndex} pageRange={p.pageRange} canPrevPage={p.canPrevPage}
      canNextPage={p.canNextPage} onPageChange={p.setPage} onPageSizeChange={p.setPageSize} onPrevPage={p.prevPage}
      onNextPage={p.nextPage} onFirstPage={p.firstPage} onLastPage={p.lastPage} pageSizeOptions={[25, 50, 100]} itemLabel={label}
    />
  );
}

export function Empty({ text }: { text: string }) {
  return <p className="px-5 py-10 text-center text-xs text-slate-500">{text}</p>;
}
