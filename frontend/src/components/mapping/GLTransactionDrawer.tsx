"use client";

import { useState, useEffect } from "react";
import { api } from "@/lib/api";
import {
  X,
  Search,
  Receipt,
} from "lucide-react";
import { SkeletonRows } from "@/components/common/SkeletonRows";
import { formatCurrency } from "@/lib/formatters";
import { usePagination } from "@/hooks/usePagination";
import { PageControls } from "@/components/common/Pagination";

interface GLTransactionDrawerProps {
  isOpen: boolean;
  onClose: () => void;
  engagementId: string;
  accountName: string | null;
  stdCode: number | null;
  stdName: string | null;
  netAmount: number;
}

interface TransactionItem {
  id: number;
  raw_account_name: string;
  transaction_date: string;
  description: string;
  reference: string;
  source: string;
  debit_amount: number;
  credit_amount: number;
  net_amount: number;
}

// Lines read for one account: all of a normal year (VAT Control on a Shopify client: 1,517), so the totals are the
// account's, not of its first 500
const LEDGER_LIMIT = 5000;

/** The account's ledger lines; a "Parent:Leaf" name with none falls back to the leaf name's lines */
async function fetchLedger(engagementId: string, accountName: string): Promise<TransactionItem[]> {
  let data = await api.getTransactions(engagementId, accountName, LEDGER_LIMIT);
  if (data.length === 0 && accountName.includes(":")) {
    const leaf = accountName.split(":").pop()?.trim();
    if (leaf) {
      const fallbackData = await api.getTransactions(engagementId, leaf, LEDGER_LIMIT);
      if (fallbackData.length > 0) {
        data = fallbackData;
      }
    }
  }
  return data;
}

export function GLTransactionDrawer({
  isOpen,
  onClose,
  engagementId,
  accountName,
  stdCode,
  stdName,
  netAmount,
}: GLTransactionDrawerProps) {
  const [transactions, setTransactions] = useState<TransactionItem[]>([]);
  const [isLoading, setIsLoading] = useState(false);
  const [searchQuery, setSearchQuery] = useState("");

  // Opening (or another account): show loading at once; closing: clear the lines and the search. Done during render
  // so the effect below only fetches.
  const wanted = isOpen && accountName && engagementId ? `${engagementId}|${accountName}` : null;
  const [shownFor, setShownFor] = useState<string | null>(null);
  if (wanted !== shownFor) {
    setShownFor(wanted);
    if (wanted) {
      setIsLoading(true);
    } else {
      setTransactions([]);
      setSearchQuery("");
    }
  }

  useEffect(() => {
    if (!isOpen || !accountName || !engagementId) return;
    fetchLedger(engagementId, accountName)
      .then(setTransactions)
      .catch((err) => console.error("Failed to load transactions", err))
      .finally(() => setIsLoading(false));
  }, [isOpen, accountName, engagementId]);


  const filtered = transactions.filter((tx) => {
    if (!searchQuery.trim()) return true;
    const q = searchQuery.toLowerCase();
    return (
      (tx.description && tx.description.toLowerCase().includes(q)) ||
      (tx.reference && tx.reference.toLowerCase().includes(q)) ||
      (tx.source && tx.source.toLowerCase().includes(q)) ||
      (tx.transaction_date && tx.transaction_date.includes(q))
    );
  });
  // A big account has hundreds of lines: a page at a time, page 1 again when the search changes
  const page = usePagination({ items: filtered, initialPageSize: 50, resetDependencies: [searchQuery, transactions] });

  const totalDebits = filtered.reduce((acc, tx) => acc + (tx.debit_amount || 0), 0);
  const totalCredits = filtered.reduce((acc, tx) => acc + (tx.credit_amount || 0), 0);


  if (!isOpen) return null;

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-3 sm:p-5 overflow-y-auto">
      {/* Backdrop */}
      <div
        className="fixed inset-0 bg-slate-900/50 backdrop-blur-xs transition-opacity animate-in fade-in duration-200"
        onClick={onClose}
      />

      {/* Refined Proportional Spreadsheet Modal */}
      <div className="relative w-full max-w-4xl bg-white rounded-2xl shadow-2xl border border-slate-200 flex flex-col max-h-[80vh] animate-in zoom-in-95 duration-200 z-10 overflow-hidden">
        {/* Modal Top Header */}
        <div className="p-4 sm:p-5 border-b border-slate-200 bg-slate-50/80">
          <div className="flex items-start justify-between gap-4">
            <div>
              <div className="flex items-center space-x-2 flex-wrap gap-y-1">
                <span className="px-2 py-0.5 rounded-md text-xs font-mono font-bold bg-teal-100 text-teal-900 border border-teal-200 shadow-2xs">
                  {stdCode !== null ? `Code ${stdCode}` : "Unmapped"}
                </span>
                <h2 className="text-base font-bold text-slate-900 tracking-tight">
                  {accountName}
                </h2>
              </div>
              <p className="text-xs text-slate-500 mt-1">
                Mapped to:{" "}
                <span className="font-semibold text-slate-700">
                  {stdName || "Standard UK Code"}
                </span>
              </p>
            </div>

            <button
              onClick={onClose}
              className="p-1.5 text-slate-400 hover:text-slate-700 rounded-lg hover:bg-slate-200/70 transition cursor-pointer"
              title="Close modal"
            >
              <X className="w-5 h-5" />
            </button>
          </div>

          {/* KPI Summary Strip */}
          <div className="grid grid-cols-2 sm:grid-cols-4 gap-2.5 mt-3 pt-3 border-t border-slate-200/80 text-xs">
            <div className="bg-white p-2.5 rounded-xl border border-slate-200/80 shadow-2xs">
              <span className="text-slate-400 font-medium text-[11px] block">Net balance</span>
              <p className="text-sm font-bold font-mono text-slate-900 mt-0.5">{formatCurrency(netAmount)}</p>
            </div>
            <div className="bg-white p-2.5 rounded-xl border border-slate-200/80 shadow-2xs">
              <span className="text-slate-400 font-medium text-[11px] block">Money in (debits)</span>
              <p className="text-sm font-bold font-mono text-emerald-700 mt-0.5">{formatCurrency(totalDebits)}</p>
            </div>
            <div className="bg-white p-2.5 rounded-xl border border-slate-200/80 shadow-2xs">
              <span className="text-slate-400 font-medium text-[11px] block">Money out (credits)</span>
              <p className="text-sm font-bold font-mono text-slate-700 mt-0.5">{formatCurrency(totalCredits)}</p>
            </div>
            <div className="bg-white p-2.5 rounded-xl border border-slate-200/80 shadow-2xs">
              <span className="text-slate-400 font-medium text-[11px] block">Ledger lines</span>
              <p className="text-sm font-bold font-mono text-teal-800 mt-0.5">
                {filtered.length}{" "}
                <span className="text-[11px] font-normal text-slate-400 font-sans">
                  {filtered.length !== transactions.length ? `(of ${transactions.length})` : "lines"}
                </span>
              </p>
            </div>
          </div>

          {/* Search Toolbar */}
          <div className="mt-3">
            <div className="relative w-full">
              <Search className="w-3.5 h-3.5 text-slate-400 absolute left-3 top-1/2 -translate-y-1/2" />
              <input
                type="text"
                placeholder="Search description, reference, date or source"
                value={searchQuery}
                onChange={(e) => setSearchQuery(e.target.value)}
                className="w-full pl-8.5 pr-3 py-1.5 text-xs rounded-xl border border-slate-200 bg-white shadow-2xs focus:outline-hidden focus:ring-2 focus:ring-teal-600/20 focus:border-teal-600"
              />
            </div>
          </div>
        </div>

        {/* Ledger Spreadsheet Table */}
        <div className="overflow-auto bg-slate-50/30">
          {isLoading ? (
            <SkeletonRows rows={8} columns={4} label="Loading the ledger lines" />
          ) : filtered.length === 0 ? (
            <div className="text-center py-14 px-4">
              <Receipt className="w-9 h-9 text-slate-300 mx-auto mb-2" />
              <p className="text-xs font-semibold text-slate-700">{searchQuery ? "Nothing matches" : "No ledger lines this year"}</p>
              <p className="text-[11px] text-slate-400 mt-1 max-w-sm mx-auto leading-relaxed">
                {searchQuery
                  ? "Try another search."
                  : "The balance was brought forward: nothing was posted to this account in the year."}
              </p>
            </div>
          ) : (
            <table className="w-full text-left text-xs border-collapse">
              <thead className="sticky top-0 bg-slate-100 text-slate-600 font-semibold border-b border-slate-200 shadow-2xs z-10 select-none">
                <tr>
                  <th className="py-2.5 px-3.5 w-28 whitespace-nowrap">Date</th>
                  <th className="py-2.5 px-3 w-24 whitespace-nowrap">Type</th>
                  <th className="py-2.5 px-3 w-36 whitespace-nowrap">Reference</th>
                  <th className="py-2.5 px-3.5 min-w-[260px]">Description</th>
                  <th className="py-2.5 px-3.5 text-right w-32 whitespace-nowrap">Money in (£)</th>
                  <th className="py-2.5 px-3.5 text-right w-32 whitespace-nowrap">Money out (£)</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-100 bg-white">
                {page.paginatedItems.map((tx, idx) => {
                  const debit = Number(tx.debit_amount || 0);
                  const credit = Number(tx.credit_amount || 0);

                  return (
                    <tr
                      key={tx.id || idx}
                      className="hover:bg-teal-50/25 transition-colors group"
                    >
                      {/* Date */}
                      <td className="py-2 px-3.5 font-mono text-slate-500 whitespace-nowrap text-[11px]">
                        {tx.transaction_date || "-"}
                      </td>

                      {/* Type / Source */}
                      <td className="py-2 px-3 whitespace-nowrap">
                        {tx.source ? (
                          <span className="px-1.5 py-0.5 rounded text-[11px] font-medium bg-slate-100 text-slate-600 border border-slate-200/60">
                            {tx.source}
                          </span>
                        ) : (
                          <span className="text-slate-300">-</span>
                        )}
                      </td>

                      {/* Reference */}
                      <td className="py-2 px-3 font-mono text-slate-600 text-[11px] truncate max-w-[140px]" title={tx.reference || ""}>
                        {tx.reference || <span className="text-slate-300">-</span>}
                      </td>

                      {/* Description */}
                      <td className="py-2 px-3.5 text-slate-800 font-medium">
                        <span className="line-clamp-2 leading-relaxed" title={tx.description || tx.reference || ""}>
                          {tx.description || tx.reference || (tx.source ? `${tx.source} entry` : "General ledger entry")}
                        </span>
                      </td>

                      {/* Money In (Debit) */}
                      <td className="py-2 px-3.5 text-right font-mono whitespace-nowrap font-semibold">
                        {debit > 0 ? (
                          <span className="text-emerald-700">
                            {formatCurrency(debit)}
                          </span>
                        ) : (
                          <span className="text-slate-300 font-normal">-</span>
                        )}
                      </td>

                      {/* Money Out (Credit) */}
                      <td className="py-2 px-3.5 text-right font-mono whitespace-nowrap font-semibold">
                        {credit > 0 ? (
                          <span className="text-slate-700">
                            {formatCurrency(credit)}
                          </span>
                        ) : (
                          <span className="text-slate-300 font-normal">-</span>
                        )}
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          )}
          <PageControls page={page} itemLabel="lines" sizes={[50, 100, 200]} />
        </div>

        {/* Modal Footer */}
        <div className="p-3.5 border-t border-slate-200 bg-slate-50 flex items-center justify-between text-xs text-slate-500">
          <div className="flex items-center space-x-4">
            <span>
              Showing <strong className="text-slate-700">{filtered.length}</strong> {filtered.length === 1 ? "line" : "lines"}
            </span>
            {filtered.length > 0 && (
              <span className="hidden sm:inline text-slate-400">
                • Net: <strong className="text-slate-700 font-mono">{formatCurrency(totalDebits - totalCredits)}</strong>
              </span>
            )}
          </div>
          <button
            onClick={onClose}
            className="px-4 py-1.5 rounded-xl bg-white border border-slate-200 text-slate-700 hover:bg-slate-100 font-medium transition cursor-pointer shadow-2xs"
          >
            Close
          </button>
        </div>
      </div>
    </div>
  );
}
