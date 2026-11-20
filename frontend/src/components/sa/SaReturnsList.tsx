"use client";

// The firm's Self Assessment returns on the home page's Self Assessment tab: search, a tax year filter, an order and
// pages, like the company list. Each person by their initials (no stand-in photo), the tax year, the kinds of income
// they have (a few, then '+n'), the company they direct, and the online filing date for the year.
import { useMemo, useState } from "react";
import { Building2, ChevronRight, Plus, RotateCcw, Search, UserRound, X } from "lucide-react";
import type { SaJob } from "@/lib/api";
import { SOURCE_LABELS } from "@/components/sa/NewIndividualModal";
import { Card } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Button } from "@/components/ui/button";
import { CustomSelect } from "@/components/ui/custom-select";
import { EmptyState } from "@/components/common/EmptyState";
import { Pagination } from "@/components/common/Pagination";
import { usePagination } from "@/hooks/usePagination";

const SHOWN = 3;

export function initials(name: string): string {
  const words = name.split(/\s+/).filter((w) => !/^(e2e|mr|mrs|ms|miss|dr)\.?$/i.test(w))
    .map((w) => w.replace(/[^A-Za-z]/g, "")).filter(Boolean);
  if (!words.length) return "?";
  return ((words[0][0] || "") + (words.length > 1 ? words[words.length - 1][0] : "")).toUpperCase();
}

// Online returns and the balancing payment: 31 January after the tax year ends
export function saDueDate(taxYear: string): Date {
  return new Date(parseInt(taxYear.slice(0, 4), 10) + 2, 0, 31);
}
const dueLabel = (taxYear: string) =>
  saDueDate(taxYear).toLocaleDateString("en-GB", { day: "numeric", month: "short", year: "numeric" });

export function SaReturnsList({ jobs, onOpen, onNew }: { jobs: SaJob[]; onOpen: (id: string) => void; onNew: () => void }) {
  const [query, setQuery] = useState("");
  const [year, setYear] = useState("all");
  const [sortBy, setSortBy] = useState("name");

  const years = useMemo(() => Array.from(new Set(jobs.map((j) => j.tax_year))).sort().reverse(), [jobs]);
  const shown = useMemo(() => {
    const q = query.toLowerCase().trim();
    const list = jobs.filter((j) => (year === "all" || j.tax_year === year) && (!q
      || j.person_name.toLowerCase().includes(q) || (j.company?.name || "").toLowerCase().includes(q)));
    return [...list].sort((a, b) => sortBy === "newest" ? (b.created_at || "").localeCompare(a.created_at || "")
      : sortBy === "year" ? b.tax_year.localeCompare(a.tax_year) || a.person_name.localeCompare(b.person_name)
      : a.person_name.localeCompare(b.person_name));
  }, [jobs, query, year, sortBy]);
  const filtering = query.trim() !== "" || year !== "all";
  const reset = () => { setQuery(""); setYear("all"); };

  const page = usePagination({ items: shown, initialPageSize: 25, resetDependencies: [query, year, sortBy] });

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center gap-2">
        <div className="relative w-full sm:w-60">
          <Search className="absolute left-2.5 top-2.5 h-3.5 w-3.5 text-slate-400" />
          <Input value={query} onChange={(e) => setQuery(e.target.value)} placeholder="Search person or company"
                 className="h-8 border-slate-300 bg-white pl-8 pr-7 text-xs" />
          {query && (
            <button onClick={() => setQuery("")} className="absolute right-2 top-2 text-slate-400 hover:text-slate-600" title="Clear search">
              <X className="h-4 w-4" />
            </button>
          )}
        </div>
        <CustomSelect value={year} onChange={setYear} title="Tax year"
                      options={[{ value: "all", label: "All tax years", count: jobs.length },
                        ...years.map((y) => ({ value: y, label: y, count: jobs.filter((j) => j.tax_year === y).length }))]} />
        <CustomSelect value={sortBy} onChange={setSortBy} title="Order" align="right"
                      options={[{ value: "name", label: "Name A–Z" }, { value: "year", label: "Tax year" }, { value: "newest", label: "Newest first" }]} />
        {filtering && (
          <Button variant="ghost" size="sm" onClick={reset} className="h-8 px-2.5 text-xs">
            <RotateCcw className="mr-1 h-3.5 w-3.5" /> Reset
          </Button>
        )}
      </div>

      {shown.length === 0 ? (
        <EmptyState
          icon={UserRound}
          art={filtering ? "search" : "start"}
          title={filtering ? "No returns match" : "No Self Assessment returns yet"}
          description={filtering ? "Change the search or tax year, or reset them." : "Start a return for an individual: a director, a landlord or a sole trader."}
          action={filtering ? { label: "Reset filters", onClick: reset, icon: RotateCcw } : { label: "New return", onClick: onNew, icon: Plus }}
        />
      ) : (
        <Card className="overflow-hidden">
          <ul className="divide-y divide-slate-100">
            {page.paginatedItems.map((j) => {
              const kinds = j.sources.map((s) => SOURCE_LABELS[s]).filter(Boolean);
              return (
                <li key={j.id}>
                  <button type="button" onClick={() => onOpen(j.id)}
                          className="group flex w-full items-center gap-3 px-5 py-3 text-left transition-colors hover:bg-teal-50/60 cursor-pointer">
                    <span className="flex h-9 w-9 shrink-0 items-center justify-center rounded-lg bg-slate-100 text-[12px] font-semibold tracking-wide text-slate-600">
                      {initials(j.person_name)}
                    </span>
                    <span className="min-w-0 flex-1">
                      <span className="flex items-center gap-2">
                        <span className="truncate text-sm font-semibold text-slate-900 group-hover:text-teal-800">{j.person_name}</span>
                        <span className="shrink-0 rounded-md bg-teal-50 px-1.5 py-px text-[10.5px] font-semibold text-teal-800">{j.tax_year}</span>
                      </span>
                      <span className="mt-1 flex flex-wrap items-center gap-1">
                        {kinds.slice(0, SHOWN).map((k) => (
                          <span key={k} className="rounded-md border border-slate-200 px-1.5 py-px text-[10.5px] text-slate-600">{k}</span>
                        ))}
                        {kinds.length > SHOWN && (
                          <span className="text-[10.5px] text-slate-400" title={kinds.slice(SHOWN).join(", ")}>+{kinds.length - SHOWN} more</span>
                        )}
                        {j.company && (
                          <span className="inline-flex items-center gap-1 text-[10.5px] text-slate-500">
                            <Building2 className="h-3 w-3" /> Director of {j.company.name}
                          </span>
                        )}
                      </span>
                    </span>
                    <span className="hidden shrink-0 text-right sm:block">
                      <span className="block text-[10.5px] text-slate-400">Due</span>
                      <span className="block text-xs font-medium text-slate-700">{dueLabel(j.tax_year)}</span>
                    </span>
                    <ChevronRight className="h-4 w-4 text-slate-300 transition group-hover:text-slate-500" />
                  </button>
                </li>
              );
            })}
          </ul>
          <Pagination
            currentPage={page.currentPage} pageSize={page.pageSize} totalPages={page.totalPages} totalItems={page.totalItems}
            startIndex={page.startIndex} endIndex={page.endIndex} pageRange={page.pageRange}
            canPrevPage={page.canPrevPage} canNextPage={page.canNextPage} onPageChange={page.setPage}
            onPageSizeChange={page.setPageSize} onPrevPage={page.prevPage} onNextPage={page.nextPage}
            onFirstPage={page.firstPage} onLastPage={page.lastPage} itemLabel="returns"
          />
        </Card>
      )}
    </div>
  );
}
