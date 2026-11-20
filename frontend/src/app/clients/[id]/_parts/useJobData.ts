// The job's data on the client page: the client, its points, journals, counts and status, how each is loaded,
// and the one refresh that reads them all again after a change.
import { useState, useEffect, useRef } from "react";
import type { Dispatch, SetStateAction } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { jobKeys } from "@/lib/queries/job";
import { jobChanged } from "@/lib/jobEvents";
import { api } from "@/lib/api";
import type { JobQueries, Reconciliations } from "@/lib/api";
import type { AreaSignoff, Mispostings, Reanalysis } from "@/lib/api";
import {
  AuditFinding,
  ClientProfile,
  EngagementData,
  EngagementStatus,
  LatestWorkpaper,
  ProposedJournal,
  SupplementaryData,
  SupplementaryDocument,
} from "@/types/engagement";
import { rememberClient } from "@/lib/clientPeek";
import { TabId, areaFromUrl, needsReview, tabFromUrl } from "./tabs";

export function useJobData(
  id: string,
  setActiveTab: Dispatch<SetStateAction<TabId | null>>,
  setActiveArea: Dispatch<SetStateAction<string | null>>,
) {
  const [engagement, setEngagement] = useState<EngagementData | null>(null);
  const [profile, setProfile] = useState<ClientProfile | null>(null);
  const [auditFindings, setAuditFindings] = useState<AuditFinding[]>([]);
  // The points and the balances have arrived (until then an area opened by its link shows loading, not "nothing")
  const [secondaryLoaded, setSecondaryLoaded] = useState(false);
  const [recsLoaded, setRecsLoaded] = useState(false);
  const [journals, setJournals] = useState<ProposedJournal[]>([]);
  const [supplementaryDocs, setSupplementaryDocs] = useState<SupplementaryDocument[]>([]);
  const [supplementaryData, setSupplementaryData] = useState<SupplementaryData>({
    vat_records: [],
    fixed_asset_records: [],
    payroll_records: [],
  });
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  // The re-analysis area's counts (its checklist status), asked after loading and after each decision
  const [reanalysis, setReanalysis] = useState<Reanalysis["summary"] | null>(null);
  const loadReanalysis = () => api.getReanalysis(id).then((r) => setReanalysis(r.summary)).catch(() => setReanalysis(null));
  // The misposting review's counts (suppliers split across accounts), asked with the re-analysis
  const [mispostings, setMispostings] = useState<Mispostings["summary"] | null>(null);
  const loadMispostings = () => api.getMispostings(id).then((m) => setMispostings(m.summary)).catch(() => setMispostings(null));
  // Sign-offs on whole areas (prepared, reviewed, approved): the area page's header and the Areas list
  const [areaSignoffs, setAreaSignoffs] = useState<Record<string, AreaSignoff[]>>({});
  useEffect(() => {
    api.getAreaSignoffs(id).then(setAreaSignoffs).catch(() => setAreaSignoffs({}));
  }, [id]);

  // The workbook: the last one built (from the server), or the one just built
  const [workpaper, setWorkpaper] = useState<LatestWorkpaper | null>(null);

  // Whether the review and the workbook are up to date (asked again after every change)
  const [status, setStatus] = useState<EngagementStatus | null>(null);

  // How many control accounts differ or need a figure (the tab's count), asked after loading and after changes
  const [recCounts, setRecCounts] = useState<Reconciliations | null>(null);
  const loadRecCounts = () =>
    api.getReconciliations(id).then((r) => setRecCounts(r)).catch(() => setRecCounts(null)).finally(() => setRecsLoaded(true));

  // The Data check's counts (the tab's badge): things that stop the workbook, and things to check
  const [dataCounts, setDataCounts] = useState<{ stops: number; warnings: number } | null>(null);
  // GL scrutiny's flagged lines not checked yet, for the Accounts step's status
  const [scrutinyFlagged, setScrutinyFlagged] = useState(0);
  const loadDataCounts = () => {
    api.getScrutinyAccounts(id).then((d) => setScrutinyFlagged(d.flagged || 0)).catch(() => setScrutinyFlagged(0));
    return api.getDataCheck(id).then((d) => setDataCounts({ stops: d.stops, warnings: d.warnings })).catch(() => setDataCounts(null));
  };

  // The Queries tab's counts (its badge): blocking queries, and every open one
  // The list is asked for once and shared with the tab: opening the Queries tab uses it (or waits for it) instead of
  // asking again; it is asked again only after the job's data or review changes
  const [queryCounts, setQueryCounts] = useState<Pick<JobQueries, "open" | "blocking" | "counts"> | null>(null);
  const queriesRef = useRef<Promise<JobQueries> | null>(null);
  const queriesLoaded = (q: JobQueries) => {
    queriesRef.current = Promise.resolve(q);
    setQueryCounts({ open: q.open, blocking: q.blocking, counts: q.counts });
  };
  const loadQueries = () => {
    if (!queriesRef.current) {
      const asked = api.getQueries(id);
      queriesRef.current = asked;
      asked
        .then((q) => setQueryCounts({ open: q.open, blocking: q.blocking, counts: q.counts }))
        .catch(() => {
          if (queriesRef.current === asked) queriesRef.current = null;
          setQueryCounts(null);
        });
    }
    return queriesRef.current;
  };
  const loadQueryCounts = () => {
    loadQueries().catch(() => undefined);
  };

  // The data or review moment the shared query list was asked at: a later one means it is asked again
  const queriesAsOf = useRef<string | null>(null);
  const refreshStatus = async () => {
    try {
      const st = await api.getEngagementStatus(id);
      const asOf = `${st.data_changed_at}|${st.review_run_at}`;
      if (queriesAsOf.current !== null && queriesAsOf.current !== asOf) {
        queriesRef.current = null;
        loadQueryCounts();
      }
      queriesAsOf.current = asOf;
      setStatus(st);
      if (st.latest_workpaper) setWorkpaper(st.latest_workpaper);
    } catch {
      // the warnings simply stay as they were
    }
  };

  // The points as last read (a re-check's 'what changed' compares them with the points after it)
  const findingsNow = useRef<AuditFinding[]>([]);
  const loadSecondary = async () => {
    const [findings, jnls, docs, sData] = await Promise.all([
      api.getAuditFindings(id),
      api.getProposedJournals(id).catch(() => []),
      api.getSupplementaryDocuments(id).catch(() => []),
      api.getSupplementaryData(id).catch(() => ({ vat_records: [], fixed_asset_records: [], payroll_records: [] })),
    ]);
    setAuditFindings(findings);
    findingsNow.current = findings;
    setSecondaryLoaded(true);
    setJournals(jnls);
    setSupplementaryDocs(docs);
    setSupplementaryData(sData);
    return findings;
  };

  const loadEngagement = async () => {
    setIsLoading(true);
    setError(null);
    try {
      // The client and its review points, journals and schedules load side by side
      const [engData] = await Promise.all([api.getEngagementById(id), loadSecondary()]);
      setEngagement(engData);
      rememberClient(id, { name: engData.client_name, source: engData.source_system || "" });
      setStatus(engData.status || null);
      setWorkpaper(engData.latest_workpaper || null);
      const prof = engData.profile || (await api.getProfile(id).catch(() => null));
      setProfile(prof);
      // Open on the first step that needs attention: the setup for a new client (nothing saved on it yet)
      const setupStarted = (prof?.confirmed_fields || []).length > 0;
      // A client with no accounting software opens on its books once the setup is started
      const booksClient = engData.source_system === "BANK_DEXT";
      // The area from the address too (read again here: after the sign-in page the address changes after the first render)
      setActiveArea((current) => current || areaFromUrl());
      setActiveTab((current) => current || tabFromUrl()
        || (!setupStarted ? "setup" : booksClient ? "books" : engData.tb_records.some(needsReview) ? "accounts" : "review"));
    } catch (err: any) {
      setError(err.message || "Failed to load the client");
    } finally {
      setIsLoading(false);
    }
  };

  useEffect(() => {
    queriesRef.current = null;
    // eslint-disable-next-line react-hooks/set-state-in-effect -- a new client id shows the loading page first (loadEngagement sets it), then its data
    loadEngagement();
    loadRecCounts();
    loadDataCounts();
    loadQueryCounts();
    loadReanalysis();
    loadMispostings();
    // eslint-disable-next-line react-hooks/exhaustive-deps -- runs once per client id: the loaders are recreated each render
  }, [id]);

  // Work confirmed in the assistant (a journal, a cleared point): the points and journals are read again
  useEffect(() => {
    const again = () => jobChanged(id);
    window.addEventListener("assistant-action", again);
    return () => window.removeEventListener("assistant-action", again);
  });

  // One refresh for every change on the client: every count, list and figure is read again,
  // so the sidebar, the header and each page show the same thing. Then LM's re-check, which a change starts on the
  // server by itself, is watched (useChecksWatch): when it ends, loadChecks refreshes everything again.
  const qc = useQueryClient();
  const refreshAll = async () => {
    queriesRef.current = null;
    qc.invalidateQueries({ queryKey: jobKeys.all(id) });
    api.getEngagementById(id).then((e) => setEngagement(e)).catch(() => undefined);
    api.getAreaSignoffs(id).then(setAreaSignoffs).catch(() => undefined);
    loadQueryCounts();
    loadReanalysis();
    loadMispostings();
    const [findings] = await Promise.all([loadSecondary().catch(() => undefined), refreshStatus()]);
    loadRecCounts();
    loadDataCounts();
    return findings;
  };

  return {
    engagement, profile, setProfile, auditFindings, setAuditFindings, secondaryLoaded, recsLoaded, journals,
    supplementaryDocs, supplementaryData, isLoading, error, reanalysis, setReanalysis, mispostings, setMispostings,
    areaSignoffs, setAreaSignoffs, workpaper, setWorkpaper, status, recCounts, setRecCounts, dataCounts, setDataCounts,
    scrutinyFlagged, queryCounts, queriesLoaded, loadQueries, refreshStatus, findingsNow, loadEngagement, refreshAll,
  };
}

export type JobData = ReturnType<typeof useJobData>;
