import { Button } from "@/components/ui/button";
import { CustomSelect } from "@/components/ui/custom-select";
import {
  ChevronLeft,
  ChevronRight,
  ChevronsLeft,
  ChevronsRight,
} from "lucide-react";

export interface PaginationProps {
  currentPage: number;
  pageSize: number;
  totalPages: number;
  totalItems: number;
  startIndex: number;
  endIndex: number;
  pageRange: (number | string)[];
  canPrevPage: boolean;
  canNextPage: boolean;
  onPageChange: (page: number) => void;
  onPageSizeChange: (size: number) => void;
  onPrevPage: () => void;
  onNextPage: () => void;
  onFirstPage: () => void;
  onLastPage: () => void;
  pageSizeOptions?: number[];
  itemLabel?: string;
}

/**
 * Reusable table pagination footer with rows-per-page selector,
 * item count counters, and smart numbered page pills.
 */
export function Pagination({
  currentPage,
  pageSize,
  totalPages,
  totalItems,
  startIndex,
  endIndex,
  pageRange,
  canPrevPage,
  canNextPage,
  onPageChange,
  onPageSizeChange,
  onPrevPage,
  onNextPage,
  onFirstPage,
  onLastPage,
  pageSizeOptions = [5, 10, 25, 50],
  itemLabel = "items",
}: PaginationProps) {
  // Everything fits on the smallest page: no page buttons needed
  if (totalItems <= Math.min(...pageSizeOptions)) return null;
  return (
    <div className="flex flex-col items-center justify-between gap-3 border-t border-slate-200 bg-white px-5 py-3.5 text-xs text-slate-600 lg:flex-row">
      {/* Counters & Page Size */}
      <div className="flex flex-wrap items-center justify-center gap-x-4 gap-y-2">
        <span className="whitespace-nowrap">
          Showing{" "}
          <strong className="text-slate-900">
            {totalItems === 0 ? 0 : startIndex + 1}
          </strong>{" "}
          to <strong className="text-slate-900">{endIndex}</strong> of{" "}
          <strong className="text-slate-900">{totalItems}</strong> {itemLabel}
        </span>

        <div className="flex items-center gap-1.5 whitespace-nowrap text-xs text-slate-500">
          <span>Rows per page:</span>
          <CustomSelect
            size="sm"
            side="top"
            value={pageSize}
            onChange={(v) => onPageSizeChange(Number(v))}
            options={pageSizeOptions.map((opt) => ({ value: opt, label: String(opt) }))}
          />
        </div>
      </div>

      {/* Navigation Buttons & Number Pills */}
      <div className="flex flex-wrap items-center justify-center gap-1">
        <Button
          variant="outline"
          size="sm"
          disabled={!canPrevPage}
          onClick={onFirstPage}
          className="h-7 w-7 p-0"
          title="First Page"
        >
          <ChevronsLeft className="w-3.5 h-3.5" />
        </Button>
        <Button
          variant="outline"
          size="sm"
          disabled={!canPrevPage}
          onClick={onPrevPage}
          className="h-7 px-2 text-xs"
        >
          <ChevronLeft className="w-3.5 h-3.5 mr-0.5" />
          <span>Prev</span>
        </Button>

        <div className="flex items-center space-x-1 mx-1">
          {pageRange.map((p, idx) =>
            p === "..." ? (
              <span
                key={`ellipsis-${idx}`}
                className="px-1.5 text-slate-400 select-none"
              >
                ...
              </span>
            ) : (
              <Button
                key={`page-${p}`}
                size="sm"
                variant={currentPage === p ? "primary" : "outline"}
                onClick={() => onPageChange(Number(p))}
                className={`h-7 w-7 p-0 text-xs font-semibold ${
                  currentPage === p
                    ? "shadow-2xs text-white"
                    : "text-slate-700 hover:bg-slate-100"
                }`}
              >
                {p}
              </Button>
            )
          )}
        </div>

        <Button
          variant="outline"
          size="sm"
          disabled={!canNextPage}
          onClick={onNextPage}
          className="h-7 px-2 text-xs"
        >
          <span>Next</span>
          <ChevronRight className="w-3.5 h-3.5 ml-0.5" />
        </Button>
        <Button
          variant="outline"
          size="sm"
          disabled={!canNextPage}
          onClick={onLastPage}
          className="h-7 w-7 p-0"
          title="Last Page"
        >
          <ChevronsRight className="w-3.5 h-3.5" />
        </Button>
      </div>
    </div>
  );
}

/** The page control for a list paged with usePagination: hidden while the whole list fits on one page. */
export function PageControls({ page, itemLabel, sizes = [25, 50, 100] }: {
  page: import("@/hooks/usePagination").UsePaginationResult<unknown>;
  itemLabel: string;
  sizes?: number[];
}) {
  if (page.totalItems <= Math.min(...sizes)) return null;
  return (
    <Pagination currentPage={page.currentPage} pageSize={page.pageSize} totalPages={page.totalPages}
                totalItems={page.totalItems} startIndex={page.startIndex} endIndex={page.endIndex}
                pageRange={page.pageRange} canPrevPage={page.canPrevPage} canNextPage={page.canNextPage}
                onPageChange={page.setPage} onPageSizeChange={page.setPageSize} onPrevPage={page.prevPage}
                onNextPage={page.nextPage} onFirstPage={page.firstPage} onLastPage={page.lastPage}
                pageSizeOptions={sizes} itemLabel={itemLabel} />
  );
}
