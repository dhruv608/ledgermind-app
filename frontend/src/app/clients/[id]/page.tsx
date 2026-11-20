"use client";

import { JobTopBar } from "@/components/clients/JobTopBar";
import { AddDocumentModal } from "@/components/clients/AddDocumentModal";
import { useState, useEffect, use } from "react";
import { useRouter } from "next/navigation";
import { jobChanged } from "@/lib/jobEvents";
import { UpdatingBar, UpdatingCover } from "@/components/clients/UpdatingCover";
import { AlertCircle } from "lucide-react";
import { resolveBackendUrl } from "@/lib/api";
import { LatestWorkpaper, TBRecord } from "@/types/engagement";
import { EngagementHeader } from "@/components/clients/EngagementHeader";
import { useRememberedState } from "@/hooks/useRememberedState";
import { ExcelViewerModal } from "@/components/workbook/ExcelViewerModal";
import { GLTransactionDrawer } from "@/components/mapping/GLTransactionDrawer";
import { ConfirmDialog } from "@/components/ui/confirm-dialog";
import { Button } from "@/components/ui/button";
import { WorkspaceLoading } from "@/components/clients/WorkspaceLoading";
import { peekClient, type ClientPeek } from "@/lib/clientPeek";
import { areaByKey } from "@/lib/areas";
import { ChecksPanel, STEP_AREA } from "@/components/clients/ChecksPanel";
import { ClientQuestions } from "@/components/setup/ClientQuestions";
import { CODING, REDONE, TabId, areaFromUrl } from "./_parts/tabs";
import { useJobData } from "./_parts/useJobData";
import { useJobActions } from "./_parts/useJobActions";
import { useChecksWatch } from "./_parts/useChecksWatch";
import { jobStatus } from "./_parts/jobStatus";
import { ChecklistSidebar } from "./_parts/ChecklistSidebar";
import { TabPanels } from "./_parts/TabPanels";

interface ClientPageProps {
  params: Promise<{ id: string }>;
}

export default function ClientEngagementPage({ params }: ClientPageProps) {
  const router = useRouter();
  const { id } = use(params);

  const [activeTab, setActiveTab] = useState<TabId | null>(null);
  const [activeArea, setActiveArea] = useState<string | null>(areaFromUrl);
  // The tab an area page opens on when a link asks for it (the VAT returns: the VAT area's Evidence tab)
  const [areaStart, setAreaStart] = useState<{ tab: "evidence"; n: number } | null>(null);
  const [addingDocument, setAddingDocument] = useState(false);

  // The workbook preview: whether it is open, and the workbook and sheet it shows (default: the latest, first sheet)
  const [isViewerOpen, setIsViewerOpen] = useState(false);
  const [viewing, setViewing] = useState<{ wp: LatestWorkpaper; sheet?: string } | null>(null);
  // Ledger lines of one account, opened from a review point
  const [ledgerAccount, setLedgerAccount] = useState<TBRecord | null>(null);

  // Unsaved changes on the Setup tab: ask before leaving it
  const [setupDirty, setSetupDirty] = useState(false);
  const [pendingTab, setPendingTab] = useState<TabId | null>(null);

  useEffect(() => {
    if (!setupDirty) return;
    const warn = (e: BeforeUnloadEvent) => e.preventDefault();
    window.addEventListener("beforeunload", warn);
    return () => window.removeEventListener("beforeunload", warn);
  }, [setupDirty]);

  // The Accounts tab: the client's accounts and their codes, or the ETB (per code, after the approved journals)
  const [accountsView, setAccountsView] = useRememberedState<"client" | "etb" | "scrutiny">("accounts.view", "client");
  // The workspace checklist on the left (wide screens): the accountant can hide it to give the tables the full width
  const [checklistOn, setChecklistOn] = useRememberedState<boolean>("workspace.checklist", true);
  // What is known of the client before it loads (name, Books step, areas): read after mounting, as the browser keeps it
  const [peek, setPeek] = useState<ClientPeek | null>(null);
  // eslint-disable-next-line react-hooks/set-state-in-effect -- browser storage is read after mounting (the server render has none)
  useEffect(() => setPeek(peekClient(id)), [id]);
  // The checklist opened over the page from the folded rail
  const [drawer, setDrawer] = useState(false);
  // The account GL scrutiny opens on when another tab sends you there
  const [scrutinyCode, setScrutinyCode] = useState<string | null>(null);

  // The client's data, its counts and status, and the one refresh after a change
  const job = useJobData(id, setActiveTab, setActiveArea);
  const { engagement, profile, setProfile, status, workpaper, isLoading, error, loadEngagement, refreshStatus, refreshAll } = job;
  const actions = useJobActions(id, engagement, job.setAuditFindings, job.setWorkpaper, refreshStatus, refreshAll, setIsViewerOpen, router);
  const { isGenerating, isDeleteModalOpen, setIsDeleteModalOpen, isDeleting, handleGenerateWorkpaper, handleConfirmDelete } = actions;

  const goToTab = (next: TabId, force = false) => {
    if (!force && setupDirty && activeTab === "setup" && next !== "setup") {
      setPendingTab(next);
      return;
    }
    // The VAT & payroll data step's address: its VAT returns are on the VAT area's Evidence tab
    if (next === "inputs") {
      setAreaStart((prev) => ({ tab: "evidence", n: (prev?.n ?? 0) + 1 }));
      openArea("vat");
      return;
    }
    setActiveTab(next);
    const url = new URL(window.location.href);
    url.searchParams.set("tab", next);
    if (next !== "area") url.searchParams.delete("area");
    window.history.replaceState(null, "", url.toString());
    window.scrollTo({ top: 0, behavior: "smooth" });
    refreshStatus();
  };
  const openArea = (key: string, evidence = false) => {
    if (evidence) setAreaStart((prev) => ({ tab: "evidence", n: (prev?.n ?? 0) + 1 }));
    setActiveArea(key);
    goToTab("area");
    const url = new URL(window.location.href);
    url.searchParams.set("area", key);
    window.history.replaceState(null, "", url.toString());
  };

  const [checksOpen, setChecksOpen] = useState(false);
  // The few questions the checks need, asked in a popup: straight after an upload (?questions=1), or from the left list
  const [questionsOpen, setQuestionsOpen] = useState(false);
  useEffect(() => {
    const url = new URL(window.location.href);
    if (url.searchParams.get("questions") === "1") {
      // eslint-disable-next-line react-hooks/set-state-in-effect -- the address is read after mounting (the server render has none), then cleaned
      setQuestionsOpen(true);
      url.searchParams.delete("questions");
      window.history.replaceState(null, "", url.toString());
    }
  }, [id]);
  // LM's checks in the background, and the watch for the re-check after each change
  const { checks, startChecks, bigUpdate } = useChecksWatch(id, refreshAll, goToTab, job.findingsNow);

  if (isLoading) {
    // The real workspace while the client loads: its name and checklist are known; only the figures shimmer
    return <WorkspaceLoading peek={peek} checklistOn={checklistOn} />;
  }

  if (error || !engagement) {
    return (
      <div className="mx-auto mt-16 max-w-xl rounded-2xl border border-rose-200 bg-white p-6 text-center shadow-sm">
        <AlertCircle className="mx-auto mb-3 h-10 w-10 text-rose-500" />
        {/* 'Failed to fetch' means the server did not answer, not that the client is missing */}
        {error && /failed to fetch|networkerror|load failed/i.test(error) ? (
          <>
            <h3 className="text-base font-bold text-slate-900">The server is not answering</h3>
            <p className="mb-4 mt-1 text-xs text-slate-500">The app could not reach its server. Check it is running, then try again.</p>
          </>
        ) : (
          <>
            <h3 className="text-base font-bold text-slate-900">Client not found</h3>
            <p className="mb-4 mt-1 text-xs text-slate-500">{error || "Could not load this client from the server."}</p>
          </>
        )}
        <div className="flex justify-center gap-2">
          <Button variant="outline" onClick={() => loadEngagement()}>Try again</Button>
          <Button variant="outline" onClick={() => router.push("/")}>Back to clients</Button>
        </div>
      </div>
    );
  }

  // Where the job stands: each step's and area's state, and the one next thing to do (lib/jobState's rules)
  const view = jobStatus({
    id, engagement, profile, auditFindings: job.auditFindings, journals: job.journals, status, workpaper,
    dataCounts: job.dataCounts, queryCounts: job.queryCounts, recCounts: job.recCounts, scrutinyFlagged: job.scrutinyFlagged,
    reanalysis: job.reanalysis, mispostings: job.mispostings, checks, secondaryLoaded: job.secondaryLoaded,
    recsLoaded: job.recsLoaded, peek,
  });
  const { workbookState, downloadUrl, workbookStale, tabById, next } = view;
  const tab = activeTab || "review";
  const shownArea = activeArea ? areaByKey(activeArea) : undefined;

  return (
    <div className="@container space-y-5">
      {engagement && (
        <ClientQuestions engagementId={id} clientName={engagement.client_name} open={questionsOpen}
                         onClose={() => setQuestionsOpen(false)}
                         onSaved={(updated) => { setProfile(updated); jobChanged(id, { big: true }); }} />
      )}
      <ChecksPanel run={checks} open={checksOpen} onClose={() => setChecksOpen(false)}
                   onOpenStep={(key) => openArea(STEP_AREA[key] || "general")} />

      {/* The workspace, as an admin panel: the job's checklist down the left and the open section beside it. The
          checklist folds to a rail of icons (each with its state as a dot) when the accountant folds it or the page is
          narrow; from the rail it opens over the page */}
      <div className="grid grid-cols-[auto_minmax(0,1fr)] gap-3 @[60rem]:gap-5">
      <ChecklistSidebar
        view={view} engagement={engagement} profile={profile} status={status} checks={checks} startChecks={startChecks}
        setChecksOpen={setChecksOpen} setQuestionsOpen={setQuestionsOpen} tab={tab} activeArea={activeArea}
        goToTab={goToTab} openArea={openArea} checklistOn={checklistOn} setChecklistOn={setChecklistOn}
        drawer={drawer} setDrawer={setDrawer} areaSignoffs={job.areaSignoffs} reanalysis={job.reanalysis}
        mispostings={job.mispostings} isGenerating={isGenerating} handleGenerateWorkpaper={handleGenerateWorkpaper}
        setIsDeleteModalOpen={setIsDeleteModalOpen}
      />
      <div className="relative min-w-0 space-y-5">
      {/* While LM checks the client again: a big change covers the page; a small one covers only the screens whose
          points, journals or figures are being redone, and other screens show the bar and stay usable */}
      {checks?.status === "RUNNING" && (bigUpdate ? <UpdatingCover checks={checks} whole />
        : REDONE.includes(tab) ? <UpdatingCover checks={checks} />
        : <div className="sticky top-2 z-20 flex justify-center"><UpdatingBar checks={checks} /></div>)}
      {/* The bar over every screen: the screen, the client, Add document, Download Excel */}
      <JobTopBar
        title={tab === "area" ? (CODING.includes(activeArea || "") ? "Coding review" : shownArea?.label || "Area") : tab === "papers" ? "Working papers" : tabById[tab]?.label || ""}
        engagementId={engagement.engagement_id}
        clientName={engagement.client_name}
        yearEnd={engagement.period_end_date}
        source={engagement.source_system === "BANK_DEXT" ? "Bank and Dext" : engagement.source_system}
        downloadUrl={downloadUrl && !workbookStale && !workpaper?.is_draft ? downloadUrl : null}
        onBuild={() => goToTab("workbook")}
        onAddDocument={() => setAddingDocument(true)}
      />
      {/* Over the tab only while the side checklist (which shows the next step) is folded to its icons */}
      <div className={checklistOn ? "@[60rem]:hidden" : undefined}>
      <EngagementHeader
        engagement={engagement}
        workbook={workbookState}
        buildBlockers={status?.build_blockers || []}
        isGenerating={isGenerating}
        onGenerate={() => handleGenerateWorkpaper()}
        onDelete={() => setIsDeleteModalOpen(true)}
        next={next}
        nextTabLabel={next.area ? next.goLabel : next.tab && next.tab !== tab ? tabById[next.tab].label : undefined}
        onGoToNext={next.area ? () => openArea(next.area!) : next.tab ? () => goToTab(next.tab!) : undefined}
        onOpenWorkbook={() => goToTab("workbook")}
      />
      </div>

      <TabPanels
        id={id} tab={tab} engagement={engagement} job={job} view={view} actions={actions} checks={checks}
        startChecks={startChecks} goToTab={goToTab} openArea={openArea} activeArea={activeArea} shownArea={shownArea}
        areaStart={areaStart} setSetupDirty={setSetupDirty} accountsView={accountsView} setAccountsView={setAccountsView}
        scrutinyCode={scrutinyCode} setScrutinyCode={setScrutinyCode} setLedgerAccount={setLedgerAccount}
        setViewing={setViewing} setIsViewerOpen={setIsViewerOpen}
      />
      </div>
      </div>

      <ExcelViewerModal
        isOpen={isViewerOpen}
        onClose={() => {
          setIsViewerOpen(false);
          setViewing(null);
        }}
        fileUrl={viewing ? resolveBackendUrl(viewing.wp.download_url) : downloadUrl}
        fileName={(viewing?.wp || workpaper)?.filename || `WP_${engagement.client_name}.xlsx`}
        initialSheet={viewing?.sheet || null}
      />

      <GLTransactionDrawer
        isOpen={Boolean(ledgerAccount)}
        onClose={() => setLedgerAccount(null)}
        engagementId={engagement.engagement_id}
        accountName={ledgerAccount?.raw_account_name || null}
        stdCode={ledgerAccount?.std_code || null}
        stdName={ledgerAccount?.std_name || null}
        netAmount={Number(ledgerAccount?.net_amount || 0)}
      />

      <AddDocumentModal
        engagementId={engagement.engagement_id}
        isOpen={addingDocument}
        onClose={() => setAddingDocument(false)}
        area={tab === "area" ? activeArea : null}
        onRead={() => jobChanged(id)}
        onGoToFiles={() => goToTab("data")}
      />
      <ConfirmDialog
        isOpen={Boolean(pendingTab)}
        onClose={() => setPendingTab(null)}
        onConfirm={() => {
          const next = pendingTab;
          setPendingTab(null);
          setSetupDirty(false);
          if (next) goToTab(next, true);
        }}
        title="Leave without saving?"
        description="The client setup has changes that are not saved. They will be lost if you leave this tab."
        confirmText="Leave without saving"
        cancelText="Stay and save"
      />

      <ConfirmDialog
        isOpen={isDeleteModalOpen}
        onClose={() => setIsDeleteModalOpen(false)}
        onConfirm={handleConfirmDelete}
        title="Delete this client?"
        description="This permanently removes the client's trial balance, ledger, mappings, review points, journals and workbooks."
        clientName={engagement.client_name}
        confirmText="Delete client"
        cancelText="Cancel"
        isLoading={isDeleting}
      />
    </div>
  );
}
