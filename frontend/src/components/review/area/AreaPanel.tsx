"use client";

import { useEffect, useState } from "react";
import { List, ListChecks, Plus } from "lucide-react";
import type { AuditFinding, ProposedJournal } from "@/types/engagement";
import type { AreaNote, AreaSignoff, JobQueries, PointSignoff, Reconciliation, Reconciliations } from "@/lib/api";
import type { Area } from "@/lib/areas";
import { JournalPostingsTable } from "@/components/review/journals/JournalPostingsTable";
import { OpeningBalancesTable } from "@/components/review/workpapers/OpeningBalancesTable";
import { AdjustmentsPanel } from "@/components/review/journals/AdjustmentsPanel";
import { ManualJournalModal } from "@/components/review/journals/ManualJournalModal";
import { PointCard, pointParts } from "@/components/review/points/PointCard";
import { AreaNotes } from "@/components/review/area/AreaNotes";
import { AreaEvidence } from "@/components/review/area/AreaEvidence";
import { LedgerViewsPanel } from "@/components/review/workpapers/LedgerViewsPanel";
import { AreaSignoffBar } from "@/components/review/area/AreaSignoffBar";
import { AreaQueries, inArea } from "@/components/review/area/AreaQueries";
import { isOpen, type GoTo } from "@/components/queries/QueriesPanel";
import { PayrollWorkpaper } from "@/components/review/workpapers/PayrollWorkpaper";
import { VatWorkpaper } from "@/components/review/workpapers/VatWorkpaper";
import { Fig, FigRow } from "@/components/review/area/WorkpaperParts";
import { BalancesWorkpaper, type BalanceGroup } from "@/components/review/workpapers/BalancesWorkpaper";
import { PAPERS, SPLITS, creditorGroups, currentAssetGroups, loanGroups, sectionsOf } from "@/components/review/workpapers/added/areaPapers";
import { FixedAssetSchedule } from "@/components/review/workpapers/FixedAssetSchedule";
import { AssetRegister } from "@/components/review/workpapers/AssetRegister";
import { EmptyState } from "@/components/common/EmptyState";
import { StockLinesPanel } from "@/components/review/workpapers/StockLinesPanel";
import { AddedPapers } from "@/components/review/workpapers/added/AddedPapers";
import { ScrutinySummary } from "@/components/mapping/scrutiny/ScrutinySummary";
import { ReservesMovement } from "@/components/review/workpapers/ReservesMovement";
import { TaxCalculation } from "@/components/review/workpapers/TaxCalculation";
import { BankWorkpaper } from "@/components/review/workpapers/BankWorkpaper";
import { VatReturnsPanel } from "@/components/setup/VatReturnsPanel";
import { CisHmrcPanel } from "@/components/control-accounts/CisHmrcPanel";
import { useJobStore, useNotes, useSignoffs } from "@/lib/queries/job";
import { AREA_EVIDENCE } from "@/lib/areas";
import { Button } from "@/components/ui/button";
import { api } from "@/lib/api";
import { Tabs } from "@/components/ui/tabs";
import { gap, text } from "@/lib/ui";
import { areaState } from "@/lib/jobState";
import { cn } from "@/lib/utils";
import { toast } from "@/lib/notify";
import { formatCurrency } from "@/lib/formatters";
import { isInfoPoint, withJournalIds } from "@/components/review/points/pointInfo";

interface AreaPanelProps {
  engagementId: string;
  area: Area;
  /** This area's review points and journals (already picked out by the page) */
  findings: AuditFinding[];
  journals: ProposedJournal[];
  /** Every review point of the job, so a journal can name the point that proposed it */
  allFindings: AuditFinding[];
  reviewRan: boolean;
  /** The review ran, but something changed since: its points are from the last run */
  reviewStale?: boolean;
  onClearFinding: (id: number, note?: string) => Promise<void> | void;
  onJournalsUpdated: () => void;
  onGoToReview: () => void;
  /** The area's balances against what they should be (the Balance sheet tab's control accounts) */
  ties?: Reconciliation[];
  /** Every balance on the balance sheet check: the Creditors summary lists every creditor, whatever its area */
  allRows?: Reconciliation[];
  /** Payroll: the pay costs against the payroll report (profit and loss checks, on no balance sheet code) */
  payCosts?: Reconciliation[];
  onGoToBalanceSheet?: () => void;
  /** Where the area's documents come in: the VAT & payroll tab, the Data check tab */
  onGoToInputs?: () => void;
  onGoToData?: () => void;
  /** The client's own accounts in the books (name, firm code, balance), to open each one's ledger lines */
  accounts?: { name: string; code: number | null; net: number }[];
  /** The job's year end (dd/mm/yyyy or yyyy-mm-dd), for an added loan schedule's split */
  yearEnd?: string;
  onOpenAccount?: (name: string) => void;
  /** Opens GL scrutiny on this firm code (every ledger line on the code, whatever the client calls the account) */
  onOpenScrutiny?: (code: number) => void;
  /** The control accounts worked out again (a typed line of the VAT proof) */
  onRecsUpdated?: (next: Reconciliations) => void;
  /** The job's queries, shared with the Queries tab (asked for once), and where they open */
  loadQueries?: () => Promise<JobQueries>;
  onQueriesLoaded?: (q: JobQueries) => void;
  onGoTo?: (tab: GoTo) => void;
  onGoToQueries?: () => void;
  /** The whole area's sign-off (prepared, reviewed, approved), kept by the page for the Areas list */
  areaSignoffs?: AreaSignoff[];
  onAreaSignoffs?: (next: Record<string, AreaSignoff[]>) => void;
  /** Open on this tab when a link asks for it (n changes with each ask) */
  startTab?: { tab: "evidence"; n: number } | null;
  /** After the CIS figures from HMRC are saved (Payroll's Evidence tab) */
  onCisSaved?: () => void;
}

type AreaTab = "recon" | "recon2" | "register" | "pl" | "points" | "lines" | "evidence" | "queries" | "notes";


const signed = (n: number) => formatCurrency(n);
const money = (n: number) => formatCurrency(Math.abs(n));

const EVIDENCE = AREA_EVIDENCE;

/** One control account area on one page: the header with the books against the document and where it stands,
 * then tabs for the reconciliation, the points, the transactions and the evidence, and an adjustment posted as a
 * journal from anywhere on the page. */
export function AreaPanel({
  engagementId, area, findings, journals, allFindings, reviewRan, reviewStale = false, onClearFinding, onJournalsUpdated, onGoToReview,
  ties = [], allRows = [], payCosts = [], yearEnd, onGoToBalanceSheet, onGoToInputs, onGoToData, accounts = [], onOpenAccount, onOpenScrutiny, onRecsUpdated,
  loadQueries, onQueriesLoaded, onGoTo, onGoToQueries, areaSignoffs, onAreaSignoffs, startTab, onCisSaved,
}: AreaPanelProps) {
  const [showCleared, setShowCleared] = useState(false);
  const [deciding, setDeciding] = useState(false);
  const [adjusting, setAdjusting] = useState(false);
  // Sign-offs and notes come from the job's shared store: asked for once, shared with the other screens
  const store = useJobStore(engagementId);
  const signoffs: Record<string, PointSignoff[]> = useSignoffs(engagementId).data ?? {};
  const setSignoffs = store.setSignoffs;
  const notesQuery = useNotes(engagementId);
  const notes: AreaNote[] | null = notesQuery.data ?? (notesQuery.isError ? [] : null);
  const setNotes = store.setNotes;
  const findingIds = findings.map((f) => f.id).join();
  // The account's queries (Raise query and Notes on each point)
  const [queries, setQueries] = useState<JobQueries | null>(null);
  const [raiseFor, setRaiseFor] = useState<AuditFinding | null>(null);
  const [noteFor, setNoteFor] = useState<AuditFinding | null>(null);
  useEffect(() => {
    (loadQueries ? loadQueries() : api.getQueries(engagementId)).then(setQueries).catch(() => undefined);
    // eslint-disable-next-line react-hooks/exhaustive-deps -- runs per job and set of points: loadQueries is recreated each render
  }, [engagementId, findingIds]);
  // A query or note added from the assistant: read again
  useEffect(() => {
    const again = () => {
      api.getQueries(engagementId).then(setQueries).catch(() => undefined);
      store.refresh("notes");
    };
    window.addEventListener("assistant-action", again);
    return () => window.removeEventListener("assistant-action", again);
    // eslint-disable-next-line react-hooks/exhaustive-deps -- one listener per job: store is a new object each render, its refresh depends only on the job
  }, [engagementId]);
  const queriesChanged = (next: JobQueries) => {
    setQueries(next);
    onQueriesLoaded?.(next);
  };
  // Points that only tell the accountant something are shown on their own, not as points to look at
  const journalIds = withJournalIds(journals);
  const openAll = findings.filter((f) => f.status === "OPEN" && f.procedure_ref !== "CT-01");
  const info = openAll.filter((f) => isInfoPoint(f, journalIds.has(f.id)));
  const open = openAll.filter((f) => !isInfoPoint(f, journalIds.has(f.id)));
  const computation = findings.filter((f) => f.procedure_ref === "CT-01");
  const cleared = findings.filter((f) => f.status !== "OPEN" && f.procedure_ref !== "CT-01");
  const toDecide = journals.filter((j) => j.status === "PROPOSED").length;
  // A journal to decide sits on its point's card: counted once, with the point; only one whose point is not open adds
  const openIds = new Set(open.map((f) => f.id));
  const loneJournals = journals.filter((j) => j.status === "PROPOSED" && !(j.finding_id && openIds.has(j.finding_id))).length;
  const hasRecon = ties.length > 0 || ["opening", "accruals", "payroll", "vat", "stock"].includes(area.key);
  // The tab the accountant picked; until then the reconciliation when the area has one (its balances can arrive after
  // the page opens), else the points
  const [picked, setTab] = useState<AreaTab | null>(null);
  // A new start request (its n changes) opens its tab: set during render, as React does for state following a prop
  const [startN, setStartN] = useState<number | undefined>(undefined);
  if (startTab?.n !== startN) {
    setStartN(startTab?.n);
    if (startTab) setTab(startTab.tab);
  }
  // An account's paper is open on the summary tab (bank, VAT, payroll or a balance): its figures replace the area's
  const [paperOpen, setPaperOpen] = useState(false);
  // The working paper tabs: one summary, or an area's two papers (SPLITS), each shown when it holds a balance (accruals
  // and prepayments always, for their line-by-line schedules)
  const split = SPLITS[area.key];
  const splitHas = (i: number) => area.key === "accruals"
    || sectionsOf(area.key, ties, true).some((g) => split[i].sections.includes(g.title) && g.list.length > 0);
  const paperTabs: AreaTab[] = !hasRecon ? [] : !split ? ["recon"] : (["recon", "recon2"] as const).filter((_, i) => splitHas(i));
  const isPaper = (t: AreaTab) => t === "recon" || t === "recon2";
  const tab: AreaTab = picked && (!isPaper(picked) || paperTabs.includes(picked)) && (picked !== "lines" || ties.length > 0)
    ? picked : paperTabs[0] ?? "points";
  const splitAt = tab === "recon2" ? 1 : 0;

  // Where the area stands (Tied / Explained by proposed journals / Unexplained), else from its points
  // The same words and order as the sidebar (lib/jobState): Unexplained, Explained by proposed journals, Tied with
  // points open, To look at, Waiting for a document, Tied
  const headerTone: Record<string, string> = {
    stop: "bg-rose-100 text-rose-800", fix: "bg-sky-100 text-sky-800", needs: "bg-amber-50 text-amber-800",
    wait: "bg-slate-100 text-slate-700", done: "bg-emerald-50 text-emerald-700",
  };
  const long = areaState(findings, journals, ties, reviewRan).long;
  const state = long ? { text: long.text, tone: headerTone[long.tone] } : null;

  // The header's figures: the area's balances added up (the document's figure only when every balance has one)
  const books = ties.reduce((s, t) => s + t.books, 0);
  const expected = ties.length && ties.every((t) => t.other !== null) ? ties.reduce((s, t) => s + (t.other ?? 0), 0) : null;
  const lastYear = ties.length && ties.every((t) => t.last_year !== null) ? ties.reduce((s, t) => s + (t.last_year ?? 0), 0) : null;

  // An overdrawn directors' loan with reserves is one decision: the point offers the dividend or
  // the s455; choosing approves or rejects its journal, and the next check books the s455 when there is no dividend
  const decide = async (journalId: number, action: "APPROVE" | "REJECT") => {
    setDeciding(true);
    try {
      await api.actOnJournal(journalId, action);
      toast.success(action === "APPROVE" ? "Dividend declared" : "No dividend: the s455 is booked when the checks run again");
      onJournalsUpdated();
    } catch (e) {
      toast.error(e instanceof Error ? e.message : "Could not save the decision");
    } finally {
      setDeciding(false);
    }
  };

  // The Points tab's filters: every point, those to act on (no journal to decide, not a client question), client
  // questions, those with a proposed journal; in the review's order or the biggest amount first
  const [pointsShow, setPointsShow] = useState<"all" | "act" | "client" | "journal">("all");
  const [biggestFirst, setBiggestFirst] = useState(false);
  const hasJournal = (f: AuditFinding) => journals.some((j) => j.finding_id === f.id && j.status === "PROPOSED");
  const isClientQuery = (f: AuditFinding) => pointParts(f, hasJournal(f)).clientQuery;
  const pointKinds = {
    all: () => true,
    act: (f: AuditFinding) => !hasJournal(f) && !isClientQuery(f),
    client: isClientQuery,
    journal: hasJournal,
  };
  // Most serious first (as the Review points tab), or the biggest amount first
  const rank = (f: AuditFinding) => ["CRITICAL", "HIGH", "MEDIUM", "LOW"].indexOf((f.severity || "LOW").toUpperCase());
  const shownOpen = open.filter(pointKinds[pointsShow])
    .sort((a, b) => (biggestFirst ? Math.abs(Number(b.quantified_amount) || 0) - Math.abs(Number(a.quantified_amount) || 0) : rank(a) - rank(b)));

  // Each point as an Issue / Detail / Action card with its journal beside it and sign-off (PointCard)
  const point = (f: AuditFinding) => {
    const journal = journals.find((j) => j.finding_id === f.id);
    const choice = f.procedure_ref === "U-DIV-001" && f.status === "OPEN" && journal?.status === "PROPOSED" ? journal : undefined;
    return (
      <PointCard
        key={f.id}
        engagementId={engagementId}
        finding={f}
        journal={journal}
        signoffs={signoffs[String(f.id)]}
        onSignoffs={setSignoffs}
        onClear={(id, note) => onClearFinding(id, note)}
        onJournalsUpdated={onJournalsUpdated}
        onRaiseQuery={(p) => { setRaiseFor(p); setTab("queries"); }}
        queries={(queries?.queries || []).filter((q) => q.source === "raised" && q.finding_id === f.id).length}
        onNote={(p) => { setNoteFor(p); setTab("notes"); }}
        notes={(notes || []).filter((n) => n.finding_id === f.id).length}
        extra={choice ? (
          <>
            <Button size="sm" className="h-7 text-xs" disabled={deciding} onClick={() => decide(choice.id, "APPROVE")}>
              Declare dividend {money(Number(choice.amount))}
            </Button>
            <Button variant="outline" size="sm" className="h-7 text-xs" disabled={deciding} onClick={() => decide(choice.id, "REJECT")}>
              No dividend: charge s455
            </Button>
          </>
        ) : undefined}
      />
    );
  };

  const pointIds = new Set(findings.map((f) => f.id));
  const areaQueries = (queries?.queries || []).filter((q) => inArea(q, area, pointIds) && isOpen(q)).length;
  const tabs: { id: AreaTab; label: string; count?: number }[] = [
    ...paperTabs.map((id) => ({ id, label: split ? split[id === "recon2" ? 1 : 0].label
      : "Summary" })),          // the area's name is in the top bar and the paper's own title: the tab just says Summary
    ...(area.key === "expenses" ? [{ id: "pl" as const, label: "P&L analysis" }] : []),
    ...(area.key === "fixed" ? [{ id: "register" as const, label: "Asset register" }] : []),
    { id: "points", label: "Points", count: open.length + loneJournals },
    ...(ties.length ? [{ id: "lines" as const, label: "Transactions" }] : []),
    { id: "evidence", label: "Evidence" },
    { id: "queries", label: "Queries", count: areaQueries },
    { id: "notes", label: "Notes", count: (notes || []).filter((n) => n.area === area.key).length },
  ];
  const evidence = EVIDENCE[area.key];
  // Fixed assets: one row per asset class (its cost and depreciation together, as the FRS 102 fixed assets note), against
  // the asset register; it opens the class's year like any other balance
  const classRows: Reconciliation[] = area.key !== "fixed" ? [] : Array.from(
    ties.filter((t) => t.key.startsWith("far:")).reduce((by, t) => {
      const [, name] = t.key.split(":");
      return by.set(name, [...(by.get(name) || []), t]);
    }, new Map<string, Reconciliation[]>()).entries()).map(([name, parts]) => {
      const add = (pick: (r: Reconciliation) => number | null) => parts.every((r) => pick(r) !== null) ? parts.reduce((s, r) => s + (pick(r) ?? 0), 0) : null;
      const status: Reconciliation["status"] = parts.some((r) => r.status === "DIFFERENCE") ? "DIFFERENCE"
        : parts.every((r) => r.status === "MATCHED") ? "MATCHED" : "NEEDS_INPUT";
      return { ...parts[0], key: `class:${name}`, account: `${name} (cost and depreciation)`, books: add((r) => r.books) ?? 0,
               last_year: add((r) => r.last_year), other: add((r) => r.other), difference: add((r) => r.difference), status,
               compared_with: "Fixed asset register", codes: parts.flatMap((r) => r.codes), note: "" };
    });
  const restTies = area.key === "fixed" ? ties.filter((t) => !t.key.startsWith("far:")) : ties;
  // Each area lists only its own balances; every balance together is on the Balance sheet check
  const balanceGroups: BalanceGroup[] = area.key === "purchases" ? creditorGroups(ties)
    : area.key === "sales" ? currentAssetGroups(ties)
    : area.key === "loans" ? loanGroups(restTies) : [
    ...(classRows.length ? [{ title: "Fixed assets by class", list: classRows }] : []),
    ...sectionsOf(area.key, restTies, Boolean(split))
      // An area of two papers: this tab's sections only
      .filter((g) => !split || split[splitAt].sections.includes(g.title))
      .map((g) => ({ title: g.title, listing: g.listing as "AR" | "AP" | undefined, list: g.list })),
  ];
  const shownGroups = balanceGroups.filter((g) => g.list.length > 0);
  // The accounts a Detailed paper can be for: the trial balance's, by code
  const accountOptions = Array.from(new Map(accounts.filter((a) => a.code !== null)
    .map((a) => [a.code as number, { code: a.code as number, name: a.name }])).values()).sort((x, y) => x.code - y.code);
  const paper = split ? split[splitAt] : PAPERS[area.key] ?? { title: `${area.label}: summary`, intro: "Each balance this year against last year and the document it is agreed to. View opens each one's working paper." };

  return (
    <div className={gap.sections}>
      {/* Header: the area's books against the document, where it stands, and an adjustment from anywhere */}
      <div className="rounded-xl border border-slate-200 bg-white p-4 shadow-2xs">
        <div className="flex flex-wrap items-start justify-between gap-3">
          {/* Where the area stands (its name is in the top bar; its points are counted on the Points tab) */}
          <div className="flex min-w-0 flex-wrap items-center gap-2">
            {state && <span className={cn("rounded-full px-2.5 py-0.5 text-[11px] font-bold", state.tone)}>{state.text}</span>}
            {!reviewRan && (
              <p className={text.meta}>
                {reviewStale || findings.length ? "Something changed since LM last checked this area: the figures here update once LM has checked it again."
                  : "The review has not run yet: this area fills in once it has."}
              </p>
            )}
          </div>
          <div className="flex flex-wrap items-center gap-2">
            {reviewRan && onAreaSignoffs && (
              <AreaSignoffBar engagementId={engagementId} area={area.key} findings={findings}
                              signoffs={areaSignoffs} onChange={onAreaSignoffs} />
            )}
            <Button size="sm" className="h-8 text-xs" onClick={() => setAdjusting(true)}>
              <Plus className="mr-1 h-3.5 w-3.5" /> Add adjustment
            </Button>
            <Button variant="outline" size="sm" className="h-8 text-xs" onClick={onGoToReview}>
              <ListChecks className="mr-1.5 h-3.5 w-3.5" /> All points
            </Button>
          </div>
        </div>
        {/* The area's figures; an account's open paper shows its own instead (not the same figures twice) */}
        {ties.length > 0 && !(isPaper(tab) && paperOpen) && (
          <FigRow className="mt-3">
            <Fig label="Books" value={signed(books)} />
            <Fig label="Per the documents" value={expected === null ? "Not in yet" : signed(expected)} />
            <Fig label="Difference" value={expected === null ? "-" : Math.abs(books - expected) < 1 ? "Agrees" : signed(books - expected)}
                    tone={expected === null ? undefined : Math.abs(books - expected) >= 1 ? "text-rose-700" : "text-emerald-700"} />
            <Fig label="Last year" value={lastYear === null ? "-" : signed(lastYear)} />
          </FigRow>
        )}
      </div>

      {/* The page's tabs */}
      <Tabs label={`${area.label} sections`} items={tabs} value={tab} onChange={setTab} />

      {isPaper(tab) && (
        <div className="space-y-4">
          {area.key === "opening" && (
            <OpeningBalancesTable engagementId={engagementId} refreshKey={journals.map((j) => j.status).join()} />
          )}
          {/* Bank: the bank working paper (summary, then each account's detailed / ledger / reconciliation) */}
          {area.key === "bank" && restTies.length > 0 && (
            <BankWorkpaper engagementId={engagementId} rows={restTies} onRecsUpdated={onRecsUpdated} onAttach={() => setTab("evidence")} onOpenChange={setPaperOpen} />
          )}
          {/* Payroll: the wages working paper (summary, each payable's detailed / ledger / reconciliation) */}
          {area.key === "payroll" && (
            <PayrollWorkpaper engagementId={engagementId} ties={[...restTies, ...payCosts.filter((r) => !restTies.some((t) => t.key === r.key))]} version={journals.map((j) => j.status).join()}
                              onRecsUpdated={onRecsUpdated} onAttach={() => setTab("evidence")} onOpenChange={setPaperOpen} />
          )}
          {/* VAT: the VAT working paper (summary by return, the VAT account's detailed / ledger / reconciliation) */}
          {area.key === "vat" && (
            <VatWorkpaper engagementId={engagementId} ties={restTies} version={journals.map((j) => j.status).join()}
                          onRecsUpdated={onRecsUpdated} onAttach={() => setTab("evidence")} onTypeReturns={() => setTab("evidence")} onOpenChange={setPaperOpen} />
          )}
          {/* Every other area: the balance summary (sections such as trade and other), each balance's detailed / ledger /
             listing and reconciliation; fixed assets by class against the asset register */}
          {/* Fixed assets: the schedule by class (cost b/f to NBV) first, then each class against the register */}
          {area.key === "fixed" && <FixedAssetSchedule engagementId={engagementId} />}
          {/* Corporation tax: the tax calculation first */}
          {area.key === "tax" && <TaxCalculation engagementId={engagementId} />}
          {!["bank", "payroll", "vat"].includes(area.key) && shownGroups.length > 0 && (
            <BalancesWorkpaper key={`paper-${tab}`} engagementId={engagementId} title={paper.title} intro={paper.intro}
                               groups={shownGroups}
                               onRecsUpdated={onRecsUpdated} onAttach={() => setTab("evidence")} onOpenChange={setPaperOpen} />
          )}
          {/* The area's own schedule: the VAT proof, payroll by month (net wages, PAYE / NI, pension), last year's and
              this year's accruals line by line */}
          {/* Share capital and reserves: the reserves movement under the balances */}
          {area.key === "dla" && tab === "recon2" && <ReservesMovement engagementId={engagementId} />}
          {area.key === "accruals" && (
            <AdjustmentsPanel key={`lines-${tab}`} engagementId={engagementId} onSaved={onJournalsUpdated} kind={tab === "recon2" ? "ACCRUAL" : "PREPAYMENT"}
                              yearEnd={yearEnd?.includes("/") ? yearEnd.split("/").reverse().join("-") : yearEnd} />
          )}
          {/* Stock: the closing stock line by line, and who verified the count */}
          {area.key === "stock" && <StockLinesPanel engagementId={engagementId} onAttach={() => setTab("evidence")} />}
          {/* Papers the accountant adds (a new working paper or reconciliation) */}
          <AddedPapers engagementId={engagementId} area={area.key} accounts={accountOptions} onAttach={() => setTab("evidence")}
                       yearEnd={yearEnd?.includes("/") ? yearEnd.split("/").reverse().join("-") : yearEnd} />
        </div>
      )}

      {tab === "register" && <AssetRegister engagementId={engagementId} />}
      {/* Expense coding: the P&L analysis (code, particular, this year, last year) */}
      {tab === "pl" && (
        <div className="overflow-hidden rounded-xl border border-slate-200 bg-white shadow-2xs">
          <ScrutinySummary engagementId={engagementId} only="PL" onOpen={(code) => onOpenScrutiny?.(code)} />
        </div>
      )}

      {tab === "points" && (
        <div className="space-y-4">
          {computation.map((f) => (
            <ul key={f.id}>{point(f)}</ul>
          ))}
          {open.length > 0 && (
            <section>
              <div className="mb-2 flex flex-wrap items-center gap-2">
                <h3 className="mr-auto text-xs font-bold uppercase tracking-wide text-slate-400">Points to look at</h3>
                <div className="inline-flex rounded-lg border border-slate-200 bg-white p-0.5 text-[11px] font-medium">
                  {([["all", "All"], ["act", "To act on"], ["client", "Client questions"], ["journal", "With a journal"]] as const).map(([k, label]) => {
                    const n = open.filter(pointKinds[k]).length;
                    return (
                      <button key={k} type="button" onClick={() => setPointsShow(k)} disabled={k !== "all" && n === 0}
                              className={cn("rounded-md px-2.5 py-1 transition-colors disabled:opacity-40",
                                            pointsShow === k ? "bg-teal-50 text-teal-800" : "text-slate-600 hover:bg-teal-50/60 hover:text-teal-800")}>
                        {label} <span className="tabular-nums text-slate-400">{n}</span>
                      </button>
                    );
                  })}
                </div>
                <label className="flex cursor-pointer items-center gap-1.5 text-[11px] text-slate-600">
                  <input type="checkbox" checked={biggestFirst} onChange={() => setBiggestFirst(!biggestFirst)} className="h-3.5 w-3.5 accent-teal-700" />
                  Biggest first
                </label>
              </div>
              <ul className="space-y-2">{shownOpen.map(point)}</ul>
              {shownOpen.length === 0 && <p className="text-xs text-slate-500">No points of this kind.</p>}
            </section>
          )}
          {info.length > 0 && (
            <section>
              <h3 className="mb-2 text-xs font-bold uppercase tracking-wide text-slate-400">
                For information <span className="font-medium normal-case tracking-normal text-slate-400">(no answer needed)</span>
              </h3>
              <ul className="space-y-2">{info.map(point)}</ul>
            </section>
          )}
          {journals.length > 0 && (
            <section>
              <h3 className="mb-2 text-xs font-bold uppercase tracking-wide text-slate-400">All journals in this area</h3>
              <JournalPostingsTable engagementId={engagementId} journals={journals} findings={allFindings} onJournalsUpdated={onJournalsUpdated} />
            </section>
          )}
          {reviewRan && open.length === 0 && info.length === 0 && journals.length === 0 && computation.length === 0 && (
            <EmptyState art="done" title="No review points" description="The checks found nothing to fix in this area." />
          )}
          {cleared.length > 0 && (
            <section>
              <button type="button" className="text-xs font-semibold text-slate-500 hover:text-slate-800" onClick={() => setShowCleared(!showCleared)}>
                {showCleared ? "Hide" : "Show"} {cleared.length} cleared point{cleared.length === 1 ? "" : "s"}
              </button>
              {showCleared && <ul className="mt-2 space-y-2">{cleared.map(point)}</ul>}
            </section>
          )}
        </div>
      )}

      {tab === "lines" && (
        <div className="space-y-4">
        {/* The area's codes as uploaded, as they are now, and what moved where (ledger analysis views) */}
        <LedgerViewsPanel
          engagementId={engagementId}
          codes={Array.from(new Map(ties.flatMap((t) => t.codes.map((c) => [c, t.codes.length === 1 ? t.account : `Code ${c}`] as const))).entries())
            .map(([code, name]) => ({ code, name }))}
        />
        <div className="overflow-hidden rounded-xl border border-slate-200 bg-white shadow-2xs">
          {/* Every ledger line on the area's codes, in GL scrutiny; then each of the client's own accounts (several can
              share one firm code: VAT Control and VAT Suspense) */}
          {onOpenScrutiny && (
            <div className="flex flex-wrap items-center justify-between gap-2 border-b border-slate-100 bg-slate-50 px-4 py-2.5 text-xs">
              <span className="text-slate-600">All the lines on this area&apos;s accounts</span>
              <span className="flex flex-wrap gap-2">
                {Array.from(new Set(ties.flatMap((t) => t.codes))).map((code) => (
                  <Button key={code} size="sm" className="h-7 text-xs" onClick={() => onOpenScrutiny(code)}>
                    <List className="mr-1 h-3.5 w-3.5" /> Open {(ties.find((t) => t.codes.length === 1 && t.codes[0] === code)?.account
                      ?? accounts.find((a) => a.code === code)?.name ?? String(code)).replace(/^\d{3,5}\s*-\s*/, "")} in GL scrutiny
                  </Button>
                ))}
              </span>
            </div>
          )}
          <ul className="divide-y divide-slate-100">
            {ties.flatMap((t) => t.codes).flatMap((code) => accounts.filter((a) => a.code === code)).map((a) => (
              <li key={a.name} className="flex flex-wrap items-center justify-between gap-2 px-4 py-2.5 text-xs">
                <span className="min-w-0">
                  <span className="block font-medium text-slate-800">{a.name}</span>
                  <span className="text-[11px] text-slate-500">Code {a.code} · balance {signed(a.net)}</span>
                </span>
                <Button variant="outline" size="sm" className="h-7 text-xs" disabled={!onOpenAccount} onClick={() => onOpenAccount?.(a.name)}>
                  <List className="mr-1 h-3.5 w-3.5" /> See transactions
                </Button>
              </li>
            ))}
          </ul>
        </div>
        </div>
      )}

      {tab === "evidence" && (
        <div className="space-y-3">
          <AreaEvidence
            engagementId={engagementId}
            area={area}
            what={evidence ? evidence.what : "Documents that support this area"}
            reads={["vat", "payroll", "fixed", "loans"].includes(area.key)}
            onRead={onJournalsUpdated}
          />
          {evidence?.where === "recs" && onGoToBalanceSheet && (
            <p className="flex flex-wrap items-center justify-between gap-2 rounded-xl border border-slate-200 bg-white px-4 py-3 text-xs text-slate-600 shadow-2xs">
              Type each statement&apos;s balance at the year end on the Balance sheet check: the books are agreed to it.
              <Button variant="outline" size="sm" className="h-7 text-xs" onClick={onGoToBalanceSheet}>Balance sheet check</Button>
            </p>
          )}
          {/* The VAT returns: uploaded above, or typed box by box here */}
          {area.key === "vat" && <VatReturnsPanel engagementId={engagementId} periodEndDate={yearEnd || ""} onSaved={onJournalsUpdated} />}
          {/* CIS: what was filed with HMRC, beside the books (shown for a client with the CIS accounts) */}
          {area.key === "payroll" && <CisHmrcPanel engagementId={engagementId} onSaved={onCisSaved} />}
          {area.key === "loans" && (
            <p className="flex flex-wrap items-center justify-between gap-2 rounded-xl border border-slate-200 bg-white px-4 py-3 text-xs text-slate-600 shadow-2xs">
              The firm&apos;s loans register: one row per agreement. Download the template, fill in the client&apos;s loans, upload it above.
              <a href="/templates/loans-register-template.xlsx" download className="rounded-md border border-slate-200 px-2.5 py-1 font-medium text-teal-800 hover:bg-teal-50">Download template</a>
            </p>
          )}
        </div>
      )}

      {tab === "queries" && (
        <AreaQueries
          engagementId={engagementId}
          area={area}
          data={queries}
          onData={queriesChanged}
          raiseFor={raiseFor}
          onRaiseForUsed={() => setRaiseFor(null)}
          onGoTo={(t) => onGoTo?.(t)}
          onGoToQueries={onGoToQueries}
          pointIds={pointIds}
        />
      )}

      {tab === "notes" && (
        <AreaNotes
          engagementId={engagementId}
          area={area}
          notes={notes}
          onNotes={setNotes}
          findings={findings.filter((f) => f.procedure_ref !== "CT-01")}
          noteFor={noteFor}
          onNoteForUsed={() => setNoteFor(null)}
        />
      )}

      <ManualJournalModal
        isOpen={adjusting}
        engagementId={engagementId}
        onClose={() => setAdjusting(false)}
        onSaved={() => { setAdjusting(false); onJournalsUpdated(); }}
      />
    </div>
  );
}

