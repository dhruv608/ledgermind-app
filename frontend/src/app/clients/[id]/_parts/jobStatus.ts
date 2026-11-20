// Where the job stands, worked out from its loaded data: each tab and checklist step's state, the working paper
// areas and their states, the 'n of n done' rows and the one next thing to do. The status rules are lib/jobState's.
import type { LucideIcon } from "lucide-react";
import {
  BookOpen,
  ClipboardCheck,
  FileSpreadsheet,
  ListChecks,
  MessageSquareMore,
  NotebookPen,
  Receipt,
  Scale,
  SlidersHorizontal,
  Table2,
} from "lucide-react";
import { areaState, codingState, isToDo, queriesState, reviewState } from "@/lib/jobState";
import { resolveBackendUrl } from "@/lib/api";
import type { CheckRun, JobQueries, Mispostings, Reanalysis, Reconciliations } from "@/lib/api";
import { plural } from "@/lib/formatters";
import type {
  AuditFinding,
  ClientProfile,
  EngagementData,
  EngagementStatus,
  LatestWorkpaper,
  ProposedJournal,
} from "@/types/engagement";
import type { WorkbookState } from "@/components/clients/EngagementHeader";
import { peekClient, rememberClient, type ClientPeek } from "@/lib/clientPeek";
import { AREAS, areaKeyOfCode, areaOfJournal, areaOfPoint, setAccountCodes } from "@/lib/areas";
import { isInfoPoint, withJournalIds } from "@/components/review/points/pointInfo";
import { CHECKLIST, TAB_IDS, TabId, needsReview } from "./tabs";

export type TabItem = { id: TabId; label: string; icon: LucideIcon; badge?: string | number; attention?: boolean; done?: boolean };
export type AreaTone = "stop" | "needs" | "fix" | "wait" | "done";
// The one next thing to do on this job: the first thing not finished, in the order the work is done; how many
// more are waiting after it. Open queries that do not block the job never stop the workbook being built (a client
// can take weeks to answer): they show beside the build step instead
export type Next = { text: string; tab?: TabId; area?: string; goLabel?: string; build?: boolean; tone: "todo" | "stop" | "done" };

export interface JobStatusInput {
  id: string;
  engagement: EngagementData;
  profile: ClientProfile | null;
  auditFindings: AuditFinding[];
  journals: ProposedJournal[];
  status: EngagementStatus | null;
  workpaper: LatestWorkpaper | null;
  dataCounts: { stops: number; warnings: number } | null;
  queryCounts: Pick<JobQueries, "open" | "blocking" | "counts"> | null;
  recCounts: Reconciliations | null;
  scrutinyFlagged: number;
  reanalysis: Reanalysis["summary"] | null;
  mispostings: Mispostings["summary"] | null;
  checks: CheckRun | null;
  secondaryLoaded: boolean;
  recsLoaded: boolean;
  peek: ClientPeek | null;
}

/** Works out the job's statuses during render (it also keeps the account codes and the area list for next time,
 *  as the page always did while rendering). */
export function jobStatus({
  id, engagement, profile, auditFindings, journals, status, workpaper, dataCounts, queryCounts, recCounts,
  scrutinyFlagged, reanalysis, mispostings, checks, secondaryLoaded, recsLoaded, peek,
}: JobStatusInput) {
  const mappingsToReview = status ? status.mappings_to_review : engagement.tb_records.filter(needsReview).length;
  // Open points to look at (the tax computation CT-01 is shown on its own, and points for information only are not
  // counted)
  const setupStarted = (profile?.confirmed_fields || []).length > 0;
  const journalIds = withJournalIds(journals);
  const toAct = (f: AuditFinding) => f.status === "OPEN" && f.procedure_ref !== "CT-01" && !isInfoPoint(f, journalIds.has(f.id));
  const openPoints = auditFindings.filter(toAct).length;
  const pendingJournals = journals.filter((j) => j.status === "PROPOSED").length;
  const workbookState: WorkbookState = workpaper ? (workpaper.is_draft ? "draft" : "final") : "none";
  const setupDone = (profile?.confirmed_fields || []).length > 0;
  const downloadUrl = workpaper ? resolveBackendUrl(workpaper.download_url) : null;

  // Each step: a number to do (amber), or a tick once it is done
  const blockers = status?.build_blockers || [];
  const reviewRan = Boolean(status?.review_run_at) && !status?.review_stale;
  const hasAccounts = engagement.tb_records.length > 0;
  const workbookFresh = workbookState === "final" && !(status?.workbook_stale);
  const tabs: TabItem[] = [
    // First: is everything the working papers need in the client's files (a red count stops the workbook)
    { id: "data", label: "Files", icon: ClipboardCheck, badge: dataCounts?.stops || undefined,
      attention: Boolean(dataCounts?.stops), done: Boolean(dataCounts) && dataCounts?.stops === 0 && dataCounts?.warnings === 0 },
    // One list of everything to ask: the client, the accountant, the preparer (a red count stops the job)
    { id: "queries", label: "Queries", icon: MessageSquareMore, badge: queryCounts?.blocking || queryCounts?.open || undefined,
      attention: Boolean(queryCounts?.blocking), done: Boolean(queryCounts) && queryCounts?.open === 0 },
    { id: "setup", label: "Client details", icon: SlidersHorizontal, badge: setupDone ? undefined : "to do", attention: !setupDone,
      done: setupDone && !blockers.some((b) => b.startsWith("Setup")) },
    // Only for a client with no accounting software: the books prepared from the bank statement and Dext
    ...(engagement?.source_system === "BANK_DEXT" ? [{ id: "books" as TabId, label: "Books", icon: BookOpen, done: hasAccounts }] : []),
    { id: "accounts", label: "Accounts", icon: Table2, badge: mappingsToReview || undefined, attention: mappingsToReview > 0,
      done: hasAccounts && mappingsToReview === 0 && scrutinyFlagged === 0 },
    { id: "inputs", label: "VAT & payroll data", icon: Receipt },
    { id: "review", label: "Review points", icon: ListChecks, badge: openPoints || undefined, attention: openPoints > 0,
      done: reviewRan && openPoints === 0 },
    { id: "journals", label: "Journals", icon: NotebookPen, badge: pendingJournals || undefined, attention: pendingJournals > 0,
      done: reviewRan && pendingJournals === 0 },
    { id: "recs", label: "Balance sheet check", icon: Scale, badge: recCounts?.differences || undefined,
      attention: Boolean(recCounts?.differences),
      done: Boolean(recCounts) && recCounts?.differences === 0 && recCounts?.needs_input === 0 },
    { id: "workbook", label: "Finish and download", icon: FileSpreadsheet,
      badge: workpaper && status?.workbook_stale ? "refresh" : undefined, attention: Boolean(workpaper && status?.workbook_stale),
      done: workbookFresh },
  ];
  const reviewStale = Boolean(status?.review_stale);
  const workbookStale = Boolean(status?.workbook_stale && workpaper);

  const tabById = Object.fromEntries(tabs.map((t) => [t.id, t]));

  // Each checklist item's state in words, from the same counts the tabs show: what is waiting on the accountant
  // (needs you), a fix the app has ready to approve, waiting on someone else, or done
  const areaStatus: Partial<Record<TabId, { text: string; tone: AreaTone }>> = {
    // Counted from the Files page's own items: to fix stops the workbook, to check leaves it a draft
    data: dataCounts?.stops ? { text: `${dataCounts.stops} to fix`, tone: "stop" }
      : dataCounts?.warnings ? { text: `${dataCounts.warnings} to check`, tone: "needs" }
      : dataCounts ? { text: "Agrees", tone: "done" } : undefined,
    setup: !setupDone ? { text: "Needs you", tone: "needs" }
      : blockers.some((b) => b.startsWith("Setup")) ? { text: "Answers missing", tone: "needs" } : { text: "Done", tone: "done" },
    books: engagement.source_system === "BANK_DEXT" ? (hasAccounts ? { text: "Done", tone: "done" } : { text: "Needs you", tone: "needs" }) : undefined,
    // The mappings and the GL scrutiny's flagged lines both live on this step: done only when both are cleared
    accounts: !hasAccounts ? undefined
      : mappingsToReview > 0 ? { text: `${mappingsToReview} to check`, tone: "needs" }
      : scrutinyFlagged ? { text: `${scrutinyFlagged} flagged to read`, tone: "needs" } : { text: "Done", tone: "done" },
    review: reviewState(checks?.status === "RUNNING", status?.review_run_at, reviewStale, openPoints),
    journals: pendingJournals > 0 ? { text: `${pendingJournals} fix${pendingJournals === 1 ? "" : "es"} ready`, tone: "fix" }
      : reviewRan ? { text: "Done", tone: "done" } : undefined,
    recs: !recCounts ? undefined
      : recCounts.differences ? { text: `${recCounts.differences} differ`, tone: "needs" }
      : recCounts.needs_input ? { text: `${recCounts.needs_input} to agree`, tone: "wait" } : { text: "Agrees", tone: "done" },
    queries: queriesState(queryCounts),
    workbook: !workpaper ? { text: "Not built", tone: "wait" }
      : workbookStale ? { text: "Build again", tone: "needs" }
      : workpaper.is_draft ? { text: "Draft", tone: "wait" } : { text: "Done", tone: "done" },
  };
  const shownAreas = CHECKLIST.flatMap((g) => g.ids).filter((tid) => tabById[tid] && areaStatus[tid]);

  // The year-end's areas (bank, net wages, VAT ...): each review point by its reference, each journal by the point
  // that proposed it, and where each area stands
  const findingsById = new Map(auditFindings.map((f) => [f.id, f]));
  const byArea = new Map<string, { findings: AuditFinding[]; journals: ProposedJournal[] }>();
  const slot = (key: string) => byArea.get(key) || byArea.set(key, { findings: [], journals: [] }).get(key)!;
  // The client's account names with their codes first: a point naming an account without its code finds its area
  setAccountCodes(engagement.tb_records.map((r) => ({ name: r.raw_account_name, code: r.std_code ?? null })));
  auditFindings.forEach((f) => slot(areaOfPoint(f).key).findings.push(f));
  journals.forEach((j) => slot(areaOfJournal(j, findingsById).key).journals.push(j));
  // An area with a balance to tie out shows even with no point (its balances agree, or wait for a document)
  (recCounts?.rows || []).forEach((r) => new Set(r.codes.map(areaKeyOfCode)).forEach((k) => slot(k)));
  // An area's balances (the area page gets the same rows as its ties)
  const tiesOf = (key: string) => (recCounts?.rows || []).filter((r) => r.codes.some((c) => areaKeyOfCode(c) === key));
  // The working papers: no "General checks" page: its points are in their own areas, and the few
  // about the whole job are on the Review points tab as "Whole job"
  const workAreas = AREAS.filter((a) => byArea.has(a.key));
  // The points and the balances both in: until then the list is only part of the job's areas
  const areasLoaded = secondaryLoaded && recsLoaded;
  // Kept for the next visit's loading view, once the list is whole (its checklist then shows these areas at once)
  if (areasLoaded && workAreas.length && peekClient(id)?.areas?.join("|") !== workAreas.map((a) => a.label).join("|")) {
    rememberClient(id, { name: engagement.client_name, areas: workAreas.map((a) => a.label) });
  }
  // The sidebar while the figures load: the areas known now and last visit's, so the list does not grow in jumps
  const remembered = peek?.areas ?? [];
  const sidebarAreas = areasLoaded || !remembered.length ? workAreas
    : AREAS.filter((a) => byArea.has(a.key) || remembered.includes(a.label));
  const workAreaStatus = (key: string): { text: string; tone: AreaTone } => {
    const d = byArea.get(key);
    if (!d) return { text: "…", tone: "wait" };
    // The same words and order as the area page's header (lib/jobState)
    return areaState(d.findings, d.journals, tiesOf(key), reviewRan).short;
  };
  // 'n of n done': every row the sidebar shows (its steps, the Coding review and every working paper area)
  const allRows = [
    ...shownAreas.map((tid) => areaStatus[tid]!.tone),
    ...(hasAccounts && codingState(reanalysis, mispostings) ? [codingState(reanalysis, mispostings)!.tone] : []),
    ...workAreas.map((a) => workAreaStatus(a.key).tone),
  ];
  const countOf = (tones: AreaTone[]) => allRows.filter((t) => tones.includes(t)).length;

  // Built from the same statuses the sidebar shows, in its order (lib/jobState): whatever the sidebar marks as to do
  // is here too, so 'Next' can never say all done while a step still shows something to do
  const sentence: Partial<Record<TabId, string>> = {
    data: dataCounts?.stops ? `${plural(dataCounts.stops, "item")} in the Files must be fixed first.` : undefined,
    setup: !setupStarted ? "Answer a few questions about the client: the checks run once they are saved." : undefined,
    books: "Make the trial balance from the bank statements on the Books tab.",
    accounts: mappingsToReview > 0 ? `Check ${plural(mappingsToReview, "account mapping")} before the review.` : undefined,
    queries: queryCounts?.blocking
      ? `${plural(queryCounts.blocking, "blocking query", "blocking queries")} to send or answer: the job can't be finished without ${queryCounts.blocking === 1 ? "it" : "them"}.`
      : undefined,
    review: openPoints > 0 && !reviewStale ? `Look at ${plural(openPoints, "open review point")}.` : undefined,
    journals: pendingJournals > 0 ? `Approve or reject ${plural(pendingJournals, "proposed journal")}.` : undefined,
    recs: recCounts?.differences ? `Clear ${plural(recCounts.differences, "balance sheet difference")}.` : undefined,
  };
  const codingNow = codingState(reanalysis, mispostings);
  const todo: Next[] = [
    ...(["data", "setup", "books", "accounts"] as TabId[]).filter((t) => tabById[t]).map((t) => ({ t, st: areaStatus[t] })),
    ...(hasAccounts ? [{ t: "coding" as const, st: codingNow }] : []),
    ...workAreas.map((a) => ({ t: a.key, st: workAreaStatus(a.key), label: a.label })),
    ...(["queries", "review", "journals", "recs"] as TabId[]).filter((t) => tabById[t]).map((t) => ({ t, st: areaStatus[t] })),
  ]
    // The points are counted on their areas: the Review points step adds only what is not about one area (not run,
    // out of date)
    .filter((x) => !(x.t === "review" && openPoints > 0 && !reviewStale && checks?.status !== "RUNNING"))
    .filter((x) => isToDo(x.st)).map((x): Next => {
    const isTab = (TAB_IDS as string[]).includes(x.t) && x.t !== "coding";
    const label = "label" in x && x.label ? x.label : x.t === "coding" ? "Coding review" : tabById[x.t as TabId]?.label || x.t;
    return {
      text: (isTab && sentence[x.t as TabId]) || `${label}: ${x.st!.text}.`,
      ...(isTab ? { tab: x.t as TabId } : { area: x.t, goLabel: label }),
      tone: x.st!.tone === "stop" ? "stop" : "todo",
    };
  });
  const openQueries = queryCounts?.open && !queryCounts?.blocking
    ? ` (${plural(queryCounts.open, "client query", "client queries")} still open)` : "";
  const next: Next = todo[0]
    ?? (!workpaper || workbookStale || workpaper.is_draft
      ? {
          text: (workpaper ? "Build the workbook again to include the latest changes." : "Everything is ready: build the workbook.") + openQueries,
          tab: "workbook",
          build: true,
          tone: "todo",
        }
      : { text: "All done: the workbook is up to date." + openQueries, tone: "done" });
  if (todo.length > 1) next.text += ` · ${todo.length - 1} more to do after this`;

  return {
    mappingsToReview, setupStarted, workbookState, downloadUrl, reviewRan, hasAccounts, reviewStale, workbookStale,
    tabById, areaStatus, byArea, tiesOf, workAreas, sidebarAreas, workAreaStatus, allRows, countOf, next,
  };
}

export type JobStatus = ReturnType<typeof jobStatus>;
