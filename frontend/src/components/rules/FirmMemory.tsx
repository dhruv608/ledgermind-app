"use client";

import { useEffect, useMemo, useState } from "react";
import { toast } from "@/lib/notify";
import { Search, Trash2 } from "lucide-react";
import { Card } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { ConfirmDialog } from "@/components/ui/confirm-dialog";
import { Pagination } from "@/components/common/Pagination";
import { SkeletonRows } from "@/components/common/SkeletonRows";
import { usePagination } from "@/hooks/usePagination";
import { api, type MemoryEntry } from "@/lib/api";
import { plural, serverDate } from "@/lib/formatters";
import { cn } from "@/lib/utils";

// The memory keeps names in small letters: shown with a capital first letter
const shownName = (n: string) => n.charAt(0).toUpperCase() + n.slice(1);
const when = (iso: string | null) =>
  iso ? serverDate(iso).toLocaleDateString("en-GB", { day: "2-digit", month: "short", year: "numeric" }) : "";
const USES = [
  { id: "all", label: "All" },
  { id: "unused", label: "Not used now" },
  { id: "used", label: "Used now" },
] as const;
type Use = (typeof USES)[number]["id"];

/** The firm memory: every code an accountant confirmed for an account name, used for every new client. A wrong one
 *  (a test client's choice, a mistake) is removed here; clients already coded keep their codes. */
export function FirmMemory({ onChanged }: { onChanged?: () => void }) {
  const [rows, setRows] = useState<MemoryEntry[] | null>(null);
  const [search, setSearch] = useState("");
  const [use, setUse] = useState<Use>("all");
  const [ticked, setTicked] = useState<Set<number>>(new Set());
  const [asking, setAsking] = useState<number[] | null>(null);
  const [busy, setBusy] = useState(false);

  const load = () => api.getFirmMemory().then(setRows).catch((e) => { toast.error(e.message); setRows([]); });
  useEffect(() => { load(); }, []);

  const unused = (rows || []).filter((r) => r.clients === 0).length;
  const countOf = (u: Use) => (u === "all" ? rows?.length ?? 0 : u === "unused" ? unused : (rows?.length ?? 0) - unused);
  const shown = useMemo(() => {
    const q = search.trim().toLowerCase();
    return (rows || []).filter((r) =>
      (use === "all" || (use === "unused" ? r.clients === 0 : r.clients > 0)) &&
      (!q || r.name.includes(q) || String(r.std_code).includes(q) || r.std_name.toLowerCase().includes(q)));
  }, [rows, search, use]);
  const page = usePagination({ items: shown, initialPageSize: 25, resetDependencies: [search, use] });

  const tick = (id: number) => setTicked((t) => { const n = new Set(t); if (n.has(id)) n.delete(id); else n.add(id); return n; });
  const allOnPage = page.paginatedItems.length > 0 && page.paginatedItems.every((r) => ticked.has(r.id));

  const remove = async () => {
    if (!asking) return;
    setBusy(true);
    try {
      const n = await api.removeFirmMemory(asking);
      toast.success(`${plural(n, "entry", "entries")} removed`);
      setTicked(new Set());
      setAsking(null);
      await load();
      onChanged?.();
    } catch (e) {
      toast.error(e instanceof Error ? e.message : "Could not remove them");
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="space-y-4">
      <p className="max-w-3xl text-[13px] leading-relaxed text-slate-600">
        Codes the firm&apos;s accountants confirmed, by account name. Every new client gets them (after its own codes from
        last year). Remove a wrong one and the next upload asks the rules and the AI again; clients already coded keep
        their codes.
        {unused > 0 && (
          <span className="mt-1.5 block text-slate-500">
            <span className="font-semibold text-amber-700">{plural(unused, "entry", "entries")}</span> {unused === 1 ? "is" : "are"} not
            used by any client now: most likely learned from deleted clients, often tests.
          </span>
        )}
      </p>

      <Card className="overflow-hidden">
        <div className="flex flex-wrap items-center gap-2 border-b border-slate-100 px-4 py-3">
          <div className="relative min-w-[220px] flex-1">
            <Search className="absolute left-2.5 top-2.5 h-3.5 w-3.5 text-slate-400" />
            <Input value={search} onChange={(e) => setSearch(e.target.value)} placeholder="Search account name or code"
                   className="h-8 border-slate-200 bg-white pl-8 text-xs" />
          </div>
          <div className="inline-flex rounded-lg border border-slate-200 bg-white p-0.5 text-xs">
            {USES.map((u) => (
              <button key={u.id} type="button" onClick={() => setUse(u.id)}
                      className={cn("rounded-md px-2.5 py-1 font-medium transition-colors",
                                    use === u.id ? "bg-teal-50 text-teal-800" : "text-slate-600 hover:bg-teal-50/60 hover:text-teal-800")}>
                {u.label} <span className="ml-0.5 text-[11px] tabular-nums text-slate-400">{rows ? countOf(u.id) : ""}</span>
              </button>
            ))}
          </div>
          {ticked.size > 0 && (
            <Button size="sm" variant="outline" className="h-8 border-rose-200 text-xs text-rose-700 hover:bg-rose-50"
                    onClick={() => setAsking([...ticked])}>
              <Trash2 className="mr-1 h-3.5 w-3.5" /> Remove {plural(ticked.size, "entry", "entries")}
            </Button>
          )}
        </div>

        {rows === null ? (
          <div className="p-4"><SkeletonRows rows={6} /></div>
        ) : shown.length === 0 ? (
          <p className="px-4 py-8 text-center text-[13px] text-slate-500">
            {search ? "Nothing matches the search." : use === "unused" ? "Every entry is used by a client." : "The firm memory is empty."}
          </p>
        ) : (
          <table className="w-full text-xs">
            <thead className="border-b border-slate-200 bg-slate-50 text-[10.5px] uppercase tracking-wide text-slate-500">
              <tr className="text-left">
                <th className="w-10 px-4 py-2">
                  <input type="checkbox" checked={allOnPage} aria-label="Tick every entry on this page" className="accent-teal-700"
                         onChange={() => setTicked((t) => {
                           const n = new Set(t);
                           page.paginatedItems.forEach((r) => (allOnPage ? n.delete(r.id) : n.add(r.id)));
                           return n;
                         })} />
                </th>
                <th className="px-3 py-2 font-semibold">Account name</th>
                <th className="px-3 py-2 font-semibold">Goes to</th>
                <th className="px-3 py-2 font-semibold">Used by</th>
                <th className="px-3 py-2 font-semibold">Confirmed by</th>
                <th className="w-10 px-4 py-2" />
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-100">
              {page.paginatedItems.map((r) => (
                <tr key={r.id} className={cn("group transition-colors hover:bg-teal-50/40", ticked.has(r.id) && "bg-teal-50/60")}>
                  <td className="px-4 py-2.5">
                    <input type="checkbox" checked={ticked.has(r.id)} onChange={() => tick(r.id)} className="accent-teal-700"
                           aria-label={`Tick ${r.name}`} />
                  </td>
                  <td className="px-3 py-2.5 text-[13px] font-medium text-slate-900">{shownName(r.name)}</td>
                  <td className="px-3 py-2.5 text-slate-700">
                    <span className="mr-2 rounded border border-teal-100 bg-teal-50 px-1.5 py-px font-mono text-[11px] font-semibold text-teal-800">
                      {String(r.std_code).padStart(4, "0")}
                    </span>
                    {r.std_name}
                  </td>
                  <td className="px-3 py-2.5">
                    {r.clients ? (
                      <span className="text-slate-700">{plural(r.clients, "client")}</span>
                    ) : (
                      <span className="rounded-full bg-amber-50 px-2 py-0.5 text-[11px] font-semibold text-amber-800 ring-1 ring-inset ring-amber-200">Not used</span>
                    )}
                  </td>
                  <td className="px-3 py-2.5 leading-tight">
                    <span className="block text-slate-700">{r.confirmed_by || "Unknown"}</span>
                    {r.confirmed_at && <span className="text-[11px] text-slate-400">{when(r.confirmed_at)}</span>}
                  </td>
                  <td className="px-4 py-2.5 text-right">
                    <button type="button" onClick={() => setAsking([r.id])} title="Remove this entry" aria-label={`Remove ${r.name}`}
                            className="rounded-md p-1 text-slate-400 opacity-0 transition hover:bg-rose-50 hover:text-rose-600 focus:opacity-100 group-hover:opacity-100">
                      <Trash2 className="h-3.5 w-3.5" />
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
        {shown.length > 0 && (
          <Pagination currentPage={page.currentPage} pageSize={page.pageSize} totalPages={page.totalPages}
                      totalItems={page.totalItems} startIndex={page.startIndex} endIndex={page.endIndex}
                      pageRange={page.pageRange} canPrevPage={page.canPrevPage} canNextPage={page.canNextPage}
                      onPageChange={page.setPage} onPageSizeChange={page.setPageSize} onPrevPage={page.prevPage}
                      onNextPage={page.nextPage} onFirstPage={page.firstPage} onLastPage={page.lastPage}
                      pageSizeOptions={[25, 50, 100]} itemLabel="entries" />
        )}
      </Card>

      <ConfirmDialog
        isOpen={asking !== null}
        onClose={() => !busy && setAsking(null)}
        onConfirm={remove}
        isLoading={busy}
        title={`Remove ${plural(asking?.length || 0, "entry", "entries")} from the firm memory?`}
        description="The app forgets these codes for new clients: the next upload asks the rules and the AI again. Clients already coded keep their codes."
        confirmText="Remove"
      />
    </div>
  );
}
