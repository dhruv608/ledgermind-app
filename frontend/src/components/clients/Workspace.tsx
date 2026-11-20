"use client";

// The home page as a workspace: a greeting, four numbers that need the firm now (each one filters the list), one list
// of companies and Self Assessment returns with tabs, search, an order and pages, and on the right what to do next and
// what was opened last. The full company table (ticks, delete, add next year) is one click away on the Companies tab.
import React, { useEffect, useMemo, useRef, useState } from "react";
import { AlarmClock, ArrowRight, CalendarClock, ListChecks, Lock, Plus, Search, Table2, X } from "lucide-react";
import type { ClientListItem } from "@/types/engagement";
import type { SaJob, SaJobStatus } from "@/lib/api";
import { Button } from "@/components/ui/button";
import { CustomSelect } from "@/components/ui/custom-select";
import { Pagination } from "@/components/common/Pagination";
import { EmptyState } from "@/components/common/EmptyState";
import { usePagination } from "@/hooks/usePagination";
import { plural, timeAgo } from "@/lib/formatters";
import { signedInEmail } from "@/lib/auth";
import { ChaseClients } from "@/components/clients/ChaseClients";
import { initials, saDueDate } from "@/components/sa/SaReturnsList";

export type HomeTab = "all" | "companies" | "sa";
type Focus = "none" | "overdue" | "due30" | "blocks" | "open";
type Tone = "red" | "amber" | "green" | "grey" | "teal";

const TAB_KEY = "lm.home.tab";
const DAY = 86400000;

const TONES: Record<Tone, string> = {
  red: "bg-rose-50 text-rose-700 ring-rose-200",
  amber: "bg-amber-50 text-amber-800 ring-amber-200",
  green: "bg-emerald-50 text-emerald-700 ring-emerald-200",
  grey: "bg-slate-100 text-slate-600 ring-slate-200",
  teal: "bg-teal-50 text-teal-800 ring-teal-200",
};

/** One row of the list: a company year-end or a person's return, in the same shape */
interface Row {
  id: string;
  kind: "company" | "sa";
  name: string;
  sub: string;
  due: Date | null;
  dueWhat: string;
  pill: { text: string; tone: Tone } | null;
  blocks: number;
  open: number;
  last: string | null;
}

const dayStart = () => new Date(new Date().toDateString()).getTime();
const daysTo = (d: Date | null) => (d ? Math.round((d.getTime() - dayStart()) / DAY) : null);
const isoDate = (iso?: string | null) => (iso ? new Date(`${iso.slice(0, 10)}T00:00:00`) : null);
const shortDate = (d: Date) =>
  d.toLocaleDateString("en-GB", { day: "numeric", month: "short", ...(d.getFullYear() !== new Date().getFullYear() ? { year: "numeric" } : {}) });

function companyRow(c: ClientListItem): Row {
  // The nearer of the accounts deadline (until the year is done) and the next VAT return
  const acc = c.workbook_state === "final" ? null : isoDate(c.accounts_due);
  const vat = c.vat_period_end ? isoDate(c.vat_due) : null;
  const due = acc && vat ? (vat < acc ? vat : acc) : acc || vat;
  const mappings = c.mappings_to_review || 0;
  const points = c.open_audit_findings || 0;
  const pill: Row["pill"] = c.checking ? { text: `Checking ${c.checking}`, tone: "teal" }
    : mappings ? { text: `${mappings} to check`, tone: "amber" }
    : points ? { text: plural(points, "point"), tone: "grey" }
    : c.workbook_state === "final" ? { text: "Done", tone: "green" }
    : c.workbook_state === "draft" ? { text: "In review", tone: "grey" }
    : { text: "Nothing open", tone: "green" };
  return {
    id: c.engagement_id, kind: "company", name: c.client_name, sub: `Company, year end ${c.period_end_date}`,
    due, dueWhat: due && due === vat ? "VAT return" : "Accounts", pill, blocks: 0, open: mappings + points, last: c.last_activity_at || null,
  };
}

// A return's times are kept in UTC with no zone on them: mark them so they are not read as local time
const utc = (iso?: string | null) => (iso ? (/[zZ]|[+-]\d\d:?\d\d$/.test(iso) ? iso : `${iso}Z`) : null);

function saRow(j: SaJob, s: SaJobStatus | undefined, loaded: boolean): Row {
  const blocks = s?.blocks || 0;
  const pill: Row["pill"] = !loaded ? null
    : !s || !s.documents ? { text: "No documents", tone: "grey" }
    : s.final ? { text: "Done", tone: "green" }
    : blocks ? { text: plural(blocks, "block"), tone: "red" }
    : s.client ? { text: plural(s.client, "query", "queries"), tone: "amber" }
    : s.decisions ? { text: plural(s.decisions, "decision"), tone: "grey" }
    : { text: "Ready", tone: "green" };
  return {
    id: j.id, kind: "sa", name: j.person_name, sub: `Self Assessment, ${j.tax_year}`, due: s?.final ? null : saDueDate(j.tax_year),
    dueWhat: "Online return", pill, blocks, open: (s?.client || 0) + (s?.decisions || 0), last: utc(s?.last_activity_at || j.created_at),
  };
}

// Each tile in its own colour with an icon, so it reads without the words; a nought stays grey
const TILE_TONES = {
  red: { box: "border-rose-200 bg-rose-50", ring: "ring-rose-500 border-rose-400", text: "text-rose-700" },
  amber: { box: "border-amber-200 bg-amber-50", ring: "ring-amber-500 border-amber-400", text: "text-amber-700" },
  slate: { box: "border-slate-300 bg-slate-100", ring: "ring-slate-500 border-slate-400", text: "text-slate-700" },
  teal: { box: "border-teal-200 bg-teal-50", ring: "ring-teal-600 border-teal-500", text: "text-teal-800" },
};

function Tile({ value, label, hint, tone, icon: Icon, active, onClick, loading }: {
  value: number; label: string; hint: string; tone: keyof typeof TILE_TONES; icon: React.ElementType; active: boolean;
  onClick: () => void; loading?: boolean;
}) {
  const t = TILE_TONES[tone];
  const lit = loading || value > 0;
  return (
    <button type="button" onClick={onClick} aria-pressed={active}
            className={`rounded-2xl border px-5 py-4 text-left transition hover:shadow-sm focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-teal-600 ${
              lit ? t.box : "border-slate-200 bg-white"} ${active ? `ring-1 ${t.ring}` : ""}`}>
      <span className="flex items-center gap-2.5">
        <span className={`flex h-8 w-8 items-center justify-center rounded-lg bg-white shadow-sm ring-1 ring-inset ${lit ? "ring-black/5" : "ring-slate-200"}`}>
          <Icon className={`h-4 w-4 ${lit ? t.text : "text-slate-400"}`} />
        </span>
        <span className={`text-[13px] font-medium ${lit ? t.text : "text-slate-500"}`}>{label}</span>
      </span>
      {loading ? <span className="mt-3 block h-9 w-12 animate-pulse rounded bg-white/70" />
        : <span className={`mt-3 block text-[32px] font-semibold leading-9 tabular-nums tracking-tight ${lit ? "text-slate-900" : "text-slate-300"}`}>{value}</span>}
      <span className="mt-1 block truncate text-[12px] text-slate-500">{hint}</span>
    </button>
  );
}

export function Workspace({
  clients, saJobs, saStatus, isLoading, onNew, onOpenClient, onOpenReturn, companyTable,
}: {
  clients: ClientListItem[];
  saJobs: SaJob[];
  saStatus: Record<string, SaJobStatus> | null;
  isLoading: boolean;
  onNew: () => void;
  onOpenClient: (engagementId: string) => void;
  onOpenReturn: (jobId: string) => void;
  /** The full company table with its own tools, shown instead of the list on request */
  companyTable: React.ReactNode;
}) {
  const [tab, setTab] = useState<HomeTab>("all");
  const [focus, setFocus] = useState<Focus>("none");
  const [query, setQuery] = useState("");
  const [sortBy, setSortBy] = useState("due");
  const [table, setTable] = useState(false);
  const [chasing, setChasing] = useState(false);
  const searchRef = useRef<HTMLInputElement>(null);

  // The last tab used comes back (a firm doing mostly returns lands on them)
  useEffect(() => {
    try {
      const saved = localStorage.getItem(TAB_KEY);
      // eslint-disable-next-line react-hooks/set-state-in-effect -- browser storage is read after mounting (the server render has none)
      if (saved === "all" || saved === "companies" || saved === "sa") setTab(saved);
    } catch { /* no storage: start on all */ }
  }, []);
  const pickTab = (t: HomeTab) => {
    setTab(t);
    if (t !== "companies") setTable(false);
    try { localStorage.setItem(TAB_KEY, t); } catch { /* fine */ }
  };

  // "/" goes to the search (Ctrl K is Ledge, the assistant), unless the person is typing somewhere
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      const el = e.target as HTMLElement | null;
      const typing = el && (el.isContentEditable || ["INPUT", "TEXTAREA", "SELECT"].includes(el.tagName));
      if (e.key === "/" && !typing && !e.ctrlKey && !e.metaKey && !e.altKey) {
        e.preventDefault();
        setTable(false);
        searchRef.current?.focus();
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);

  const loaded = saStatus !== null;
  const rows = useMemo(
    () => [...clients.map(companyRow), ...saJobs.map((j) => saRow(j, saStatus?.[j.id], loaded))],
    [clients, saJobs, saStatus, loaded]
  );

  const late = (r: Row) => (daysTo(r.due) ?? 1) < 0;
  const within30 = (r: Row) => { const d = daysTo(r.due); return d !== null && d >= 0 && d <= 30; };
  const counts = {
    overdue: rows.filter(late).length,
    due30: rows.filter(within30).length,
    blocks: rows.filter((r) => r.blocks > 0).length,
    open: rows.reduce((n, r) => n + r.open, 0),
  };

  const shown = useMemo(() => {
    const q = query.toLowerCase().trim();
    const list = rows.filter((r) =>
      (tab === "all" || (tab === "companies" ? r.kind === "company" : r.kind === "sa"))
      && (focus === "none" || (focus === "overdue" ? late(r) : focus === "due30" ? within30(r) : focus === "blocks" ? r.blocks > 0 : r.open > 0))
      && (!q || r.name.toLowerCase().includes(q) || r.sub.toLowerCase().includes(q)));
    const far = 8.64e15;
    return list.sort((a, b) => sortBy === "name" ? a.name.localeCompare(b.name)
      : sortBy === "recent" ? (b.last || "").localeCompare(a.last || "")
      : (a.due?.getTime() ?? far) - (b.due?.getTime() ?? far) || a.name.localeCompare(b.name));
     
  }, [rows, tab, focus, query, sortBy]);

  const page = usePagination({ items: shown, initialPageSize: 25, resetDependencies: [tab, focus, query, sortBy] });

  // What to do next: blocks first, then accounts to check, then deadlines passed, then returns waiting on the client
  const nextUp = useMemo(() => {
    const items: { key: string; text: string; go: () => void }[] = [];
    for (const r of rows.filter((x) => x.kind === "sa" && x.blocks).sort((a, b) => b.blocks - a.blocks).slice(0, 2))
      items.push({ key: `b${r.id}`, text: `${r.name}: answer ${plural(r.blocks, "block")}`, go: () => onOpenReturn(r.id) });
    for (const c of clients.filter((x) => x.mappings_to_review).sort((a, b) => (b.mappings_to_review || 0) - (a.mappings_to_review || 0)).slice(0, 2))
      items.push({ key: `m${c.engagement_id}`, text: `${c.client_name}: ${plural(c.mappings_to_review || 0, "account")} to check`, go: () => onOpenClient(c.engagement_id) });
    for (const r of rows.filter((x) => x.kind === "company" && late(x)).slice(0, 2))
      items.push({ key: `l${r.id}`, text: `${r.name}: ${r.dueWhat.replace("Accounts", "accounts").replace("Online", "online")} overdue`, go: () => onOpenClient(r.id) });
    const waiting = saJobs.filter((j) => saStatus?.[j.id]?.client).length;
    if (waiting) items.push({ key: "waiting", text: `Draft emails: ${plural(waiting, "return")} waiting on client answers`, go: () => setChasing(true) });
    return items.slice(0, 4);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [rows, clients, saJobs, saStatus]);

  const recent = useMemo(() => [...rows].filter((r) => r.last).sort((a, b) => (b.last || "").localeCompare(a.last || "")).slice(0, 3), [rows]);
  const open = (r: Row) => (r.kind === "company" ? onOpenClient(r.id) : onOpenReturn(r.id));

  const [who, setWho] = useState("");
  useEffect(() => {
    const first = (signedInEmail() || "").split("@")[0].split(/[._\-\d]+/)[0];
    // eslint-disable-next-line react-hooks/set-state-in-effect -- the signed-in email is in browser storage, read after mounting
    if (first.length > 1) setWho(first[0].toUpperCase() + first.slice(1).toLowerCase());
  }, []);
  const hour = new Date().getHours();
  const greeting = hour < 12 ? "Good morning" : hour < 18 ? "Good afternoon" : "Good evening";
  const today = new Date().toLocaleDateString("en-GB", { weekday: "long", day: "numeric", month: "long" });
  const companyCount = useMemo(() => new Set(clients.map((c) => c.company_key || c.client_name.toLowerCase())).size, [clients]);

  // The brief under the greeting: the nearest deadline, what is overdue and who is waiting, from the figures shown
  const brief = useMemo(() => {
    if (isLoading) return "";
    const parts: string[] = [];
    const lateRows = rows.filter(late);
    if (lateRows.length) parts.push(`${lateRows.length === 1 ? `${lateRows[0].name}'s ${lateRows[0].dueWhat.replace("Accounts", "accounts").replace("Online", "online")} is` : `${lateRows.length} deadlines are`} overdue.`);
    const next = rows.filter((r) => { const d = daysTo(r.due); return d !== null && d >= 0; })
      .sort((a, b) => (a.due!.getTime() - b.due!.getTime()))[0];
    if (next) {
      const d = daysTo(next.due)!;
      const when = d === 0 ? "today" : d === 1 ? "tomorrow" : `in ${d} days`;
      const same = rows.filter((r) => r.due && r.due.getTime() === next.due!.getTime()).length;
      parts.push(same > 1 ? `${same} ${next.kind === "sa" ? "returns are" : "deadlines are"} due ${when}, on ${shortDate(next.due!)}.`
        : `${next.name}'s ${next.dueWhat.replace("Accounts", "accounts").replace("Online", "online")} is due ${when}.`);
    }
    const waiting = saJobs.filter((j) => saStatus?.[j.id]?.client).length;
    if (waiting) parts.push(`${plural(waiting, "return is", "returns are")} waiting on client answers.`);
    return parts.length ? parts.join(" ") : "Nothing is due soon and nothing is waiting on you.";
     
  }, [rows, saJobs, saStatus, isLoading]);

  const toggleFocus = (f: Focus) => setFocus((cur) => (cur === f ? "none" : f));
  // The tabs and the rows' initials in the app's teal
  const tabs: { id: HomeTab; label: string; count: number; on: string; badge: string; idle: string }[] = [
    { id: "all", label: "All", count: rows.length, on: "bg-teal-700 text-white", badge: "bg-white/20 text-white", idle: "bg-teal-100 text-teal-800" },
    { id: "companies", label: "Companies", count: clients.length, on: "bg-teal-700 text-white", badge: "bg-white/20 text-white", idle: "bg-teal-100 text-teal-800" },
    { id: "sa", label: "Self Assessment", count: saJobs.length, on: "bg-teal-700 text-white", badge: "bg-white/20 text-white", idle: "bg-teal-100 text-teal-800" },
  ];
  const FOCUS_LABEL: Record<Focus, string> = { none: "", overdue: "Overdue", due30: "Due in 30 days", blocks: "Returns with blocks", open: "Points to clear" };

  return (
    <div className="space-y-5">
      <div className="flex flex-col gap-4 rounded-2xl border border-slate-200 bg-white px-6 py-5 sm:flex-row sm:items-start sm:justify-between">
        <div className="min-w-0">
          <h1 className="text-[26px] font-semibold leading-tight tracking-tight text-slate-900">
            {greeting}{who && <>, <span className="text-teal-700">{who}</span></>}
          </h1>
          <p className="mt-1 text-sm text-slate-500">
            {today}, {plural(companyCount, "company", "companies")} and {plural(saJobs.length, "return")}
          </p>
          {brief && <p className="mt-3 max-w-2xl text-[14px] leading-relaxed text-slate-700">{brief}</p>}
        </div>
        <Button onClick={onNew} variant="primary" className="h-9 shrink-0 self-start">
          <Plus className="mr-1.5 h-4 w-4" /> New client or return
        </Button>
      </div>

      <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
        <Tile value={counts.overdue} label="Overdue" hint="Accounts or VAT past the due date" tone="red" icon={AlarmClock} active={focus === "overdue"} onClick={() => toggleFocus("overdue")} loading={isLoading} />
        <Tile value={counts.due30} label="Due in 30 days" hint="Accounts, VAT and returns" tone="amber" icon={CalendarClock} active={focus === "due30"} onClick={() => toggleFocus("due30")} loading={isLoading} />
        <Tile value={counts.blocks} label="Returns with blocks" hint="Cannot be finished yet" tone="teal" icon={Lock} active={focus === "blocks"} onClick={() => toggleFocus("blocks")} loading={!loaded} />
        <Tile value={counts.open} label="Points to clear" hint="Checks, queries and decisions" tone="slate" icon={ListChecks} active={focus === "open"} onClick={() => toggleFocus("open")} loading={isLoading || !loaded} />
      </div>

      <div className="grid gap-4 lg:grid-cols-[minmax(0,1fr)_260px]">
        <div className={`min-w-0 overflow-hidden rounded-xl border border-slate-200 bg-white ${table ? "lg:col-span-2" : ""}`}>
          <div className="flex flex-wrap items-center gap-2 border-b border-slate-200 bg-slate-50/70 px-3 py-2">
            <div role="tablist" className="flex gap-1">
              {tabs.map((t) => (
                <button key={t.id} type="button" role="tab" aria-selected={tab === t.id} onClick={() => pickTab(t.id)}
                        className={`inline-flex items-center gap-1.5 rounded-lg px-3 py-1.5 text-[13px] font-medium transition ${tab === t.id
                          ? `${t.on} shadow-sm` : "text-slate-600 hover:bg-white hover:text-slate-900"}`}>
                  {t.label}
                  <span className={`rounded-full px-1.5 text-[11px] font-semibold tabular-nums ${tab === t.id ? t.badge : t.idle}`}>{t.count}</span>
                </button>
              ))}
            </div>
            <div className="ml-auto flex flex-wrap items-center gap-2">
              {!table && (
                <>
                  <div className="relative w-44 sm:w-52">
                    <Search className="absolute left-2.5 top-2 h-3.5 w-3.5 text-slate-400" />
                    <input ref={searchRef} value={query} onChange={(e) => setQuery(e.target.value)} placeholder="Search name or year"
                           className="h-7.5 w-full rounded-lg border border-slate-200 bg-white py-1.5 pl-8 pr-8 text-xs outline-none focus:border-teal-600 focus:ring-1 focus:ring-teal-600" />
                    {!query && (
                      <kbd className="pointer-events-none absolute right-2 top-1.5 rounded border border-slate-200 bg-slate-50 px-1 text-[10px] font-medium text-slate-400" title="Press / to search">/</kbd>
                    )}
                    {query && (
                      <button onClick={() => setQuery("")} className="absolute right-2 top-1.5 text-slate-400 hover:text-slate-600" title="Clear search">
                        <X className="h-4 w-4" />
                      </button>
                    )}
                  </div>
                  <CustomSelect value={sortBy} onChange={setSortBy} title="Order" align="right"
                                options={[{ value: "due", label: "Due date" }, { value: "name", label: "Name A–Z" }, { value: "recent", label: "Recently worked on" }]} />
                </>
              )}
              {tab === "companies" && (
                <button type="button" onClick={() => setTable((v) => !v)} title="Tick, delete and add next year in the full table"
                        className={`inline-flex items-center gap-1 rounded-lg px-2 py-1.5 text-xs transition ${table ? "bg-teal-700 text-white" : "text-slate-600 hover:bg-slate-100"}`}>
                  <Table2 className="h-3.5 w-3.5" /> {table ? "Back to list" : "Full table"}
                </button>
              )}
            </div>
          </div>

          {focus !== "none" && !table && (
            <div className="flex items-center gap-2 border-b border-slate-100 px-4 py-2 text-xs text-slate-600">
              Showing {FOCUS_LABEL[focus].toLowerCase()} only
              <button type="button" onClick={() => setFocus("none")} className="inline-flex items-center gap-0.5 text-teal-700 hover:underline">
                <X className="h-3 w-3" /> Show all
              </button>
            </div>
          )}

          {table ? (
            <div className="p-4">{companyTable}</div>
          ) : isLoading ? (
            <div className="space-y-px p-2">{[0, 1, 2, 3].map((i) => <div key={i} className="h-14 animate-pulse rounded-lg bg-slate-50" />)}</div>
          ) : shown.length === 0 ? (
            <EmptyState
              icon={Search}
              art={rows.length ? "search" : "start"}
              title={rows.length ? "Nothing matches" : "No clients yet"}
              description={rows.length ? "Change the search or the filter." : "Add a company's year-end or a person's Self Assessment return to start."}
              action={rows.length ? { label: "Show all", onClick: () => { setFocus("none"); setQuery(""); pickTab("all"); }, icon: X }
                : { label: "New client or return", onClick: onNew, icon: Plus }}
            />
          ) : (
            <>
              <ul className="divide-y divide-slate-100">
                {page.paginatedItems.map((r) => {
                  const d = daysTo(r.due);
                  return (
                    <li key={`${r.kind}:${r.id}`}>
                      <button type="button" onClick={() => open(r)}
                              className="group grid w-full grid-cols-[36px_minmax(0,1fr)_auto] items-center gap-3 px-4 py-2.5 text-left transition-colors hover:bg-slate-50 sm:grid-cols-[36px_minmax(0,1fr)_140px_110px]">
                        <span className="flex h-9 w-9 items-center justify-center rounded-lg bg-teal-50 text-[12px] font-semibold text-teal-800">
                          {initials(r.name)}
                        </span>
                        <span className="min-w-0">
                          <span className="block truncate text-sm font-medium text-slate-900 group-hover:text-teal-800">{r.name}</span>
                          <span className="block truncate text-xs text-slate-500">{r.sub}</span>
                        </span>
                        <span className="hidden sm:block">
                          {r.pill ? (
                            <span className={`inline-flex whitespace-nowrap rounded-full px-2 py-0.5 text-[11px] font-medium ring-1 ring-inset ${TONES[r.pill.tone]}`}>
                              {r.pill.text}
                            </span>
                          ) : <span className="block h-5 w-16 animate-pulse rounded-full bg-slate-100" />}
                        </span>
                        <span className={`whitespace-nowrap text-right text-xs ${d === null ? "text-slate-400" : d < 0 ? "font-medium text-rose-600" : d <= 30 ? "font-medium text-amber-700" : "text-slate-600"}`}
                              title={r.due ? `${r.dueWhat} due ${r.due.toLocaleDateString("en-GB")}` : undefined}>
                          {r.due ? `${d !== null && d < 0 ? "Overdue" : "Due"} ${shortDate(r.due)}` : "Nothing due"}
                        </span>
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
                onFirstPage={page.firstPage} onLastPage={page.lastPage} itemLabel="clients"
              />
            </>
          )}
        </div>

        {!table && (
          <aside className="space-y-4 self-start rounded-xl border border-slate-200 bg-white p-4">
            <div>
              <h2 className="text-sm font-semibold text-slate-900">Next up</h2>
              {nextUp.length === 0 ? (
                <p className="mt-2 text-xs text-slate-500">{loaded ? "Nothing waiting on you." : "Working it out..."}</p>
              ) : (
                <ul className="mt-1 divide-y divide-slate-100">
                  {nextUp.map((n) => (
                    <li key={n.key}>
                      <button type="button" onClick={n.go}
                              className="group flex w-full items-start justify-between gap-2 py-2.5 text-left text-[13px] text-slate-700 hover:text-teal-800">
                        <span>{n.text}</span>
                        <ArrowRight className="mt-0.5 h-3.5 w-3.5 shrink-0 text-slate-300 group-hover:text-teal-700" />
                      </button>
                    </li>
                  ))}
                </ul>
              )}
            </div>
            {recent.length > 0 && (
              <div>
                <h2 className="text-sm font-semibold text-slate-900">Recently worked on</h2>
                <ul className="mt-1 divide-y divide-slate-100">
                  {recent.map((r) => (
                    <li key={`${r.kind}:${r.id}`}>
                      <button type="button" onClick={() => open(r)}
                              className="flex w-full items-center justify-between gap-2 py-2 text-left text-[13px] text-slate-700 hover:text-teal-800">
                        <span className="truncate">{r.name}</span>
                        <span className="shrink-0 text-[11px] text-slate-400">{timeAgo(r.last)}</span>
                      </button>
                    </li>
                  ))}
                </ul>
              </div>
            )}
          </aside>
        )}
      </div>
      <ChaseClients open={chasing} onClose={() => setChasing(false)} jobs={saJobs} status={saStatus} onOpenReturn={onOpenReturn} />
    </div>
  );
}
