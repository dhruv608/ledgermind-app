"use client";

import { useMemo, useState } from "react";
import { AuditFinding, ProposedJournal } from "@/types/engagement";
import { BookOpen, Clock, Check, ChevronDown, Plus, Trash2, Pencil, ListChecks, Search } from "lucide-react";
import { Input } from "@/components/ui/input";
import { areaOfJournal } from "@/lib/areas";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { StatusChip } from "@/components/ui/status-chip";
import { EmptyState } from "@/components/common/EmptyState";
import { cn } from "@/lib/utils";
import { toast } from "@/lib/notify";
import { api } from "@/lib/api";
import { formatCurrency } from "@/lib/formatters";
import { ManualJournalModal } from "@/components/review/journals/ManualJournalModal";
import { EditFoundAdjustmentModal, foundAdjustment } from "@/components/review/journals/EditFoundAdjustmentModal";
import { text } from "@/lib/ui";

interface JournalPostingsTableProps {
  engagementId: string;
  journals: ProposedJournal[];
  onJournalsUpdated: () => void;
  /** Review points, to show which one proposed a journal. */
  findings?: AuditFinding[];
}

const SECTIONS = [
  { status: "PROPOSED", title: "To decide" },
  { status: "APPROVED", title: "Approved" },
  { status: "REJECTED", title: "Rejected" },
];

/** "3000 - Wages and Salaries" -> "Wages and Salaries" (the code has its own column). */
const withoutCode = (name: string | null | undefined, code: string) => (name || "").replace(new RegExp(`^0*${Number(code)}\\s*[-–:]\\s*`), "");

/** A journal's debit and credit lines. */
function JournalLines({ journal: j }: { journal: ProposedJournal }) {
  const lines =
    j.lines && j.lines.length > 0
      ? j.lines.map((l) => ({
          key: String(l.line_no),
          code: String(l.account_code).padStart(4, "0"),
          name: l.narrative || l.account_name,
          debit: l.debit,
          credit: l.credit,
        }))
      : [
          { key: "dr", code: String(j.debit_code), name: j.debit_name, debit: j.amount, credit: 0 },
          { key: "cr", code: String(j.credit_code), name: j.credit_name, debit: 0, credit: j.amount },
        ];
  return (
    <div className="overflow-x-auto border-t border-slate-100 bg-slate-50/50">
      <table className="w-full text-[11px]">
        <thead className="text-[11px] uppercase tracking-wide text-slate-400">
          <tr>
            <th className="w-16 px-4 py-1.5 text-left font-semibold">Code</th>
            <th className="px-2 py-1.5 text-left font-semibold">Account</th>
            <th className="w-28 px-2 py-1.5 text-right font-semibold">Debit</th>
            <th className="w-28 px-4 py-1.5 text-right font-semibold">Credit</th>
          </tr>
        </thead>
        <tbody className="text-slate-700">
          {lines.map((l) => (
            <tr key={l.key} className="border-t border-slate-100">
              <td className="px-4 py-1.5 font-mono">{l.code}</td>
              <td className="px-2 py-1.5">{withoutCode(l.name, l.code)}</td>
              <td className="whitespace-nowrap px-2 py-1.5 text-right font-mono">{l.debit ? formatCurrency(l.debit) : ""}</td>
              <td className="whitespace-nowrap px-4 py-1.5 text-right font-mono">{l.credit ? formatCurrency(l.credit) : ""}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

export function JournalPostingsTable({
  engagementId,
  journals,
  onJournalsUpdated,
  findings = [],
}: JournalPostingsTableProps) {
  const [actingId, setActingId] = useState<number | null>(null);
  const [isNewOpen, setIsNewOpen] = useState(false);
  const [editing, setEditing] = useState<ProposedJournal | null>(null);
  // An accrual or prepayment the app proposed, its amount being changed
  const [changingFound, setChangingFound] = useState<ProposedJournal | null>(null);
  const [openIds, setOpenIds] = useState<Set<number>>(new Set());
  const toggleOpen = (id: number) =>
    setOpenIds((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  const pointOf = (j: ProposedJournal) => (j.finding_id ? findings.find((f) => f.id === j.finding_id) : undefined);

  // Which journals show: one area (VAT, payroll, fixed assets ...) or all, and a search on the text, ref and codes
  const [areaKey, setAreaKey] = useState("all");
  const [search, setSearch] = useState("");
  const findingsById = useMemo(() => new Map(findings.map((f) => [f.id, f])), [findings]);
  const areaOf = (j: ProposedJournal) => areaOfJournal(j, findingsById);
  const areas = useMemo(() => {
    const by = new Map<string, { key: string; label: string; n: number }>();
    for (const j of journals || []) {
      const a = areaOf(j);
      by.set(a.key, { key: a.key, label: a.label, n: (by.get(a.key)?.n || 0) + 1 });
    }
    return Array.from(by.values()).sort((a, b) => b.n - a.n);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [journals, findingsById]);
  const shownJournals = (journals || []).filter((j) => (areaKey === "all" || areaOf(j).key === areaKey) && (!search.trim()
    || `${j.journal_ref} ${j.description} ${j.debit_code} ${j.credit_code} ${j.debit_name} ${j.credit_name}`.toLowerCase().includes(search.trim().toLowerCase())));

  const newJournalButton = (
    <Button variant="primary" size="sm" onClick={() => setIsNewOpen(true)}>
      <Plus className="mr-1 h-3.5 w-3.5" /> New journal
    </Button>
  );

  const modal = (
    <ManualJournalModal
      isOpen={isNewOpen || Boolean(editing)}
      engagementId={engagementId}
      journal={editing}
      onClose={() => {
        setIsNewOpen(false);
        setEditing(null);
      }}
      onSaved={onJournalsUpdated}
    />
  );
  const foundModal = (
    <EditFoundAdjustmentModal journal={changingFound} onClose={() => setChangingFound(null)} onSaved={onJournalsUpdated} />
  );

  const handleDelete = async (j: ProposedJournal) => {
    setActingId(j.id);
    try {
      await api.deleteJournal(j.id);
      toast.success(`Journal ${j.journal_ref} deleted`);
      onJournalsUpdated();
    } catch (err: any) {
      toast.error("Delete failed", { description: err.message });
    } finally {
      setActingId(null);
    }
  };

  const handleAction = async (id: number, action: "APPROVE" | "REJECT") => {
    setActingId(id);
    try {
      await api.actOnJournal(id, action);
      toast.success(action === "APPROVE" ? "Journal approved" : "Journal rejected", {
        description: action === "APPROVE"
          ? "It will be posted to B2-Journals and the ETB the next time the workbook is generated."
          : "It is left out of the working papers.",
      });
      onJournalsUpdated();
    } catch (err: any) {
      toast.error("Not updated", {
        description: err.message || "Could not update journal status.",
      });
    } finally {
      setActingId(null);
    }
  };

  const stageLabel = (stage: string) =>
    ({
      STAGE_1_ACCOUNTING: "from the accounts review",
      STAGE_2_VAT: "from the VAT review",
      STAGE_3_CT600: "from the corporation tax",
      MANUAL: "entered by the accountant",
    })[stage] || stage;

  if (!journals || journals.length === 0) {
    return (
      <>
        <EmptyState
          icon={BookOpen}
          art="start"
          title="No journals yet"
          description="Journals proposed by the review appear here, and you can enter your own."
          action={{ label: "New journal", onClick: () => setIsNewOpen(true), icon: Plus, variant: "primary" }}
        />
        {modal}
      </>
    );
  }

  const approvedCount = journals.filter((j) => j.status === "APPROVED").length;
  const proposedCount = journals.filter((j) => j.status === "PROPOSED").length;

  return (
    <div className="space-y-4">
      <Card className="flex flex-wrap items-center justify-between gap-3 px-4 py-3">
        {/* The top bar names the screen: only the help line here */}
        <p className={cn("min-w-0", text.meta)}>Approved ones go to B2-Journals and the ETB when the workbook is built; rejected ones are left out.</p>
        <div className="flex flex-wrap items-center gap-1.5">
          <StatusChip tone={proposedCount ? "warning" : "neutral"} icon={Clock}>{proposedCount} to decide</StatusChip>
          <StatusChip tone="success" icon={Check}>{approvedCount} approved</StatusChip>
          {newJournalButton}
        </div>
      </Card>

      {(areas.length > 1 || journals.length > 6) && (
        <div className="flex flex-wrap items-center gap-2">
          {areas.length > 1 && (
            <div className="flex flex-wrap gap-1 rounded-lg border border-slate-200 bg-white p-0.5 text-[11px] font-medium">
              {[{ key: "all", label: "All areas", n: journals.length }, ...areas].map((a) => (
                <button key={a.key} type="button" onClick={() => setAreaKey(a.key)}
                        className={cn("rounded-md px-2.5 py-1 transition-colors",
                                      areaKey === a.key ? "bg-teal-50 text-teal-800" : "text-slate-600 hover:bg-teal-50/60 hover:text-teal-800")}>
                  {a.label} <span className="tabular-nums text-slate-400">{a.n}</span>
                </button>
              ))}
            </div>
          )}
          <div className="relative ml-auto w-full sm:w-56">
            <Search className="absolute left-2.5 top-2.5 h-3.5 w-3.5 text-slate-400" />
            <Input value={search} onChange={(e) => setSearch(e.target.value)} placeholder="Search journals or codes"
                   className="h-8 border-slate-200 bg-white pl-8 text-xs" />
          </div>
        </div>
      )}
      {shownJournals.length === 0 && <p className="px-1 text-xs text-slate-500">No journals match.</p>}

      {SECTIONS.map(({ status, title }) => {
        const list = shownJournals.filter((j) => j.status === status);
        if (!list.length) return null;
        return (
          <section key={status} className="space-y-2">
            <h3 className="flex items-baseline justify-between px-1 text-[11px] font-semibold uppercase tracking-wide text-slate-500">
              <span>{title} <span className="font-normal text-slate-400">{list.length}</span></span>
              <span className="font-mono normal-case tracking-normal text-slate-500">{formatCurrency(list.reduce((s, j) => s + Number(j.amount || 0), 0))}</span>
            </h3>
            <Card className="divide-y divide-slate-100 overflow-hidden">
              {list.map((j) => {
                const toDecide = j.status === "PROPOSED";
                const isOpen = toDecide || openIds.has(j.id);
                return (
                  <div key={j.id} className={cn(j.status === "REJECTED" && "opacity-60")}>
                    <div
                      onClick={toDecide ? undefined : () => toggleOpen(j.id)}
                      className={cn("flex items-start justify-between gap-3 px-4 py-2.5", !toDecide && "cursor-pointer transition-colors hover:bg-teal-50/40")}
                    >
                      <div className="flex min-w-0 flex-1 items-start gap-2">
                        {!toDecide && (
                          <ChevronDown className={cn("mt-0.5 h-4 w-4 shrink-0 text-slate-400 transition", isOpen && "rotate-180")} />
                        )}
                        <div className="min-w-0">
                          <p className="text-[13px] font-medium text-slate-900">{j.description}</p>
                          <p className="mt-0.5 text-[11px] text-slate-500">
                            <span className="font-mono text-slate-400">{j.journal_ref}</span> · {stageLabel(j.stage)}
                          </p>
                        </div>
                      </div>
                      <span className="shrink-0 font-mono text-sm font-semibold tabular-nums text-slate-900">{formatCurrency(Number(j.amount))}</span>
                    </div>
                    {isOpen && <JournalLines journal={j} />}
                    {toDecide && (
                      <div className="flex flex-wrap items-center justify-between gap-2 border-t border-slate-100 px-4 py-2">
                        <p className="flex min-w-0 items-center gap-1 text-[11px] text-slate-500">
                          {pointOf(j) && <><ListChecks className="h-3 w-3 shrink-0" /><span className="truncate">Why: {pointOf(j)!.finding_title}</span></>}
                        </p>
                        <div className="flex shrink-0 items-center gap-1.5">
                          {j.source === "MANUAL" && (
                            <button type="button" disabled={actingId === j.id} onClick={() => setEditing(j)}
                                    className="rounded p-1.5 text-slate-400 transition hover:bg-teal-50 hover:text-teal-800 disabled:opacity-50"
                                    title="Change this journal" aria-label="Change this journal">
                              <Pencil className="h-3.5 w-3.5" />
                            </button>
                          )}
                          {j.source !== "MANUAL" && foundAdjustment(j) && (
                            <button type="button" disabled={actingId === j.id} onClick={() => setChangingFound(j)}
                                    className="rounded p-1.5 text-slate-400 transition hover:bg-teal-50 hover:text-teal-800 disabled:opacity-50"
                                    title="Change the amount" aria-label="Change the amount">
                              <Pencil className="h-3.5 w-3.5" />
                            </button>
                          )}
                          {j.source === "MANUAL" && (
                            <button type="button" disabled={actingId === j.id} onClick={() => handleDelete(j)}
                                    className="rounded p-1.5 text-slate-400 transition hover:bg-rose-50 hover:text-rose-600 disabled:opacity-50"
                                    title="Delete this journal" aria-label="Delete this journal">
                              <Trash2 className="h-3.5 w-3.5" />
                            </button>
                          )}
                          <Button variant="outline" size="sm" disabled={actingId === j.id} onClick={() => handleAction(j.id, "REJECT")} className="h-7 px-2.5 text-[11px]">
                            Reject
                          </Button>
                          <Button size="sm" disabled={actingId === j.id} onClick={() => handleAction(j.id, "APPROVE")} className="h-7 bg-emerald-600 px-2.5 text-[11px] hover:bg-emerald-700">
                            <Check className="mr-1 h-3 w-3" /> Approve
                          </Button>
                        </div>
                      </div>
                    )}
                  </div>
                );
              })}
            </Card>
          </section>
        );
      })}
      {modal}
      {foundModal}
    </div>
  );
}
