import { useState, useMemo, useCallback } from "react";

export interface UseSelectionOptions {
  pageItemIds: string[];
  allItemIds?: string[];
}

export interface UseSelectionResult {
  selectedIds: Set<string>;
  selectedCount: number;
  isSelected: (id: string) => boolean;
  toggle: (id: string) => void;
  toggleAllPage: () => void;
  selectAll: (customIds?: string[]) => void;
  clear: () => void;
  isAllPageSelected: boolean;
  isSomePageSelected: boolean;
}

/**
 * Headless selection hook for managing multi-select checkboxes,
 * select-all-on-page, select-all-filtered, and bulk actions.
 */
export function useSelection({
  pageItemIds,
  allItemIds = [],
}: UseSelectionOptions): UseSelectionResult {
  const [selectedIds, setSelectedIds] = useState<Set<string>>(new Set());

  const selectedCount = selectedIds.size;

  const isSelected = useCallback(
    (id: string) => selectedIds.has(id),
    [selectedIds]
  );

  const toggle = useCallback((id: string) => {
    setSelectedIds((prev) => {
      const next = new Set(prev);
      if (next.has(id)) {
        next.delete(id);
      } else {
        next.add(id);
      }
      return next;
    });
  }, []);

  const isAllPageSelected = useMemo(() => {
    return (
      pageItemIds.length > 0 &&
      pageItemIds.every((id) => selectedIds.has(id))
    );
  }, [pageItemIds, selectedIds]);

  const isSomePageSelected = useMemo(() => {
    return (
      pageItemIds.some((id) => selectedIds.has(id)) && !isAllPageSelected
    );
  }, [pageItemIds, selectedIds, isAllPageSelected]);

  const toggleAllPage = useCallback(() => {
    setSelectedIds((prev) => {
      const next = new Set(prev);
      if (isAllPageSelected) {
        pageItemIds.forEach((id) => next.delete(id));
      } else {
        pageItemIds.forEach((id) => next.add(id));
      }
      return next;
    });
  }, [pageItemIds, isAllPageSelected]);

  const selectAll = useCallback(
    (customIds?: string[]) => {
      const idsToSelect = customIds || allItemIds;
      setSelectedIds(new Set(idsToSelect));
    },
    [allItemIds]
  );

  const clear = useCallback(() => {
    setSelectedIds(new Set());
  }, []);

  return {
    selectedIds,
    selectedCount,
    isSelected,
    toggle,
    toggleAllPage,
    selectAll,
    clear,
    isAllPageSelected,
    isSomePageSelected,
  };
}
