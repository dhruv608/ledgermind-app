import { Loader2 } from "lucide-react";
import { cn } from "@/lib/utils";

/** Placeholder rows in the shape of a list, shown while it loads: bars with a moving sweep, and above them what is
 *  loading in words when the caller says (a spinner and the label), so the wait never reads as an empty or broken page. */
export function SkeletonRows({ rows = 5, columns = 3, label = "Loading", quiet, className }: {
  rows?: number;
  columns?: number;
  label?: string;
  /** No spinner line: the page around it already shows what is loading */
  quiet?: boolean;
  className?: string;
}) {
  const widths = ["w-2/5", "w-1/4", "w-1/6", "w-1/5"];
  // The bars already say "loading": a line only when it says what is loading ("Reading the ledger"), never a bare "Loading"
  const said = !quiet && label !== "Loading";
  return (
    <div className={cn("divide-y divide-slate-100", className)} aria-busy="true" aria-label={label}>
      {said && (
        <p className="flex items-center gap-2 px-4 py-3 text-xs font-medium text-slate-500">
          <Loader2 className="h-3.5 w-3.5 animate-spin text-teal-600" />
          {label}…
        </p>
      )}
      {Array.from({ length: rows }).map((_, r) => (
        <div key={r} className="flex items-center gap-6 px-4 py-3.5">
          {Array.from({ length: columns }).map((_, c) => (
            <div
              key={c}
              className={cn("skeleton h-3 rounded", c === 0 ? "flex-1" : widths[c % widths.length], c === 0 && r % 2 && "max-w-[70%]")}
            />
          ))}
        </div>
      ))}
    </div>
  );
}
