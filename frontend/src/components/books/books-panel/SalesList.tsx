// The customers and their sales invoices: what each owes, and how each invoice was paid.

import { useMemo } from "react";
import { usePagination, UsePaginationResult } from "@/hooks/usePagination";
import { BooksData } from "@/lib/api";
import { formatCurrency, formatDate } from "@/lib/formatters";
import { cn } from "@/lib/utils";
import { Empty, Pager, matches } from "./common";

export function SalesList({ data, onlyUnpaid, search }: { data: BooksData; onlyUnpaid: boolean; search: string }) {
  const invoices = useMemo(() => (onlyUnpaid ? data.invoices.filter((i) => i.outstanding > 0.005) : data.invoices)
    .filter((i) => !search || matches(`${i.customer} ${i.number}`, search))
    .slice().sort((a, b) => a.customer.localeCompare(b.customer) || a.date.localeCompare(b.date)), [data.invoices, onlyUnpaid, search]);
  const customers = data.customers.filter((c) => !search || matches(c.customer, search));
  const pager = usePagination({ items: invoices, initialPageSize: 25, resetDependencies: [onlyUnpaid, search] });
  const tone = (s: string) => (s === "Paid" ? "text-emerald-700" : s === "Part-paid" ? "text-amber-700" : "text-rose-700");
  return (
    <div className="text-xs">
      <p className="border-b border-slate-100 px-5 pb-2 pt-3 text-[11px] font-semibold uppercase tracking-wide text-slate-500">Customers</p>
      <div className="overflow-x-auto">
        <table className="w-full">
          <thead className="border-b border-slate-200 bg-slate-50 text-left text-[11px] uppercase tracking-wide text-slate-500">
            <tr>
              <th className="px-5 py-2 font-semibold">Customer</th>
              <th className="px-3 py-2 text-right font-semibold">Last year</th>
              <th className="px-3 py-2 text-right font-semibold">Invoiced</th>
              <th className="px-3 py-2 text-right font-semibold">Received</th>
              <th className="px-3 py-2 text-right font-semibold">Owes</th>
              <th className="px-3 py-2 font-semibold">Status</th>
            </tr>
          </thead>
          <tbody>
            {customers.map((c) => (
              <tr key={c.customer} className="border-b border-slate-100 hover:bg-slate-50/60">
                <td className="px-5 py-2 font-medium text-slate-800">{c.customer}</td>
                <td className="px-3 py-2 text-right tabular-nums">{formatCurrency(c.brought_forward, { currencySymbol: "" })}</td>
                <td className="px-3 py-2 text-right tabular-nums">{formatCurrency(c.invoiced, { currencySymbol: "" })}</td>
                <td className="px-3 py-2 text-right tabular-nums">{formatCurrency(c.received, { currencySymbol: "" })}</td>
                <td className="px-3 py-2 text-right font-medium tabular-nums">{formatCurrency(c.position, { currencySymbol: "", accountingStyle: true })}</td>
                <td className={cn("px-3 py-2", c.status === "Settled" ? "text-emerald-700" : c.status === "Overpaid" ? "text-amber-700" : "text-rose-700")}>
                  {c.status}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <p className="border-b border-slate-100 px-5 pb-2 pt-5 text-[11px] font-semibold uppercase tracking-wide text-slate-500">
        {onlyUnpaid ? "Unpaid invoices" : "Invoices"}
      </p>
      {invoices.length === 0 ? (
        <Empty text={search ? "No invoice matches the search." : "Every invoice is paid."} />
      ) : (
        <div className="overflow-x-auto">
          <table className="w-full">
            <thead className="border-b border-slate-200 bg-slate-50 text-left text-[11px] uppercase tracking-wide text-slate-500">
              <tr>
                <th className="px-5 py-2 font-semibold">Date</th>
                <th className="px-3 py-2 font-semibold">Invoice</th>
                <th className="px-3 py-2 font-semibold">Customer</th>
                <th className="px-3 py-2 text-right font-semibold">Amount</th>
                <th className="px-3 py-2 font-semibold">Status</th>
                <th className="px-3 py-2 font-semibold">Paid by</th>
              </tr>
            </thead>
            <tbody>
              {pager.paginatedItems.map((i, n) => (
                <tr key={`${i.number}-${i.customer}-${n}`} className="border-b border-slate-100 hover:bg-slate-50/60">
                  <td className="px-5 py-2 text-slate-500">{formatDate(i.date, "short")}</td>
                  <td className="px-3 py-2">{i.number || (i.last_year ? "last year" : "-")}</td>
                  <td className="px-3 py-2 font-medium text-slate-800">{i.customer}</td>
                  <td className="px-3 py-2 text-right tabular-nums">{formatCurrency(i.amount, { currencySymbol: "" })}</td>
                  <td className={cn("px-3 py-2 font-medium", tone(i.status))}>{i.status}{i.last_year ? " (last year)" : ""}</td>
                  <td className="px-3 py-2 text-slate-500">
                    {i.paid_by.length
                      ? i.paid_by.map((p) => `${formatDate(p.date, "short")} £${p.amount.toFixed(2)} (${p.rule})`).join(", ")
                      : i.outstanding > 0.005 ? "Owed at the year end" : ""}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
          <Pager p={pager as UsePaginationResult<unknown>} label="invoices" />
        </div>
      )}
    </div>
  );
}
