import React from "react";
import { ClientListItem } from "@/types/engagement";
import { Card } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { ConfirmDialog } from "@/components/ui/confirm-dialog";
import { CustomSelect } from "@/components/ui/custom-select";
import { plural } from "@/lib/formatters";
import { getAccountingSystemBadge } from "@/lib/badges";
import { Pagination } from "@/components/common/Pagination";
import { TableSkeleton } from "@/components/common/TableSkeleton";
import { EmptyState } from "@/components/common/EmptyState";
import { BulkActionBar } from "@/components/common/BulkActionBar";
import { Building2, Plus, RotateCcw, Search, X } from "lucide-react";
import { nextYearEnd, STAGES, type StageFilter } from "@/components/clients/client-directory/stages";
import { useClientDirectory } from "@/components/clients/client-directory/useClientDirectory";
import { ClientCardList } from "@/components/clients/client-directory/ClientCardList";
import { ClientTable } from "@/components/clients/client-directory/ClientTable";

export { matchesStage, type StageFilter } from "@/components/clients/client-directory/stages";

interface ClientDirectoryProps {
  clients: ClientListItem[];
  isLoading?: boolean;
  onSelectClient: (engagementId: string) => void;
  /** Opens the upload; with a company, for its next year-end */
  onOpenUpload: (nextYearOf?: { name: string; yearEnd: string }) => void;
  onDeleteClient: (engagementId: string, clientName: string) => Promise<void>;
  onBulkDeleteClients?: (engagementIds: string[]) => Promise<void>;
  /** The stage filter set from outside (the home page's Today strip); else the list keeps its own */
  stage?: StageFilter;
  onStageChange?: (stage: StageFilter) => void;
  /** The home page shows its own title and New client button */
  showTitle?: boolean;
}

export function ClientDirectory({
  clients,
  isLoading = false,
  onSelectClient,
  onOpenUpload,
  onDeleteClient,
  onBulkDeleteClients,
  stage: stageProp,
  onStageChange,
  showTitle = true,
}: ClientDirectoryProps) {
  const {
    searchQuery, setSearchQuery, stage, setStage, systemFilter, setSystemFilter, sortBy, setSortBy,
    isBulkDeleteModalOpen, setIsBulkDeleteModalOpen, isDeleting, stageCounts, filteredClients, companyCount,
    isAnyFilterActive, handleResetFilters,
    currentPage, pageSize, totalPages, totalFiltered, startIndex, endIndex, pageNumbers, canPrevPage, canNextPage,
    setCurrentPage, setPageSize, prevPage, nextPage, firstPage, lastPage,
    rows, selectedIds, selectedCount, handleToggleRow, handleToggleSelectAllPage, handleSelectAllFiltered,
    handleClearSelection, isAllPageSelected, isSomePageSelected, handleConfirmBulkDelete, selectedClientNames,
  } = useClientDirectory({ clients, stage: stageProp, onStageChange, onDeleteClient, onBulkDeleteClients });

  // Ticks every year-end of the company, or clears them when all are ticked
  // Tick boxes show on hover, or all of them once anything is ticked (the list stays clean until then; phones always)
  const boxShown = (ticked: boolean) =>
    selectedIds.size > 0 || ticked ? "" : "sm:opacity-0 sm:group-hover:opacity-100 sm:focus:opacity-100";
  const companyCheckbox = (years: ClientListItem[]) => {
    const ticked = years.filter((c) => selectedIds.has(c.engagement_id)).length;
    return (
      <input
        type="checkbox"
        checked={ticked === years.length}
        ref={(el) => {
          if (el) el.indeterminate = ticked > 0 && ticked < years.length;
        }}
        onChange={() =>
          years.forEach((c) => {
            if (ticked === years.length || !selectedIds.has(c.engagement_id)) handleToggleRow(c.engagement_id);
          })
        }
        title={ticked === years.length ? "Untick all its years" : "Tick all its years"}
        className={`h-4 w-4 cursor-pointer rounded border-slate-300 accent-teal-700 ${boxShown(ticked > 0)}`}
      />
    );
  };
  const addNextYear = (latest: ClientListItem) => (
    <button
      type="button"
      onClick={() => onOpenUpload({ name: latest.client_name, yearEnd: nextYearEnd(latest.period_end_date) })}
      className="inline-flex items-center gap-1 rounded-md border border-slate-200 bg-white px-2 py-1 text-[11px] font-medium text-slate-600 transition hover:border-teal-300 hover:text-teal-800"
    >
      <Plus className="h-3 w-3" />
      Add next year
    </button>
  );

  return (
    <div className="space-y-5">
      {/* Page title */}
      {showTitle && <div className="flex flex-col gap-3 sm:flex-row sm:items-end sm:justify-between">
        <div>
          <h1 className="text-xl font-bold tracking-tight text-slate-900">Clients</h1>
          {isLoading ? (
            <div className="mt-1.5 h-3 w-64 animate-pulse rounded bg-slate-200/70" />
          ) : (
            <p className="mt-0.5 text-xs text-slate-500">
              {`${plural(companyCount, "company", "companies")} · ${plural(clients.length, "year-end")} · ${clients.length - stageCounts.final} in progress · ${stageCounts.final} done`}
            </p>
          )}
        </div>
        <Button onClick={() => onOpenUpload()} variant="primary" className="h-9 self-start sm:self-auto">
          <Plus className="mr-1.5 h-4 w-4" />
          New client
        </Button>
      </div>}

      {/* Where each client stands */}
      <div className="flex flex-col gap-3 xl:flex-row xl:items-center xl:justify-between">
        <div className="inline-flex flex-wrap gap-1 self-start rounded-lg border border-slate-200 bg-white p-1">
          {STAGES.filter((s) => !s.optional || stageCounts[s.id] > 0 || stage === s.id).map((s) => (
            <button
              key={s.id}
              type="button"
              title={s.hint}
              onClick={() => setStage(s.id)}
              className={`group rounded-md px-3 py-1.5 text-xs font-medium transition ${
                stage === s.id ? "bg-teal-700 text-white shadow-sm" : "text-slate-600 hover:bg-teal-50 hover:text-teal-800"
              }`}
            >
              {s.label}
              <span className={`ml-1.5 font-mono text-[11px] ${stage === s.id ? "text-teal-100"
                : s.id === "overdue" && stageCounts.overdue > 0 ? "font-semibold text-rose-600"
                : "text-slate-400 group-hover:text-teal-600"}`}>
                {stageCounts[s.id]}
              </span>
            </button>
          ))}
        </div>

        <div className="flex flex-wrap items-center gap-2">
          <div className="relative w-full sm:w-60">
            <Search className="absolute left-2.5 top-2.5 h-3.5 w-3.5 text-slate-400" />
            <Input
              value={searchQuery}
              onChange={(e) => setSearchQuery(e.target.value)}
              placeholder="Search client or year end"
              className="h-8 border-slate-300 bg-white pl-8 pr-7 text-xs"
            />
            {searchQuery && (
              <button
                onClick={() => setSearchQuery("")}
                className="absolute right-2 top-2 text-slate-400 hover:text-slate-600"
                title="Clear search"
              >
                <X className="h-4 w-4" />
              </button>
            )}
          </div>
          <CustomSelect
            value={systemFilter}
            onChange={setSystemFilter}
            title="Accounting software"
            options={[
              { value: "all", label: "All software", count: clients.length },
              { value: "xero", label: "Xero", count: clients.filter((c) => getAccountingSystemBadge(c.source_system).label === "Xero").length },
              { value: "quickbooks", label: "QuickBooks", count: clients.filter((c) => getAccountingSystemBadge(c.source_system).label === "QuickBooks").length },
              { value: "sage", label: "Sage", count: clients.filter((c) => getAccountingSystemBadge(c.source_system).label === "Sage").length },
              { value: "bank_dext", label: "Bank + Dext", count: clients.filter((c) => getAccountingSystemBadge(c.source_system).label === "Bank + Dext").length },
              { value: "other", label: "Other software", count: clients.filter((c) => getAccountingSystemBadge(c.source_system).label === "Other software").length },
            ]}
          />
          <CustomSelect
            value={sortBy}
            onChange={setSortBy}
            title="Order"
            align="right"
            options={[
              { value: "recent", label: "Recently worked on" },
              { value: "newest", label: "Newest first" },
              { value: "name", label: "Name A–Z" },
              { value: "year_end", label: "Year end" },
              { value: "due", label: "Due soonest" },
              { value: "todo", label: "Most left to do" },
            ]}
          />
          {isAnyFilterActive && (
            <Button variant="ghost" size="sm" onClick={handleResetFilters} className="h-8 px-2.5 text-xs">
              <RotateCcw className="mr-1 h-3.5 w-3.5" />
              Reset
            </Button>
          )}
        </div>
      </div>

      <BulkActionBar
        selectedCount={selectedCount}
        totalFiltered={filteredClients.length}
        onSelectAllFiltered={() => handleSelectAllFiltered()}
        onClearSelection={handleClearSelection}
        onAction={() => setIsBulkDeleteModalOpen(true)}
        actionLabel="Delete selected"
        itemLabel="clients"
      />

      {isLoading ? (
        <TableSkeleton columns={["Year end", "Progress", "To do", "Workbook", "Last worked on", ""]} rows={6} hasCheckbox={true} />
      ) : filteredClients.length === 0 ? (
        <EmptyState
          icon={Building2}
          art={isAnyFilterActive ? "search" : "start"}
          title={isAnyFilterActive ? "No clients match" : "No clients yet"}
          description={
            isAnyFilterActive
              ? "Change the search or filters, or reset them."
              : "Upload a client's trial balance and ledger export to start their year-end."
          }
          action={
            isAnyFilterActive
              ? { label: "Reset filters", onClick: handleResetFilters, icon: RotateCcw }
              : { label: "New client", onClick: () => onOpenUpload(), icon: Plus }
          }
        />
      ) : (
        <Card className="overflow-hidden">
          {/* Phones: one card per client */}
          <ClientCardList rows={rows} companyCheckbox={companyCheckbox} addNextYear={addNextYear} onSelectClient={onSelectClient} />

          <ClientTable
            rows={rows}
            companyCheckbox={companyCheckbox}
            addNextYear={addNextYear}
            onSelectClient={onSelectClient}
            selectedIds={selectedIds}
            handleToggleRow={handleToggleRow}
            boxShown={boxShown}
            isAllPageSelected={isAllPageSelected}
            isSomePageSelected={isSomePageSelected}
            handleToggleSelectAllPage={handleToggleSelectAllPage}
          />

          <Pagination
            currentPage={currentPage}
            pageSize={pageSize}
            totalPages={totalPages}
            totalItems={totalFiltered}
            startIndex={startIndex}
            endIndex={endIndex}
            pageRange={pageNumbers}
            canPrevPage={canPrevPage}
            canNextPage={canNextPage}
            onPageChange={setCurrentPage}
            onPageSizeChange={setPageSize}
            onPrevPage={prevPage}
            onNextPage={nextPage}
            onFirstPage={firstPage}
            onLastPage={lastPage}
            itemLabel="companies"
          />
        </Card>
      )}

      <ConfirmDialog
        isOpen={isBulkDeleteModalOpen}
        onClose={() => setIsBulkDeleteModalOpen(false)}
        onConfirm={handleConfirmBulkDelete}
        title={`Delete ${plural(selectedIds.size, "client")}?`}
        description="This removes each client's trial balance, ledger, mappings, review points, journals and workbooks. It cannot be undone."
        clientName={
          selectedClientNames.length <= 3
            ? selectedClientNames.join(", ")
            : `${selectedClientNames.slice(0, 3).join(", ")} and ${selectedClientNames.length - 3} more`
        }
        confirmText={`Delete ${plural(selectedIds.size, "client")}`}
        cancelText="Cancel"
        isLoading={isDeleting}
      />
    </div>
  );
}
