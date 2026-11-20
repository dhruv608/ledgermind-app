import { useState, useMemo } from "react";

export interface UsePaginationOptions<T> {
  items: T[];
  initialPageSize?: number;
  initialPage?: number;
  resetDependencies?: any[]; // Automatically reset to page 1 when any of these change (e.g. search query)
}

export interface UsePaginationResult<T> {
  currentPage: number;
  pageSize: number;
  totalPages: number;
  totalItems: number;
  startIndex: number;
  endIndex: number;
  paginatedItems: T[];
  pageRange: (number | string)[];
  canPrevPage: boolean;
  canNextPage: boolean;
  setPage: (page: number) => void;
  setPageSize: (size: number) => void;
  nextPage: () => void;
  prevPage: () => void;
  firstPage: () => void;
  lastPage: () => void;
}

/**
 * Headless pagination hook that calculates boundaries, slices items,
 * and generates smart pagination number pills ([1, '...', 4, 5, 6, '...', 12]).
 */
export function usePagination<T>({
  items,
  initialPageSize = 10,
  initialPage = 1,
  resetDependencies = [],
}: UsePaginationOptions<T>): UsePaginationResult<T> {
  const [currentPage, setCurrentPage] = useState<number>(initialPage);
  const [pageSize, setPageSize] = useState<number>(initialPageSize);

  // Reset to first page when resetDependencies change (e.g. search filter). Set while rendering, not in an effect:
  // each one is compared as an effect's dependency is (Object.is), so pass values or state, not objects made each render
  const [resetFor, setResetFor] = useState<any[]>(resetDependencies);
  if (resetFor.length !== resetDependencies.length || resetDependencies.some((d, i) => !Object.is(d, resetFor[i]))) {
    setResetFor(resetDependencies);
    setCurrentPage(1);
  }

  const totalItems = items.length;
  const totalPages = Math.max(1, Math.ceil(totalItems / pageSize));

  // Ensure current page is always within valid boundaries
  const safeCurrentPage = Math.min(Math.max(1, currentPage), totalPages);

  const startIndex = (safeCurrentPage - 1) * pageSize;
  const endIndex = Math.min(startIndex + pageSize, totalItems);

  const paginatedItems = useMemo(() => {
    return items.slice(startIndex, endIndex);
  }, [items, startIndex, endIndex]);

  // Generate smart pagination number list
  const pageRange = useMemo<(number | string)[]>(() => {
    if (totalPages <= 7) {
      return Array.from({ length: totalPages }, (_, i) => i + 1);
    }

    if (safeCurrentPage <= 4) {
      return [1, 2, 3, 4, 5, "...", totalPages];
    }

    if (safeCurrentPage >= totalPages - 3) {
      return [
        1,
        "...",
        totalPages - 4,
        totalPages - 3,
        totalPages - 2,
        totalPages - 1,
        totalPages,
      ];
    }

    return [
      1,
      "...",
      safeCurrentPage - 1,
      safeCurrentPage,
      safeCurrentPage + 1,
      "...",
      totalPages,
    ];
  }, [totalPages, safeCurrentPage]);

  const canPrevPage = safeCurrentPage > 1;
  const canNextPage = safeCurrentPage < totalPages;

  const setPage = (page: number) => {
    const clamped = Math.min(Math.max(1, page), totalPages);
    setCurrentPage(clamped);
  };

  const handleSetPageSize = (newSize: number) => {
    setPageSize(newSize);
    setCurrentPage(1);
  };

  const nextPage = () => {
    if (canNextPage) setCurrentPage((prev) => prev + 1);
  };

  const prevPage = () => {
    if (canPrevPage) setCurrentPage((prev) => prev - 1);
  };

  const firstPage = () => setCurrentPage(1);
  const lastPage = () => setCurrentPage(totalPages);

  return {
    currentPage: safeCurrentPage,
    pageSize,
    totalPages,
    totalItems,
    startIndex,
    endIndex,
    paginatedItems,
    pageRange,
    canPrevPage,
    canNextPage,
    setPage,
    setPageSize: handleSetPageSize,
    nextPage,
    prevPage,
    firstPage,
    lastPage,
  };
}
