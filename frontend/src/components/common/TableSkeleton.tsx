import { Card } from "@/components/ui/card";

export interface TableSkeletonProps {
  columns: string[];
  rows?: number;
  hasCheckbox?: boolean;
}

/**
 * Reusable animated shimmer skeleton table loader.
 */
export function TableSkeleton({
  columns,
  rows = 6,
  hasCheckbox = true,
}: TableSkeletonProps) {
  return (
    <Card className="overflow-hidden border-slate-200 shadow-2xs bg-white">
      <div className="overflow-x-auto">
        <table className="w-full text-left text-xs">
          <thead className="bg-slate-50 text-slate-600 font-semibold border-b border-slate-200">
            <tr>
              {hasCheckbox && (
                <th className="py-3 px-3.5 w-10 text-center">
                  <div className="w-4 h-4 rounded bg-slate-200/80 animate-pulse mx-auto" />
                </th>
              )}
              {columns.map((col, idx) => (
                <th
                  key={idx}
                  className={`py-3 px-4 ${
                    idx === columns.length - 1 ? "text-right px-5" : ""
                  }`}
                >
                  {col}
                </th>
              ))}
            </tr>
          </thead>
          <tbody className="divide-y divide-slate-100">
            {Array.from({ length: rows }).map((_, rIdx) => (
              <tr key={rIdx} className="animate-pulse">
                {hasCheckbox && (
                  <td className="py-3.5 px-3.5 text-center">
                    <div className="w-4 h-4 rounded bg-slate-200/80 mx-auto" />
                  </td>
                )}
                {/* Primary Column (Avatar + Title) */}
                <td className="py-3.5 px-4">
                  <div className="flex items-center space-x-3">
                    <div className="w-8 h-8 rounded-lg bg-slate-200/80 shrink-0" />
                    <div className="space-y-1.5 w-36">
                      <div className="h-3.5 bg-slate-200/80 rounded w-full" />
                      <div className="h-2 bg-slate-100 rounded w-20" />
                    </div>
                  </div>
                </td>
                {/* Secondary Data Columns */}
                {columns.slice(1, -1).map((_, cIdx) => (
                  <td key={cIdx} className="py-3.5 px-4">
                    <div
                      className={`h-3.5 bg-slate-200/70 rounded ${
                        cIdx % 2 === 0 ? "w-20" : "w-16"
                      }`}
                    />
                  </td>
                ))}
                {/* Actions Column */}
                <td className="py-3.5 px-5 text-right">
                  <div className="flex items-center justify-end space-x-2">
                    <div className="w-7 h-7 bg-slate-200/70 rounded-md" />
                    <div className="w-16 h-7 bg-slate-200/70 rounded-md" />
                    <div className="w-7 h-7 bg-slate-200/70 rounded-md" />
                  </div>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {/* Shimmer Pagination Footer Placeholder */}
      <div className="flex items-center justify-between px-5 py-3.5 border-t border-slate-200 bg-white">
        <div className="h-3.5 bg-slate-200/70 rounded w-48 animate-pulse" />
        <div className="h-7 bg-slate-200/70 rounded w-44 animate-pulse" />
      </div>
    </Card>
  );
}
