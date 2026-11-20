import React from "react";
import { Card } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { CustomSelect } from "@/components/ui/custom-select";
import { Search, ArrowUpDown, ArrowUp, ArrowDown, ListTree, Check } from "lucide-react";
import { Tabs } from "@/components/ui/tabs";
import { cn } from "@/lib/utils";
import { SectionHeader } from "@/components/ui/section-header";
import { StatusChip } from "@/components/ui/status-chip";
import { GLTransactionDrawer } from "@/components/mapping/GLTransactionDrawer";
import { ReassignMappingModal } from "@/components/mapping/ReassignMappingModal";
import { ConfirmDialog } from "@/components/ui/confirm-dialog";
import { plural, formatCurrency } from "@/lib/formatters";
import { PageControls } from "@/components/common/Pagination";
import { MappingTableProps, SortField, StatusFilter } from "@/components/mapping/mapping-table/helpers";
import { useMappingTable } from "@/components/mapping/mapping-table/useMappingTable";
import { MappingRow } from "@/components/mapping/mapping-table/MappingRow";

export function MappingTable({ records, engagementId, onChanged }: MappingTableProps) {
  const {
    localRecords, lastYear, searchTerm, setSearchTerm, statementArea, setStatementArea, balanceFilter, setBalanceFilter,
    setMateriality, sortField, sortOrder, statusFilter, setStatusFilter, showDrCr, hasLastYear, columns, toggleDrCr,
    isConfirmingAll, askConfirmAll, setAskConfirmAll, optionsFor, setOptionsFor, options, loadingOptions, showOptions,
    chooseOption, ticked, setTicked, materiality, plCount, bsCount, hiddenByView, statusCounts, reassignRecord,
    isReassignOpen, setIsReassignOpen, confirmingAccount, selectedDrawerAccount, setSelectedDrawerAccount, isDrawerOpen,
    setIsDrawerOpen, handleSort, handleOpenReassign, handleMappingUpdated, handleSingleConfirm, confirmable,
    handleConfirmAllShown, page, paginatedRecords, allPageTicked, tickablePage, toggleTick, togglePage, handleConfirmTicked,
  } = useMappingTable({ records, engagementId, onChanged });

  const renderSortIcon = (field: SortField) => {
    if (sortField !== field || sortOrder === "none") {
      return <ArrowUpDown className="w-3 h-3 text-slate-400 opacity-60 ml-1 inline" />;
    }
    if (sortOrder === "asc") {
      return <ArrowUp className="w-3 h-3 text-teal-700 ml-1 inline" />;
    }
    return <ArrowDown className="w-3 h-3 text-teal-700 ml-1 inline" />;
  };

  const totalDebit = records.reduce((s, r) => s + (Number(r.debit_amount) || 0), 0);
  const totalCredit = records.reduce((s, r) => s + (Number(r.credit_amount) || 0), 0);
  const totalNet = totalDebit - totalCredit;

  const STATUS_TABS: { id: StatusFilter; label: string; count: number }[] = [
    { id: "REVIEW", label: "Needs review", count: statusCounts.REVIEW },
    { id: "AI", label: "AI suggested", count: statusCounts.AI },
    { id: "CONFIRMED", label: "Confirmed", count: statusCounts.CONFIRMED },
    { id: "ALL", label: "All", count: statusCounts.ALL },
  ];
  const AREAS: { id: "ALL" | "PL" | "BS"; label: string; count: number }[] = [
    { id: "ALL", label: "All", count: localRecords.length },
    { id: "PL", label: "P&L", count: plCount },
    { id: "BS", label: "Balance sheet", count: bsCount },
  ];
  const tbBalances = Math.abs(totalNet) < 0.01;
  const th = "whitespace-nowrap py-2.5 px-3 font-semibold";

  return (
    <div className="space-y-4">
      <Card className="overflow-hidden">
        <SectionHeader
          icon={ListTree}
          title="Accounts and mappings" page
          description="Each trial balance account and the standard code it goes to in the workbook. Click an account to see its ledger lines; confirm the code if it is right, or change it."
          className="border-b border-slate-100 p-5"
          actions={
            <StatusChip tone={tbBalances ? "success" : "danger"} title="Total debits minus total credits">
              {tbBalances ? "Trial balance balances" : `Trial balance out by ${formatCurrency(totalNet)}`}
            </StatusChip>
          }
        />

        {/* The status tabs, with the search and filters on the same bar */}
        <div className="px-5 pt-1">
          <Tabs
            label="Accounts by status"
            items={STATUS_TABS.filter((t) => t.count > 0 || t.id === "ALL" || t.id === statusFilter)}
            value={statusFilter}
            onChange={(id) => {
              setStatusFilter(id);
            }}
            actions={<>
            <div className="relative w-full sm:w-56">
              <Search className="absolute left-2.5 top-2.5 h-3.5 w-3.5 text-slate-400" />
              <Input
                type="text"
                placeholder="Search account or code"
                value={searchTerm}
                onChange={(e) => {
                  setSearchTerm(e.target.value);
                }}
                className="h-8 border-slate-200 bg-white pl-8 text-xs"
              />
            </div>
            <div className="inline-flex rounded-lg border border-slate-200 bg-white p-0.5 text-xs">
              {AREAS.map((a) => (
                <button
                  key={a.id}
                  type="button"
                  onClick={() => {
                    setStatementArea(a.id);
                  }}
                  className={cn(
                    "rounded-md px-2.5 py-1 font-medium transition",
                    statementArea === a.id ? "bg-teal-50 text-teal-800" : "text-slate-600 hover:bg-teal-50/60 hover:text-teal-800"
                  )}
                >
                  {a.label} <span className="font-mono text-[11px] text-slate-400">{a.count}</span>
                </button>
              ))}
            </div>
            <CustomSelect
              align="right"
              value={balanceFilter}
              onChange={(val) => {
                setBalanceFilter(val);
              }}
              options={[
                { value: "ALL", label: "All balances" },
                { value: "NON_ZERO", label: "Not zero" },
                { value: "MATERIAL", label: `Over materiality (£${materiality.toLocaleString("en-GB")})`,
                  description: setMateriality ? "The client's materiality (setup)" : "Default: 1% of turnover or 5% of profit, the lower" },
                { value: "OVER_250", label: "Over £250" },
                { value: "ZERO_ONLY", label: "Zero only" },
              ]}
            />
            <label className="flex cursor-pointer items-center gap-1.5 whitespace-nowrap text-xs text-slate-600" title="Show the debit and credit columns">
              <input type="checkbox" checked={showDrCr} onChange={toggleDrCr} className="h-3.5 w-3.5 accent-teal-700" />
              Debit / credit
            </label>
            </>}
          />
        </div>

        {hiddenByView > 0 && (
          <div className="flex flex-wrap items-center gap-x-2 gap-y-1 border-b border-amber-100 bg-amber-50/60 px-5 py-2 text-xs text-amber-900">
            <span>
              {hiddenByView} more {hiddenByView === 1 ? "account" : "accounts"}
              {statusFilter === "REVIEW" ? " to review" : ""} hidden by the filters
              {[statementArea === "PL" ? "P&L only" : statementArea === "BS" ? "balance sheet only" : "",
                balanceFilter === "MATERIAL" ? `over materiality (£${materiality.toLocaleString("en-GB")})`
                  : balanceFilter === "OVER_250" ? "over £250" : balanceFilter === "NON_ZERO" ? "not zero"
                  : balanceFilter === "ZERO_ONLY" ? "zero only" : "", searchTerm.trim() ? `the search "${searchTerm.trim()}"` : ""]
                .filter(Boolean).join(", ").replace(/^/, ": ")}
            </span>
            <button type="button" className="font-semibold text-teal-700 hover:text-teal-900"
                    onClick={() => { setStatementArea("ALL"); setBalanceFilter("ALL"); setSearchTerm(""); }}>
              Show all
            </button>
          </div>
        )}

        {statusFilter !== "ALL" && statusFilter !== "CONFIRMED" && confirmable.length > 0 && (
          <div className="flex flex-col gap-2 border-b border-emerald-100 bg-emerald-50/50 px-5 py-2.5 sm:flex-row sm:items-center sm:justify-between">
            <p className="text-xs text-emerald-900">Checked every account below and the codes are right? Confirm them in one go.</p>
            <Button
              type="button"
              size="sm"
              variant="outline"
              onClick={() => setAskConfirmAll(true)}
              disabled={isConfirmingAll}
              className="h-7 shrink-0 border-emerald-300 bg-white text-[11px] text-emerald-700 hover:bg-emerald-50"
            >
              <Check className="mr-1 h-3.5 w-3.5" />
              Confirm all shown ({confirmable.length})
            </Button>
          </div>
        )}

        {ticked.size > 0 && (
          <div className="flex flex-col gap-2 border-b border-teal-100 bg-teal-50/60 px-5 py-2.5 sm:flex-row sm:items-center sm:justify-between">
            <p className="text-xs font-medium text-teal-900">{plural(ticked.size, "account")} ticked: confirm their codes together.</p>
            <div className="flex gap-2">
              <Button type="button" size="sm" variant="ghost" onClick={() => setTicked(new Set())} className="h-7 text-[11px]">
                Untick all
              </Button>
              <Button type="button" size="sm" onClick={handleConfirmTicked} disabled={isConfirmingAll} className="h-7 bg-emerald-600 text-[11px] hover:bg-emerald-700">
                <Check className="mr-1 h-3.5 w-3.5" />
                Confirm {plural(ticked.size, "code")}
              </Button>
            </div>
          </div>
        )}

        {lastYear && (
          <div className="border-b border-slate-100 px-5 py-2 text-[11px] text-slate-500">
            {lastYear.source ? (
              <>
                Last year: from {lastYear.source}. Big changes (over 50% and £1,000, or new or gone) are in orange and go to the
                Review tab as client questions.
                {Object.values(lastYear.accounts).some((a) => a.last_year === null) &&
                  " Last year's TB has no P&L lines (the profit was already moved to reserves), so P&L shows –."}
                {lastYear.gone.length > 0 && (
                  <span className="mt-1 block text-slate-600">
                    Last year but not this year:{" "}
                    {lastYear.gone.map((g) => `${g.name} ${formatCurrency(g.amount)}`).join(" · ")}
                  </span>
                )}
              </>
            ) : (
              <>No last year&apos;s figures: last year&apos;s job is not in the app and no last year&apos;s TB was uploaded.</>
            )}
          </div>
        )}
        <div className="overflow-x-auto">
          <table className={cn("w-full text-left text-xs", showDrCr ? "min-w-[1100px]" : "min-w-[880px]")}>
            <thead className="select-none border-b border-slate-200 bg-slate-50 text-[11px] uppercase tracking-wide text-slate-500">
              <tr>
                <th className="w-10 py-2.5 pl-5">
                  <input
                    type="checkbox"
                    checked={allPageTicked}
                    disabled={tickablePage.length === 0}
                    onChange={togglePage}
                    className="h-4 w-4 cursor-pointer rounded border-slate-300 accent-teal-700 disabled:cursor-not-allowed disabled:opacity-40"
                    title="Tick every unconfirmed account on this page"
                  />
                </th>
                <th onClick={() => handleSort("raw_account_name")} className={`${th} cursor-pointer hover:text-slate-800`}>
                  Account {renderSortIcon("raw_account_name")}
                </th>
                {showDrCr && (
                  <>
                    <th onClick={() => handleSort("debit_amount")} className={`${th} w-28 cursor-pointer text-right hover:text-slate-800`}>
                      Debit {renderSortIcon("debit_amount")}
                    </th>
                    <th onClick={() => handleSort("credit_amount")} className={`${th} w-28 cursor-pointer text-right hover:text-slate-800`}>
                      Credit {renderSortIcon("credit_amount")}
                    </th>
                  </>
                )}
                <th onClick={() => handleSort("net_amount")} className={`${th} w-28 cursor-pointer text-right hover:text-slate-800`}>
                  Net {renderSortIcon("net_amount")}
                </th>
                {hasLastYear && (
                  <>
                    <th className={`${th} w-28 text-right`} title={lastYear?.source ? `From ${lastYear.source}` : "No last year's figures"}>
                      Last year
                    </th>
                    <th className={`${th} w-28 text-right`}>Change</th>
                  </>
                )}
                <th onClick={() => handleSort("std_code")} className={`${th} cursor-pointer hover:text-slate-800`}>
                  Mapped to {renderSortIcon("std_code")}
                </th>
                <th className={`${th} sticky right-0 w-28 bg-slate-50 pr-5 text-right shadow-[-6px_0_6px_-6px_rgba(0,0,0,0.12)]`}>
                  Actions
                </th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-100 text-slate-700">
              {paginatedRecords.length === 0 ? (
                <tr>
                  <td colSpan={columns} className="py-10 text-center text-slate-400">
                    {statusFilter === "REVIEW" ? "Nothing needs review here." : "No accounts match these filters."}
                  </td>
                </tr>
              ) : (
                paginatedRecords.map((rec) => (
                  <MappingRow
                    key={rec.id}
                    rec={rec}
                    columns={columns}
                    showDrCr={showDrCr}
                    hasLastYear={hasLastYear}
                    lastYear={lastYear}
                    ticked={ticked}
                    toggleTick={toggleTick}
                    confirmingAccount={confirmingAccount}
                    optionsFor={optionsFor}
                    setOptionsFor={setOptionsFor}
                    options={options}
                    loadingOptions={loadingOptions}
                    setSelectedDrawerAccount={setSelectedDrawerAccount}
                    setIsDrawerOpen={setIsDrawerOpen}
                    handleSingleConfirm={handleSingleConfirm}
                    handleOpenReassign={handleOpenReassign}
                    showOptions={showOptions}
                    chooseOption={chooseOption}
                  />
                ))
              )}
            </tbody>
          </table>
        </div>

        <PageControls page={page} itemLabel="accounts" sizes={[25, 50, 100]} />
      </Card>

      {/* Slide-Out General Ledger Transaction Drawer */}
      <GLTransactionDrawer
        isOpen={isDrawerOpen}
        onClose={() => setIsDrawerOpen(false)}
        engagementId={engagementId || ""}
        accountName={selectedDrawerAccount?.raw_account_name || null}
        stdCode={selectedDrawerAccount?.std_code || null}
        stdName={selectedDrawerAccount?.std_name || null}
        netAmount={Number(selectedDrawerAccount?.net_amount || 0)}
      />

      {/* Reassign Nominal Code Modal */}
      <ReassignMappingModal
        isOpen={isReassignOpen}
        onClose={() => setIsReassignOpen(false)}
        record={reassignRecord}
        onMappingUpdated={handleMappingUpdated}
        engagementId={engagementId}
      />
      <ConfirmDialog
        isOpen={askConfirmAll}
        onClose={() => setAskConfirmAll(false)}
        onConfirm={handleConfirmAllShown}
        isLoading={isConfirmingAll}
        title={`Confirm ${plural(confirmable.length, "account")}?`}
        description="The code shown for each account becomes the accountant's answer and is remembered for next time. Only do this after checking each one."
        confirmText="Confirm all"
      />
    </div>
  );
}
