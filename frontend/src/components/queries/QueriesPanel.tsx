"use client";

import { useEffect, useMemo, useState } from "react";
import { toast } from "@/lib/notify";
import type { LucideIcon } from "lucide-react";
import {
  ArrowRight,
  Briefcase,
  Calculator,
  CalendarCheck,
  Check,
  ChevronDown,
  ChevronRight,
  FileSearch,
  FileText,
  GitCompareArrows,
  HelpCircle,
  Landmark,
  ListChecks,
  Loader2,
  Mail,
  MessageSquareMore,
  OctagonX,
  Package,
  Receipt,
  RotateCcw,
  Search,
  TrendingUp,
  User,
  UserCog,
  Users,
  Wrench,
} from "lucide-react";
import { api } from "@/lib/api";
import type { JobQueries, JobQuery, QueryAudience, QueryUpdate } from "@/lib/api";
import { formatCurrency, plural } from "@/lib/formatters";
import { Card } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { CustomSelect } from "@/components/ui/custom-select";
import { Input } from "@/components/ui/input";
import { Pagination } from "@/components/common/Pagination";
import { usePagination } from "@/hooks/usePagination";
import { SectionHeader } from "@/components/ui/section-header";
import { Tabs } from "@/components/ui/tabs";
import { text } from "@/lib/ui";
import { StatusChip } from "@/components/ui/status-chip";
import { ClientEmailDialog } from "@/components/clients/ClientEmailDialog";
import { SkeletonRows } from "@/components/common/SkeletonRows";
import { cn } from "@/lib/utils";

export type GoTo = "data" | "books" | "review" | "accounts";

const AUDIENCES: { id: QueryAudience; label: string; icon: LucideIcon; help: string }[] = [
  { id: "CLIENT", label: "For the client", icon: User, help: "Only the client can answer these: send them, then enter the answers." },
  { id: "ACCOUNTANT", label: "For you", icon: Briefcase, help: "Judgements and approvals for the accountant." },
  { id: "INTERNAL", label: "Fix in the app", icon: Wrench, help: "Fixes for the preparer in the app. Never sent to the client." },
];

// Where each query comes from (the tab to fix it on comes with the query: go_to)
const SOURCE: Record<JobQuery["source"], string> = {
  data: "Files", books: "Books", review: "Review", rules: "Query rules", gl: "GL scrutiny", raised: "Raised by hand",
};

// Two states on screen: open or done (an answer saved, or Done pressed; a query the data now answers closes by itself)
export const isOpen = (q: JobQuery) => q.status === "OPEN";

// Topics, in the order they are listed: each query's topic from its rule code (BK-04, U-PAY-001, CT-CA-001 ...) or,
// for the Data check and the Books tab, from where it comes
const TOPICS: { id: string; label: string; icon: LucideIcon; refs?: RegExp; keys?: RegExp }[] = [
  { id: "files", label: "Files to send", icon: FileText, keys: /^data:/ },
  { id: "bank", label: "Bank", icon: Landmark, refs: /^(BK|U-BNK|FRS-F)\b/, keys: /^books:(bank|money_in|money_out|transfer|payee)/ },
  { id: "payroll", label: "Payroll and subcontractors", icon: Users, refs: /^(PY(?!-MOVE)|U-PAY|U-SUB|C-CIS|C-COS|C-LEV)\b/ },
  { id: "vat", label: "VAT", icon: Receipt, refs: /^(V-|VT|E-VAT|C-VAT)/ },
  { id: "director", label: "Director's loan, dividends and related parties", icon: UserCog, refs: /^(DL|U-DLA|U-DIV|RP)\b/ },
  { id: "assets", label: "Fixed assets and leases", icon: Package, refs: /^(CT-CA|U-FA|T-FA|C-FA|U-DT|U-LSE)\b/ },
  { id: "yearend", label: "Year end: accruals, prepayments and stock", icon: CalendarCheck, refs: /^(U-ADJ|U-ACC|U-PRE|YE|G\d|C-WIP|PS-REV)/ },
  { id: "income", label: "Sales and other income", icon: TrendingUp, refs: /^(U-REV|[A-Z]+-REV|U-GRT|U-INS|P-DEP)\b/ },
  { id: "tax", label: "Corporation tax", icon: Calculator, refs: /^(CT|U-CT)\b/ },
  { id: "gl", label: "Ledger lines asked about", icon: FileSearch, keys: /^gl:/ },
  { id: "change", label: "Changes from last year", icon: GitCompareArrows, refs: /^PY-MOVE/ },
  { id: "general", label: "General questions", icon: HelpCircle, refs: /^SQ\b/, keys: /^books:standard/ },
  { id: "other", label: "Ledger and other checks", icon: ListChecks },
];
// A query raised by hand on an area page with no point: its topic from the area
const AREA_TOPIC: Record<string, string> = {
  bank: "bank", payroll: "payroll", vat: "vat", dla: "director", fixed: "assets", loans: "assets", accruals: "yearend",
  stock: "yearend", sales: "income", tax: "tax",
};
const topicOf = (q: JobQuery) =>
  (q.source === "data" && TOPICS[0]) ||
  (q.source === "raised" && !q.ref && TOPICS.find((t) => t.id === AREA_TOPIC[q.area || ""])) ||
  TOPICS.find((t) => (t.refs && q.ref && t.refs.test(q.ref)) || (t.keys && t.keys.test(q.key))) ||
  TOPICS[TOPICS.length - 1];

type Show = "open" | "answered" | "all";

/** The Queries tab: one list of everything the app asks about the job (the Data check at upload, the Books tab's
 *  client questions and the review points after), split by who answers and grouped by topic. Questions that must be
 *  answered come first in each topic: the job cannot be finished until they are. Answers saved here also show on the
 *  Books and Review tabs. */
export function QueriesPanel({
  engagementId,
  clientName,
  yearEnd,
  onGoTo,
  load,
  onLoaded,
}: {
  engagementId: string;
  clientName: string;
  yearEnd: string | null;
  onGoTo: (tab: GoTo) => void;
  /** The list the page already asked for (shared, so opening the tab does not ask again) */
  load?: () => Promise<JobQueries>;
  onLoaded?: (q: JobQueries) => void;
}) {
  const [data, setData] = useState<JobQueries | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [audience, setAudience] = useState<QueryAudience>("CLIENT");
  const [show, setShow] = useState<Show>("open");
  const [search, setSearch] = useState("");
  const [openKey, setOpenKey] = useState<string | null>(null);
  const [saving, setSaving] = useState<string | null>(null);
  const [emailOpen, setEmailOpen] = useState(false);

  const loaded = (d: JobQueries) => {
    setData(d);
    onLoaded?.(d);
  };

  // A new job starts empty until its list arrives
  const [prevEngagementId, setPrevEngagementId] = useState(engagementId);
  if (engagementId !== prevEngagementId) {
    setPrevEngagementId(engagementId);
    setData(null);
    setError(null);
  }
  useEffect(() => {
    (load ? load() : api.getQueries(engagementId)).then(loaded).catch((e) => setError(e.message));
    // eslint-disable-next-line react-hooks/exhaustive-deps -- runs once per engagementId: load and loaded are recreated each render
  }, [engagementId]);
  useEffect(() => {
    const again = () => { api.getQueries(engagementId).then(loaded).catch(() => undefined); };
    window.addEventListener("assistant-action", again);
    return () => window.removeEventListener("assistant-action", again);
    // eslint-disable-next-line react-hooks/exhaustive-deps -- listener set once per engagementId: loaded is recreated each render
  }, [engagementId]);

  const save = async (update: QueryUpdate, done?: string) => {
    setSaving(update.key);
    try {
      loaded(await api.saveQuery(engagementId, update));
      if (done) toast.success(done);
    } catch (e) {
      toast.error((e as Error).message);
    } finally {
      setSaving(null);
    }
  };

  const forAudience = useMemo(() => (data?.queries || []).filter((q) => q.audience === audience), [data, audience]);
  const answered = forAudience.filter((q) => !isOpen(q)).length;
  const shown = useMemo(() => {
    const words = search.toLowerCase().trim();
    const order = (q: JobQuery) => TOPICS.indexOf(topicOf(q)) * 2 + (q.blocking && isOpen(q) ? 0 : 1);
    return forAudience
      .filter((q) => (show === "all" ? true : show === "open" ? isOpen(q) : !isOpen(q)))
      .filter((q) => !words || `${q.title} ${q.detail} ${q.items.map((i) => i.text).join(" ")}`.toLowerCase().includes(words))
      .sort((a, b) => order(a) - order(b));
  }, [forAudience, show, search]);

  // Queries of one kind under one topic ('Bank statement: ...' for 9 accounts) as one group row
  const units = useMemo(() => {
    const kind = (q: JobQuery) => {
      const head = q.title.includes(":") ? q.title.split(":")[0].trim() : "";
      return head && head.length <= 40 ? `${topicOf(q).id}|${head}` : "";
    };
    const sizes: Record<string, number> = {};
    shown.forEach((q) => { const k = kind(q); if (k) sizes[k] = (sizes[k] || 0) + 1; });
    const out: ({ kind: "one"; q: JobQuery } | { kind: "group"; key: string; head: string; items: JobQuery[] })[] = [];
    const placed: Record<string, { items: JobQuery[] }> = {};
    shown.forEach((q) => {
      const k = kind(q);
      if (k && sizes[k] >= 3) {
        if (!placed[k]) {
          placed[k] = { items: [] };
          out.push({ kind: "group", key: k, head: q.title.split(":")[0].trim(), items: placed[k].items });
        }
        placed[k].items.push(q);
      } else {
        out.push({ kind: "one", q });
      }
    });
    return out;
  }, [shown]);
  const page = usePagination({ items: units, initialPageSize: 20, resetDependencies: [audience, show, search] });
  const topicCounts = useMemo(() => {
    const c: Record<string, number> = {};
    shown.forEach((q) => (c[topicOf(q).id] = (c[topicOf(q).id] || 0) + 1));
    return c;
  }, [shown]);

  // The client email: every open client query (a grouped bank query lists its unanswered lines)
  const clientOpen = (data?.queries || []).filter((q) => q.audience === "CLIENT" && isOpen(q));
  const emailGroups = [
    { title: "Documents and information we still need:", items: documentLines(clientOpen.filter((q) => q.source === "data")) },
    {
      title: "Questions about the year:",
      items: clientOpen.filter((q) => q.source !== "data").flatMap((q) =>
        q.items.length > 1
          ? [`${q.title}. ${q.detail}`, ...q.items.filter((i) => !i.answered).map((i) => `   - ${i.text}`)]
          : [q.items[0]?.text || (q.source === "rules" ? `${q.title}. ${q.detail}` : `${q.title}${q.detail ? `: ${q.detail.split("\n")[0]}` : ""}`)]
      ),
    },
  ];

  if (error) {
    return (
      <Card className="px-4 py-3.5">
        <p className="text-sm text-rose-700">{error}</p>
      </Card>
    );
  }
  if (!data) {
    return (
      <Card className="px-4 py-3.5">
        <SkeletonRows rows={6} />
      </Card>
    );
  }

  const help = AUDIENCES.find((a) => a.id === audience)!.help;

  return (
    <div className="space-y-4">
      <ClientEmailDialog isOpen={emailOpen} onClose={() => setEmailOpen(false)} client={clientName} yearEnd={yearEnd} groups={emailGroups} />

      <Card className="px-4 py-3.5">
        <SectionHeader
          icon={MessageSquareMore}
          title="Queries" page
          description="Everything we need to ask about this job, in one list, by topic. Answer each one here or mark it done."
          actions={
            audience === "CLIENT" && clientOpen.length > 0 ? (
              <Button size="sm" variant="primary" onClick={() => setEmailOpen(true)}>
                <Mail className="mr-1.5 h-3.5 w-3.5" /> Make client email
              </Button>
            ) : undefined
          }
        />

        {/* Where it stands, in one line */}
        <p className={cn("mt-1 pl-[2.375rem]", text.meta)}>
          {data.open === 0 ? (
            <span className="font-medium text-emerald-700">No open queries.</span>
          ) : (
            <>
              {answered} of {forAudience.length} answered
              {data.blocking > 0 && (
                <span className="font-medium text-rose-700"> · {plural(data.blocking, "question")} must be answered before the job can be finished</span>
              )}
            </>
          )}
          <span className="text-slate-400"> · {help}</span>
        </p>

        {/* Who answers, as tabs (open count, must-answer in red), with the search and the filter on the same bar */}
        <Tabs
          className="mt-3"
          label="Who answers"
          value={audience}
          onChange={(id) => { setAudience(id); setOpenKey(null); }}
          items={AUDIENCES.map(({ id, label }) => ({ id, label, count: data.counts[id].open, alert: data.counts[id].blocking }))}
          actions={
            <>
              <div className="relative w-full sm:w-56">
                <Search className="absolute left-2.5 top-2.5 h-3.5 w-3.5 text-slate-400" />
                <Input value={search} onChange={(e) => setSearch(e.target.value)} placeholder="Search the questions"
                       className="h-8 border-slate-200 bg-white pl-8 text-xs" />
              </div>
              <div className="flex items-center gap-1 rounded-lg border border-slate-200 bg-white p-0.5 text-[11px] font-semibold">
                {(["open", "answered", "all"] as const).map((v) => (
                  <button key={v} type="button" onClick={() => setShow(v)}
                          className={cn("rounded-md px-2.5 py-1 transition-colors", show === v ? "bg-teal-50 text-teal-800" : "text-slate-500 hover:bg-teal-50/60 hover:text-teal-800")}>
                    {v === "open" ? `Open (${forAudience.length - answered})` : v === "answered" ? `Answered (${answered})` : "All"}
                  </button>
                ))}
              </div>
            </>
          }
        />
      </Card>

      <div className="overflow-hidden rounded-xl border border-slate-200 bg-white">
        {shown.length === 0 ? (
          <p className="px-4 py-6 text-center text-xs text-slate-500">
            {search ? "No questions match the search." : show === "answered" ? "Nothing answered yet." : "No open queries here."}
          </p>
        ) : (
          page.paginatedItems.map((u, i) => {
            const first = u.kind === "one" ? u.q : u.items[0];
            const topic = topicOf(first);
            const prev = page.paginatedItems[i - 1];
            const newTopic = i === 0 || topicOf(prev.kind === "one" ? prev.q : prev.items[0]) !== topic;
            const Icon = topic.icon;
            return (
              <div key={u.kind === "one" ? u.q.key : u.key}>
                {newTopic && (
                  <div className="flex items-center gap-2 border-t border-slate-200 bg-slate-50 px-4 py-2">
                    <Icon className="h-3.5 w-3.5 text-slate-500" />
                    <span className="text-xs font-semibold text-slate-700">{topic.label}</span>
                    <span className="text-[11px] text-slate-400">{topicCounts[topic.id]}</span>
                  </div>
                )}
                {u.kind === "one" ? (
                  <QueryRow q={u.q} expanded={openKey === u.q.key} onToggle={() => setOpenKey(openKey === u.q.key ? null : u.q.key)}
                            saving={saving === u.q.key} onSave={save} onGoTo={onGoTo} />
                ) : (
                  <QueryGroup head={u.head} items={u.items} open={openKey === u.key}
                              onToggle={() => setOpenKey(openKey === u.key ? null : u.key)}>
                    {u.items.map((q) => (
                      <QueryRow key={q.key} q={q} expanded={openKey === q.key} onToggle={() => setOpenKey(openKey === q.key ? null : q.key)}
                                saving={saving === q.key} onSave={save} onGoTo={onGoTo} />
                    ))}
                  </QueryGroup>
                )}
              </div>
            );
          })
        )}
        {shown.length > 0 && (
          <Pagination
            currentPage={page.currentPage}
            pageSize={page.pageSize}
            totalPages={page.totalPages}
            totalItems={page.totalItems}
            startIndex={page.startIndex}
            endIndex={page.endIndex}
            pageRange={page.pageRange}
            canPrevPage={page.canPrevPage}
            canNextPage={page.canNextPage}
            onPageChange={page.setPage}
            onPageSizeChange={page.setPageSize}
            onPrevPage={page.prevPage}
            onNextPage={page.nextPage}
            onFirstPage={page.firstPage}
            onLastPage={page.lastPage}
            pageSizeOptions={[20, 50, 100]}
            itemLabel="questions"
          />
        )}
      </div>
    </div>
  );
}

export function QueryRow({
  q,
  expanded,
  onToggle,
  saving,
  onSave,
  onGoTo,
}: {
  q: JobQuery;
  expanded: boolean;
  onToggle: () => void;
  saving: boolean;
  onSave: (update: QueryUpdate, done?: string) => Promise<void>;
  onGoTo: (tab: GoTo) => void;
}) {
  const [answer, setAnswer] = useState(q.answer);
  const [lines, setLines] = useState<Record<string, string>>({});
  const [prevAnswer, setPrevAnswer] = useState(q.answer);
  if (q.answer !== prevAnswer) {
    setPrevAnswer(q.answer);
    setAnswer(q.answer);
  }

  const grouped = q.source === "books";
  const linesLeft = q.items.filter((i) => !i.answered).length;
  const changedLines = Object.fromEntries(
    Object.entries(lines).filter(([k, v]) => v.trim() !== (q.items.find((i) => i.key === k)?.answer || ""))
  );

  return (
    <div className="border-t border-slate-100 first:border-t-0">
      <button onClick={onToggle} className="flex w-full items-start gap-3 px-4 py-3 text-left transition-colors hover:bg-teal-50/40">
        {expanded ? (
          <ChevronDown className="mt-0.5 h-4 w-4 shrink-0 text-slate-400" />
        ) : (
          <ChevronRight className="mt-0.5 h-4 w-4 shrink-0 text-slate-400" />
        )}
        <div className="min-w-0 flex-1">
          <p className={cn("text-[13px] font-medium", isOpen(q) ? "text-slate-900" : "text-slate-500")}>{q.title}</p>
          {!expanded && (q.detail || q.items[0]?.text) && (
            <p className="mt-0.5 line-clamp-2 text-xs leading-relaxed text-slate-600">
              {q.items.length === 1 && q.source === "books" ? q.items[0].text : q.detail || q.items[0]?.text}
            </p>
          )}
          <div className="mt-1 flex flex-wrap items-center gap-1.5 text-[11px] text-slate-500">
            {q.blocking && isOpen(q) && (
              <span className="inline-flex items-center gap-1 font-semibold text-rose-700">
                <span className="h-1.5 w-1.5 rounded-full bg-rose-500" /> Must answer
              </span>
            )}
            {!isOpen(q) && <StatusChip tone="success" icon={Check}>{q.answer ? "Answered" : "Done"}</StatusChip>}
            <span>From {SOURCE[q.source]}</span>
            {grouped && q.items.length > 1 && (
              <>
                <span aria-hidden="true">·</span>
                <span>{linesLeft ? `${linesLeft} of ${q.items.length} lines to answer` : "every line answered"}</span>
              </>
            )}
          </div>
        </div>
        {Math.abs(q.amount) >= 0.005 && (
          <span className="shrink-0 text-[13px] font-semibold tabular-nums text-slate-700">{formatCurrency(q.amount)}</span>
        )}
      </button>

      {expanded && (
        <div className="space-y-3 bg-slate-50/50 px-4 pb-4 pl-11">
          {q.detail && !(grouped && q.items.length === 1) && (
            <p className="whitespace-pre-line text-xs leading-relaxed text-slate-700">{q.detail}</p>
          )}

          {/* A bank query: each line answered on its own (the same answer as on the Books tab) */}
          {grouped ? (
            <div className="overflow-hidden rounded-lg border border-slate-200 bg-white text-xs">
              {q.items.map((i) => {
                const draft = lines[i.key] ?? i.answer;
                return (
                  <div key={i.key} className="space-y-1.5 border-t border-slate-100 px-3 py-2.5 first:border-t-0">
                    <p className="text-slate-800">{i.text}</p>
                    <div className="flex items-center gap-2">
                      <input
                        value={draft}
                        onChange={(e) => setLines((d) => ({ ...d, [i.key]: e.target.value }))}
                        placeholder="The client's answer"
                        className="h-7 flex-1 rounded-md border border-slate-200 px-2 text-[11px] focus:outline-none focus:ring-2 focus:ring-teal-200"
                      />
                      {i.answered && draft === i.answer && (
                        <span className="flex items-center gap-1 text-[11px] text-emerald-700">
                          <Check className="h-3.5 w-3.5" /> Answered
                        </span>
                      )}
                    </div>
                  </div>
                );
              })}
            </div>
          ) : (
            <textarea
              value={answer}
              onChange={(e) => setAnswer(e.target.value)}
              rows={2}
              placeholder={q.audience === "CLIENT" ? "The client's answer" : "Your note or decision"}
              className="w-full rounded-md border border-slate-200 bg-white px-2 py-1.5 text-xs focus:outline-none focus:ring-2 focus:ring-teal-200"
            />
          )}

          <div className="flex flex-wrap items-center gap-2">
            {saving && <Loader2 className="h-4 w-4 animate-spin text-slate-400" />}
            {grouped && (
              <Button
                size="sm"
                variant="outline"
                className="h-7 text-[11px]"
                disabled={saving || !Object.keys(changedLines).length}
                onClick={() => onSave({ key: q.key, item_answers: changedLines }, "Answers saved").then(() => setLines({}))}
              >
                Save answers
              </Button>
            )}
            {/* One button: the answer (if any) saved and the query done; a review point is cleared on its tab too */}
            {isOpen(q) ? (
              <Button size="sm" variant="primary" className="h-7 text-[11px]" disabled={saving}
                      onClick={() => onSave({ key: q.key, status: "CLEARED", ...(grouped ? {} : { answer }) },
                                            q.source === "review" ? "Done, and cleared on the Review tab" : "Done")}>
                <Check className="mr-1 h-3 w-3" /> Done
              </Button>
            ) : (
              <>
                {!grouped && answer.trim() !== q.answer.trim() && (
                  <Button size="sm" variant="primary" className="h-7 text-[11px]" disabled={saving}
                          onClick={() => onSave({ key: q.key, answer }, "Answer saved")}>
                    Save answer
                  </Button>
                )}
                <Button size="sm" variant="outline" className="h-7 text-[11px]" disabled={saving}
                        onClick={() => onSave({ key: q.key, status: "OPEN" }, "Open again")}>
                  <RotateCcw className="mr-1 h-3 w-3" /> Undo
                </Button>
              </>
            )}
            <label className="flex items-center gap-1 text-[11px] text-slate-500">
              For
              <CustomSelect size="sm" value={q.audience} disabled={saving}
                            onChange={(v) => onSave({ key: q.key, audience: v as QueryAudience }, "Moved")}
                            options={AUDIENCES.map((a) => ({ value: a.id, label: a.label }))} />
            </label>
            {q.go_to && (
              <Button size="sm" variant="ghost" className="ml-auto h-7 text-[11px]" onClick={() => onGoTo(q.go_to as GoTo)}>
                {/* A review point's working and steps are on its card, not repeated here */}
                {q.source === "review" ? "Open the point" : `Open in ${SOURCE[q.source]}`} <ArrowRight className="ml-1 h-3 w-3" />
              </Button>
            )}
          </div>
        </div>
      )}
    </div>
  );
}


/** Queries of one kind (a bank statement for each of 9 accounts) as one row: the kind, how many, the must-answer
 *  mark once, and the text they share; opened, each query as its own row. */
function QueryGroup({ head, items, open, onToggle, children }: {
  head: string; items: JobQuery[]; open: boolean; onToggle: () => void; children: React.ReactNode;
}) {
  const left = items.filter(isOpen).length;
  const must = items.filter((q) => q.blocking && isOpen(q)).length;
  const shared = (items[0].detail || "").split(/(?<=\.)\s/)[0];
  return (
    <div className="border-t border-slate-100 first:border-t-0">
      <button type="button" onClick={onToggle} className="flex w-full items-start gap-3 px-4 py-3 text-left transition-colors hover:bg-teal-50/40">
        {open ? <ChevronDown className="mt-0.5 h-4 w-4 shrink-0 text-slate-400" /> : <ChevronRight className="mt-0.5 h-4 w-4 shrink-0 text-slate-400" />}
        <div className="min-w-0 flex-1">
          <p className="text-[13px] font-medium text-slate-900">
            {head}: {items.length} {items.length === 1 ? "item" : "items"}
            {left < items.length && <span className="font-normal text-slate-500"> · {left} open</span>}
          </p>
          {shared && <p className="mt-0.5 line-clamp-2 text-xs leading-relaxed text-slate-600">{shared}</p>}
          {must > 0 && (
            <p className="mt-1 inline-flex items-center gap-1.5 text-[11px] font-semibold text-rose-700">
              <span className="h-1.5 w-1.5 rounded-full bg-rose-500" /> {must} must be answered
            </p>
          )}
        </div>
      </button>
      {open && <div className="border-t border-slate-100 bg-slate-50/40 pl-6">{children}</div>}
    </div>
  );
}


/** The client email's document requests: one line per kind of document naming each account it is for ('The bank
 *  statements ... Accounts: Monzo (4800); Tide (4803)'), not the same sentence once per account with no name. */
function documentLines(queries: JobQuery[]): string[] {
  const opening = (q: JobQuery) => q.detail.split("\n")[0];
  const firstSentence = (q: JobQuery) => (opening(q).match(/^.*?[.!?](\s|$)/)?.[0] || opening(q)).trim();
  const head = (q: JobQuery) => (q.title.includes(":") ? q.title.split(":")[0].trim() : q.title);
  const what = (q: JobQuery) => (q.title.includes(":") ? q.title.slice(q.title.indexOf(":") + 1).trim() : "");
  const groups = new Map<string, JobQuery[]>();
  for (const q of queries) groups.set(head(q), [...(groups.get(head(q)) || []), q]);
  return Array.from(groups.values()).map((qs) => {
    const names = qs.map(what).filter(Boolean);
    if (!names.length) return firstSentence(qs[0]);
    return `${firstSentence(qs[0])} ${names.length === 1 ? "For" : "Accounts"}: ${names.join("; ")}.`;
  });
}
