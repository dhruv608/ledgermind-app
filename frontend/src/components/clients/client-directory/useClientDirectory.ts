// State of the client list: search, stage, software and order filters, companies grouped with their year-ends,
// pages, ticks and deleting the ticked clients.
import { useState, useMemo } from "react";
import { ClientListItem } from "@/types/engagement";
import { parseDateSafe } from "@/lib/formatters";
import { usePagination } from "@/hooks/usePagination";
import { useSelection } from "@/hooks/useSelection";
import { matchesStage, STAGES, StageFilter, yearEndTime } from "@/components/clients/client-directory/stages";

/** One company and its year-ends, latest first */
export type CompanyGroup = { key: string; years: ClientListItem[] };
/** A row on screen: a company heading, or one of its year-ends */
export type Row = { head: CompanyGroup } | { client: ClientListItem };

export function useClientDirectory({
  clients,
  stage: stageProp,
  onStageChange,
  onDeleteClient,
  onBulkDeleteClients,
}: {
  clients: ClientListItem[];
  stage?: StageFilter;
  onStageChange?: (stage: StageFilter) => void;
  onDeleteClient: (engagementId: string, clientName: string) => Promise<void>;
  onBulkDeleteClients?: (engagementIds: string[]) => Promise<void>;
}) {
  const [searchQuery, setSearchQuery] = useState("");
  const [ownStage, setOwnStage] = useState<StageFilter>("all");
  const stage = stageProp ?? ownStage;
  const setStage = (s: StageFilter) => (onStageChange ? onStageChange(s) : setOwnStage(s));
  const [systemFilter, setSystemFilter] = useState<string>("all");
  const [sortBy, setSortBy] = useState<string>("recent");
  const [isBulkDeleteModalOpen, setIsBulkDeleteModalOpen] = useState(false);
  const [isDeleting, setIsDeleting] = useState(false);

  const stageCounts = useMemo(
    () => Object.fromEntries(STAGES.map((s) => [s.id, clients.filter((c) => matchesStage(c, s.id)).length])) as Record<StageFilter, number>,
    [clients]
  );

  const filteredClients = useMemo(() => {
    const q = searchQuery.toLowerCase().trim();
    const result = clients.filter((c) => {
      if (q && !c.client_name.toLowerCase().includes(q) && !c.period_end_date.includes(q)) return false;
      if (!matchesStage(c, stage)) return false;
      if (systemFilter !== "all") {
        const sys = (c.source_system || "").toLowerCase();
        if (systemFilter === "quickbooks" ? !(sys.includes("quickbooks") || sys.includes("qbo")) : !sys.includes(systemFilter)) return false;
      }
      return true;
    });

    const created = (c: ClientListItem) => parseDateSafe(c.created_at)?.getTime() || 0;
    const toDo = (c: ClientListItem) => (c.mappings_to_review || 0) + (c.open_audit_findings || 0);
    return result.sort((a, b) => {
      if (sortBy === "name") return a.client_name.localeCompare(b.client_name);
      if (sortBy === "year_end") return yearEndTime(a.period_end_date) - yearEndTime(b.period_end_date);
      if (sortBy === "todo") return toDo(b) - toDo(a);
      if (sortBy === "recent") return (b.last_activity_at || "").localeCompare(a.last_activity_at || "");
      return created(b) - created(a);
    });
  }, [clients, searchQuery, stage, systemFilter, sortBy]);

  // One company's year-ends together (same Companies House number, else the same name). Companies keep the order of their first year-end in the sorted list.
  const groups = useMemo(() => {
    const byKey = new Map<string, ClientListItem[]>();
    for (const c of filteredClients) {
      const key = c.company_key || c.client_name.toLowerCase();
      byKey.set(key, [...(byKey.get(key) || []), c]);
    }
    const list = Array.from(byKey, ([key, years]) => ({
      key,
      years: [...years].sort((a, b) => yearEndTime(b.period_end_date) - yearEndTime(a.period_end_date)),
    }));
    // Due soonest: by the latest year's filing deadline, finished years last
    if (sortBy === "due") {
      const rank = (g: (typeof list)[number]) =>
        `${g.years[0].workbook_state === "final" ? 1 : 0}${g.years[0].accounts_due || "9999-12-31"}`;
      list.sort((a, b) => rank(a).localeCompare(rank(b)));
    }
    return list;
  }, [filteredClients, sortBy]);
  const companyCount = useMemo(() => new Set(clients.map((c) => c.company_key || c.client_name.toLowerCase())).size, [clients]);

  const isAnyFilterActive = searchQuery.trim() !== "" || stage !== "all" || systemFilter !== "all";

  const handleResetFilters = () => {
    setSearchQuery("");
    setStage("all");
    setSystemFilter("all");
  };

  const {
    currentPage,
    pageSize,
    totalPages,
    totalItems: totalFiltered,
    startIndex,
    endIndex,
    paginatedItems: paginatedGroups,
    pageRange: pageNumbers,
    canPrevPage,
    canNextPage,
    setPage: setCurrentPage,
    setPageSize,
    prevPage,
    nextPage,
    firstPage,
    lastPage,
  } = usePagination({
    items: groups,
    initialPageSize: 25,
    resetDependencies: [searchQuery, stage, systemFilter, sortBy],
  });

  // The rows on screen: every company has a heading with its name, then a row for each year-end, latest first
  const rows: Row[] = paginatedGroups.flatMap((g): Row[] => [{ head: g }, ...g.years.map((client) => ({ client }))]);
  const pageIds = useMemo(() => paginatedGroups.flatMap((g) => g.years.map((c) => c.engagement_id)), [paginatedGroups]);
  const allFilteredIds = useMemo(() => filteredClients.map((c) => c.engagement_id), [filteredClients]);

  const {
    selectedIds,
    selectedCount,
    isSelected,
    toggle: handleToggleRow,
    toggleAllPage: handleToggleSelectAllPage,
    selectAll: handleSelectAllFiltered,
    clear: handleClearSelection,
    isAllPageSelected,
    isSomePageSelected,
  } = useSelection({
    pageItemIds: pageIds,
    allItemIds: allFilteredIds,
  });

  const handleConfirmBulkDelete = async () => {
    if (selectedIds.size === 0) return;
    setIsDeleting(true);
    const idsToDelete = Array.from(selectedIds);
    try {
      if (onBulkDeleteClients) {
        await onBulkDeleteClients(idsToDelete);
      } else {
        await Promise.all(idsToDelete.map((id) => onDeleteClient(id, "")));
      }
      handleClearSelection();
      setIsBulkDeleteModalOpen(false);
    } finally {
      setIsDeleting(false);
    }
  };

  const selectedClientNames = useMemo(
    () => clients.filter((c) => selectedIds.has(c.engagement_id)).map((c) => c.client_name),
    [clients, selectedIds]
  );
  return {
    searchQuery, setSearchQuery, stage, setStage, systemFilter, setSystemFilter, sortBy, setSortBy,
    isBulkDeleteModalOpen, setIsBulkDeleteModalOpen, isDeleting, stageCounts, filteredClients, companyCount,
    isAnyFilterActive, handleResetFilters,
    currentPage, pageSize, totalPages, totalFiltered, startIndex, endIndex, pageNumbers, canPrevPage, canNextPage,
    setCurrentPage, setPageSize, prevPage, nextPage, firstPage, lastPage,
    rows, selectedIds, selectedCount, handleToggleRow, handleToggleSelectAllPage, handleSelectAllFiltered,
    handleClearSelection, isAllPageSelected, isSomePageSelected, handleConfirmBulkDelete, selectedClientNames,
  };
}
