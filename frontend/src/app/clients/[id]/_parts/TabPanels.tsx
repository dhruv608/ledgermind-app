// The open section of the client page: the panel for the chosen tab or working paper area.
import { useEffect } from "react";
import type { Dispatch, SetStateAction } from "react";
import { Tabs } from "@/components/ui/tabs";
import { WorkpapersList } from "@/components/review/area/WorkpapersList";
import { jobChanged } from "@/lib/jobEvents";
import type { CheckRun } from "@/lib/api";
import type { EngagementData, LatestWorkpaper, TBRecord } from "@/types/engagement";
import { ClientSetupPanel } from "@/components/setup/ClientSetupPanel";
import { DataCheckPanel } from "@/components/setup/DataCheckPanel";
import { QueriesPanel } from "@/components/queries/QueriesPanel";
import { MappingTable } from "@/components/mapping/MappingTable";
import { EtbTable } from "@/components/mapping/EtbTable";
import { ScrutinyPanel } from "@/components/mapping/ScrutinyPanel";
import { SupplementaryDocsPanel } from "@/components/upload/SupplementaryDocsPanel";
import { SequentialReviewPipeline } from "@/components/review/points/SequentialReviewPipeline";
import { JournalPostingsTable } from "@/components/review/journals/JournalPostingsTable";
import { WorkbookPanel } from "@/components/workbook/WorkbookPanel";
import { BooksPanel } from "@/components/books/BooksPanel";
import { ReconciliationsPanel } from "@/components/control-accounts/ReconciliationsPanel";
import { GENERAL, areaByKey, areaKeyOfCode } from "@/lib/areas";
import { SkeletonRows } from "@/components/common/SkeletonRows";
import { AreaPanel } from "@/components/review/area/AreaPanel";
import { CodingReview } from "@/components/review/coding/CodingReview";
import { CODING, TabId } from "./tabs";
import type { JobData } from "./useJobData";
import type { JobStatus } from "./jobStatus";
import type { useJobActions } from "./useJobActions";

export interface TabPanelsProps {
  id: string;
  tab: TabId;
  engagement: EngagementData;
  job: JobData;
  view: JobStatus;
  actions: ReturnType<typeof useJobActions>;
  checks: CheckRun | null;
  startChecks: () => void;
  goToTab: (next: TabId, force?: boolean) => void;
  openArea: (key: string, evidence?: boolean) => void;
  activeArea: string | null;
  shownArea: ReturnType<typeof areaByKey> | undefined;
  areaStart: { tab: "evidence"; n: number } | null;
  setSetupDirty: Dispatch<SetStateAction<boolean>>;
  accountsView: "client" | "etb" | "scrutiny";
  setAccountsView: (value: "client" | "etb" | "scrutiny") => void;
  scrutinyCode: string | null;
  setScrutinyCode: Dispatch<SetStateAction<string | null>>;
  setLedgerAccount: Dispatch<SetStateAction<TBRecord | null>>;
  setViewing: Dispatch<SetStateAction<{ wp: LatestWorkpaper; sheet?: string } | null>>;
  setIsViewerOpen: Dispatch<SetStateAction<boolean>>;
}

export function TabPanels({
  id, tab, engagement, job, view, actions, checks, startChecks, goToTab, openArea, activeArea, shownArea, areaStart,
  setSetupDirty, accountsView, setAccountsView, scrutinyCode, setScrutinyCode, setLedgerAccount, setViewing,
  setIsViewerOpen,
}: TabPanelsProps) {
  const {
    profile, setProfile, auditFindings, secondaryLoaded, recsLoaded, journals, supplementaryDocs, supplementaryData,
    reanalysis, setReanalysis, mispostings, setMispostings, areaSignoffs, setAreaSignoffs, workpaper, status,
    recCounts, setRecCounts, setDataCounts, queriesLoaded, loadQueries, loadEngagement,
  } = job;
  const { mappingsToReview, downloadUrl, reviewRan, reviewStale, workbookStale, byArea, tiesOf, workAreas, workAreaStatus } = view;
  const { isGenerating, handleClearFinding, handleClearMany, handleGenerateWorkpaper } = actions;

  return (
    <>
      {tab === "data" && (
        <DataCheckPanel
          engagementId={engagement.engagement_id}
          clientName={engagement.client_name}
          yearEnd={engagement.period_end_date}
          onLoaded={(d) => setDataCounts({ stops: d.stops, warnings: d.warnings })}
          onChanged={() => jobChanged(id, { big: true })}
          onGoTo={(t) => goToTab(t)}
        />
      )}
      {/* The job's other years: last year's final working paper and next year's ledger (the area documents are on each
          area's Evidence tab) */}
      {tab === "data" && (
        <SupplementaryDocsPanel
          engagementId={engagement.engagement_id}
          documents={supplementaryDocs}
          data={supplementaryData}
          onRefresh={() => jobChanged(id, { big: true })}
          only={["LAST_YEAR_WP", "NEXT_YEAR_LEDGER"]}
        />
      )}

      {tab === "queries" && (
        <QueriesPanel
          engagementId={engagement.engagement_id}
          clientName={engagement.client_name}
          yearEnd={engagement.period_end_date}
          load={loadQueries}
          onLoaded={queriesLoaded}
          onGoTo={(t) => {
            // A ledger line asked about opens on the GL scrutiny view
            if (t === "accounts") setAccountsView("scrutiny");
            goToTab(t);
          }}
        />
      )}

      {tab === "setup" && (
        <ClientSetupPanel engagementId={id} initialProfile={profile} onProfileUpdated={(updated) => {
            setProfile(updated);
            jobChanged(id, { big: true });
          }} onDirtyChange={setSetupDirty} />
      )}

      {tab === "books" && (
        <BooksPanel engagementId={id} onGoToSetup={() => goToTab("setup")} onTrialBalanceMade={() => { loadEngagement(); jobChanged(id, { big: true }); }} />
      )}

      {tab === "accounts" && (
        <div className="space-y-3">
          <Tabs label="Trial balance views" value={accountsView} onChange={setAccountsView}
                items={[{ id: "client", label: "Client accounts" }, { id: "etb", label: "ETB (after journals)" }, { id: "scrutiny", label: "GL scrutiny" }]} />
          {accountsView === "scrutiny" ? (
            <ScrutinyPanel
              key={scrutinyCode || "first"}
              engagementId={engagement.engagement_id}
              initialKey={scrutinyCode}
              onChanged={() => jobChanged(id)}
              onQueriesChanged={() => jobChanged(id)}
            />
          ) : accountsView === "etb" ? (
            <EtbTable
              engagementId={engagement.engagement_id}
              refreshKey={`${status?.data_changed_at}|${journals.filter((j) => j.status === "APPROVED").length}`}
            />
          ) : (
            <MappingTable records={engagement.tb_records} engagementId={engagement.engagement_id} onChanged={() => jobChanged(id)} />
          )}
        </div>
      )}

      {/* A link to the VAT & payroll data step lands on the VAT area's Evidence tab */}
      {tab === "inputs" && <RedirectOnce onGo={() => goToTab("inputs")} />}

      {tab === "review" && (
        <SequentialReviewPipeline
          engagementId={engagement.engagement_id}
          findings={auditFindings}
          journals={journals}
          onReviewCompleted={() => jobChanged(id)}
          checks={checks}
          onRunChecks={startChecks}
          onClearFinding={handleClearFinding}
          onClearMany={handleClearMany}
          accountNames={engagement.tb_records.map((r) => r.raw_account_name)}
          onOpenAccount={(name) => setLedgerAccount(engagement.tb_records.find((r) => r.raw_account_name === name) || null)}
          onGoToSetup={() => goToTab("setup")}
          clientName={engagement.client_name}
          yearEnd={engagement.period_end_date}
        />
      )}

      {tab === "area" && CODING.includes(activeArea || "") && (
        <CodingReview
          key={activeArea}
          engagementId={engagement.engagement_id}
          start={activeArea === "mispostings" ? "mispostings" : "reanalysis"}
          reanalysis={reanalysis}
          mispostings={mispostings}
          onReanalysis={(r) => setReanalysis(r.summary)}
          onMispostings={(m) => setMispostings(m.summary)}
          onChanged={() => jobChanged(id)}
        />
      )}

      {tab === "papers" && (
        <WorkpapersList
          papers={workAreas}
          status={workAreaStatus}
          rows={recCounts?.rows || []}
          signoffs={areaSignoffs}
          onOpen={openArea}
        />
      )}

      {tab === "area" && !CODING.includes(activeArea || "") && (shownArea && byArea.has(shownArea.key) ? (
        <AreaPanel
          engagementId={engagement.engagement_id}
          area={shownArea}
          findings={byArea.get(shownArea.key)!.findings}
          journals={byArea.get(shownArea.key)!.journals}
          allFindings={auditFindings}
          reviewRan={reviewRan}
          reviewStale={Boolean(status?.review_run_at) && reviewStale}
          onClearFinding={handleClearFinding}
          onJournalsUpdated={() => jobChanged(id)}
          onGoToReview={() => goToTab("review")}
          ties={tiesOf(shownArea.key)}
          allRows={recCounts?.rows || []}
          yearEnd={engagement.period_end_date}
          payCosts={shownArea.key === "payroll" ? (recCounts?.rows || []).filter((r) => r.area === "Payroll" && r.section === "Profit and loss checks") : []}
          onGoToBalanceSheet={() => goToTab("recs")}
          onGoToInputs={() => goToTab("inputs")}
          startTab={areaStart}
          onCisSaved={() => jobChanged(id)}
          onGoToData={() => goToTab("data")}
          accounts={engagement.tb_records.map((r) => ({ name: r.raw_account_name, code: r.std_code ?? null, net: Number(r.net_amount || 0) }))}
          onOpenAccount={(name) => setLedgerAccount(engagement.tb_records.find((r) => r.raw_account_name === name) || null)}
          onOpenScrutiny={(code) => {
            setScrutinyCode(String(code));
            setAccountsView("scrutiny");
            goToTab("accounts");
          }}
          onRecsUpdated={setRecCounts}
          loadQueries={loadQueries}
          onQueriesLoaded={queriesLoaded}
          onGoTo={(t) => {
            if (t === "accounts") setAccountsView("scrutiny");
            goToTab(t);
          }}
          onGoToQueries={() => goToTab("queries")}
          areaSignoffs={areaSignoffs[shownArea.key]}
          onAreaSignoffs={setAreaSignoffs}
        />
      ) : !secondaryLoaded || !recsLoaded ? (
        <div className="rounded-xl border border-slate-200 bg-white p-4"><SkeletonRows rows={6} /></div>
      ) : (
        <p className="rounded-xl border border-slate-200 bg-white px-4 py-3 text-xs text-slate-500">
          Nothing in this area yet: run the review, then pick an area from the checklist.
        </p>
      ))}

      {tab === "journals" && (
        <JournalPostingsTable engagementId={engagement.engagement_id} journals={journals} findings={auditFindings} onJournalsUpdated={() => jobChanged(id)} />
      )}

      {tab === "recs" && (
        <ReconciliationsPanel
          engagementId={engagement.engagement_id}
          onOpenLedger={(code) => setLedgerAccount(engagement.tb_records.find((r) => r.std_code === code) || null)}
          onOpenScrutiny={(code) => {
            setScrutinyCode(String(code));
            setAccountsView("scrutiny");
            goToTab("accounts");
          }}
          onGoTo={(t) => goToTab(t)}
          onSaved={() => jobChanged(id)}
          onLoaded={setRecCounts}
          areaFor={(codes) => codes.map(areaKeyOfCode).find((k) => k !== GENERAL.key && byArea.has(k)) ?? null}
          onOpenArea={openArea}
        />
      )}

      {tab === "workbook" && (
        <WorkbookPanel
          engagementId={engagement.engagement_id}
          workpaper={workpaper}
          downloadUrl={downloadUrl}
          mappingsToReview={mappingsToReview}
          stale={workbookStale}
          buildBlockers={status?.build_blockers || []}
          onGoTo={(t) => goToTab(t)}
          isGenerating={isGenerating}
          onGenerate={() => handleGenerateWorkpaper()}
          onView={(wp, sheet) => {
            setViewing({ wp, sheet });
            setIsViewerOpen(true);
          }}
          onReviewAccounts={() => goToTab("accounts")}
          findings={auditFindings}
          journals={journals}
          recs={recCounts}
          reviewRan={reviewRan}
          onOpenTab={(t) => goToTab(t)}
          onOpenArea={openArea}
        />
      )}
    </>
  );
}

/** Runs its action once after it shows (redirects an outdated address to where its content lives). */
function RedirectOnce({ onGo }: { onGo: () => void }) {
  // eslint-disable-next-line react-hooks/exhaustive-deps -- runs once on mount by design: onGo is a new function each render
  useEffect(() => { onGo(); }, []);
  return null;
}
