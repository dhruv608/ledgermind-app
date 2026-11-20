import { Button } from "@/components/ui/button";
import { Trash2, X, LucideIcon } from "lucide-react";

export interface BulkActionBarProps {
  selectedCount: number;
  totalFiltered: number;
  onSelectAllFiltered: () => void;
  onClearSelection: () => void;
  onAction: () => void;
  actionLabel?: string;
  actionIcon?: LucideIcon;
  itemLabel?: string;
}

/**
 * Reusable banner displayed when one or more rows are selected in a table.
 */
export function BulkActionBar({
  selectedCount,
  totalFiltered,
  onSelectAllFiltered,
  onClearSelection,
  onAction,
  actionLabel = "Delete Selected",
  actionIcon: ActionIcon = Trash2,
  itemLabel = "client engagements",
}: BulkActionBarProps) {
  if (selectedCount === 0) return null;

  return (
    <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3 p-3 bg-teal-50/90 border border-teal-200 rounded-xl text-xs text-teal-950 animate-in fade-in slide-in-from-top-1 duration-200">
      <div className="flex items-center space-x-2">
        <span className="w-5 h-5 rounded-full bg-teal-700 text-white font-bold flex items-center justify-center text-[11px] shrink-0">
          {selectedCount}
        </span>
        <span className="font-medium">
          {selectedCount === 1
            ? `1 ${itemLabel.replace(/s$/, "")} selected`
            : `${selectedCount} ${itemLabel} selected`}
        </span>
        {selectedCount < totalFiltered && (
          <button
            onClick={onSelectAllFiltered}
            className="text-teal-800 hover:text-teal-900 underline font-semibold text-xs ml-2 cursor-pointer"
          >
            Select all {totalFiltered} {itemLabel}
          </button>
        )}
      </div>

      <div className="flex items-center space-x-2">
        <Button
          size="sm"
          variant="ghost"
          onClick={onClearSelection}
          className="h-8 text-xs text-teal-800 hover:text-teal-950 hover:bg-teal-100/70"
        >
          <X className="w-3.5 h-3.5 mr-1" />
          <span>Clear selection</span>
        </Button>
        <Button
          size="sm"
          variant="destructive"
          onClick={onAction}
          className="h-8 text-xs font-semibold shadow-2xs"
        >
          <ActionIcon className="w-3.5 h-3.5 mr-1" />
          <span>
            {actionLabel} ({selectedCount})
          </span>
        </Button>
      </div>
    </div>
  );
}
