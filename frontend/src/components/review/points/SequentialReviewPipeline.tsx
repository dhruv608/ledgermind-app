"use client";

import { useEffect, useMemo, useState } from "react";
import { pointsToAct } from "@/lib/jobState";
import { AuditFinding, ProposedJournal } from "@/types/engagement";
import { BookOpenText, Calculator, Check, CheckCircle2, ChevronDown, Download, ListChecks, Lock, Mail, RefreshCw, X } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { SectionHeader } from "@/components/ui/section-header";
import { Modal } from "@/components/ui/dialog";
import { ClientEmailDialog } from "@/components/clients/ClientEmailDialog";
import { CapitalAllowancesPanel } from "@/components/review/workpapers/CapitalAllowancesPanel";
import { PointCard } from "@/components/review/points/PointCard";
import { EmptyState } from "@/components/common/EmptyState";
import { CustomSelect } from "@/components/ui/custom-select";
import { areaOfPoint } from "@/lib/areas";
import { toast } from "@/lib/notify";
import { api, SetupGapsError } from "@/lib/api";
import type { CheckRun, PointSignoff } from "@/lib/api";
import { Tabs } from "@/components/ui/tabs";
import { cn } from "@/lib/utils";
import { plural } from "@/lib/formatters";
import { useRememberedState } from "@/hooks/useRememberedState";
import { useJobStore, useSignoffs } from "@/lib/queries/job";

interface SequentialReviewPipelineProps {
  engagementId: string;
  findings: AuditFinding[];
  journals: ProposedJournal[];
  onReviewCompleted: () => void;
  /** The checks in the background (the page asks how far they have got); Run review starts them */
  checks?: CheckRun | null;
  onRunChecks?: () => void | Promise<void>;
  onClearFinding: (findingId: number, note?: string) => void | Promise<void>;
  /** Clear several points at once with one note (the low points), one message at the end. */
  onClearMany?: (findingIds: number[], note: string) => Promise<void>;
  /** Open the Setup tab (the review waits for the setup's blocking gaps). */
  onGoToSetup?: () => void;
  /** The client's account names, to link a point to its ledger lines. */
  accountNames?: string[];
  onOpenAccount?: (accountName: string) => void;
  /** For the email to the client */
  clientName?: string;
  yearEnd?: string | null;
}

// Asked of every client (the accountant's answer: ask the client for mileage, use of home and the accountancy fee);
// negative ids so they never clash with a review point's id
const STANDARD_QUESTIONS = [
  { id: -1, text: "Please send your mileage log for the year (date, from, to, purpose and miles of each business journey made in your own car)." },
  { id: -2, text: "Do you use your home for the business? If yes, please confirm the hours a month you work from home." },
  { id: -3, text: "Please confirm the accountancy fee for this year's accounts." },
  { id: -4, text: "Did the director take a salary this year? Please send the P60 or payslips, or confirm none was paid." },
];

type Stage = "ALL" | "STAGE_1_ACCOUNTING" | "STAGE_2_VAT" | "STAGE_3_CT600";

const STAGES: { id: Stage; label: string }[] = [
  { id: "ALL", label: "All" },
  { id: "STAGE_1_ACCOUNTING", label: "Accounts checks" },
  { id: "STAGE_2_VAT", label: "VAT" },
  { id: "STAGE_3_CT600", label: "Corporation tax" },
];

const SEVERITY_ORDER = ["CRITICAL", "HIGH", "MEDIUM", "LOW"];

// Points shown per group before Show more
const FIRST_POINTS = 3;

const stageOf = (f: AuditFinding): Stage => (f.stage as Stage) || "STAGE_1_ACCOUNTING";

type SeverityFilter = "ALL" | "HIGH" | "MEDIUM" | "LOW";
const matchesSeverity = (f: AuditFinding, filter: SeverityFilter) => {
  const sev = (f.severity || "LOW").toUpperCase();
  if (filter === "HIGH") return sev === "HIGH" || sev === "CRITICAL";
  return filter === "ALL" || sev === filter;
};

/** The tax computation finding is written as "Label (Box 155): £1,234.00" lines: show them as a table. */
function parseComputation(details: string) {
  const rows: { label: string; box?: string; amount: string }[] = [];
  const notes: string[] = [];
  for (const line of details.split("\n")) {
    const m = line.match(/^(.*?)(?: \(Box ([^)]+)\))?: (£-?[\d,]+\.\d{2})$/);
    if (m) rows.push({ label: m[1], box: m[2], amount: m[3].replace(/^£-0\.00$/, "£0.00").replace(/^£-(.+)$/, "(£$1)") });
    else if (line.trim()) notes.push(line.trim().replace(/£-([\d,]+(?:\.\d{2})?)/g, "(£$1)"));
  }
  return { rows, notes };
}

/** A check's name without the guide it comes from: "Sector Audit (RTL): Stock count" -> "Industry check: Stock count". */
const checkName = (name: string) =>
  name
    .replace(/^Sector Audit \([^)]*\):\s*/i, "Industry check: ")
    .replace(/\s*\((?:[^()]*guide[^()]*|[^()]*\bSOP\b[^()]*|Tax_Comp)\)\s*$/i, "")
    .replace(/^VAT Review:\s*/i, "VAT: ");

export function SequentialReviewPipeline({
  engagementId,
  findings,
  journals,
  onReviewCompleted,
  checks = null,
  onRunChecks,
  onClearFinding,
  onClearMany,
  accountNames = [],
  onOpenAccount,
  onGoToSetup,
  clientName = "",
  yearEnd = null,
}: SequentialReviewPipelineProps) {
  // Email to the client: the accountant picks the open points to ask about (the review's points are written for
  // the accountant, so the email text can be reworded before copying)
  const [picking, setPicking] = useState(false);
  const [picked, setPicked] = useState<Set<number>>(new Set());
  const [emailOpen, setEmailOpen] = useState(false);
  const askable = useMemo(() => findings.filter((f) => f.status === "OPEN" && f.procedure_ref !== "CT-01"), [findings]);
  // Sign-offs on the points (the same card as the area pages: Issue / Detail / Action, journal, sign-off)
  const signoffs: Record<string, PointSignoff[]> = useSignoffs(engagementId).data ?? {};
  const setSignoffs = useJobStore(engagementId).setSignoffs;
  const emailGroups = useMemo(() => [{
    title: "Please explain or send",
    items: [...STANDARD_QUESTIONS.filter((q) => picked.has(q.id)).map((q) => q.text),
            ...askable.filter((f) => picked.has(f.id)).map((f) => f.finding_title)],
  }], [askable, picked]);
  // Blocking gaps in the client setup: the review waits for them
  const [gaps, setGaps] = useState<string[] | null>(null);
  useEffect(() => {
    api.getSetupStatus(engagementId).then((s) => setGaps(s.gaps)).catch(() => setGaps([]));
  }, [engagementId]);
  const blocked = Boolean(gaps && gaps.length);
  const [severity, setSeverity] = useState<SeverityFilter>("ALL");
  // One area's points only (VAT, payroll ...), and the biggest amounts first
  const [areaFilter, setAreaFilter] = useState("ALL");
  const [biggestFirst, setBiggestFirst] = useState(false);
  // Low points cleared together (they stay in the list, under Show cleared, with the note)
  const lowOpen = useMemo(() => findings.filter((f) => f.status === "OPEN" && f.procedure_ref !== "CT-01"
    && (f.severity || "LOW").toUpperCase() === "LOW"), [findings]);
  const [askClearLow, setAskClearLow] = useState(false);
  const [clearingLow, setClearingLow] = useState(false);
  const LOW_NOTE = "Low point: cleared together with the other low points";
  const clearLow = async () => {
    if (!onClearMany) return;
    setClearingLow(true);
    try {
      await onClearMany(lowOpen.map((f) => f.id), LOW_NOTE);
      setAskClearLow(false);
    } finally {
      setClearingLow(false);
    }
  };

  // The account a point is about: the longest client account name in its reference or title
  const byLength = useMemo(() => [...accountNames].sort((a, b) => b.length - a.length), [accountNames]);
  const accountOf = (f: AuditFinding) => {
    const hay = `${f.source_row_ref || ""} | ${f.finding_title}`;
    return byLength.find((name) => name.length > 3 && hay.includes(name)) || null;
  };

  const [isRunning, setIsRunning] = useState(false);
  const [stage, setStage] = useState<Stage>("ALL");
  const [showCleared, setShowCleared] = useRememberedState("review.showCleared", false);
  // The download: a PDF report or an Excel list of all the points, the open ones, or what the tab shows
  const [downloadOpen, setDownloadOpen] = useState(false);
  const [dlFormat, setDlFormat] = useRememberedState<"pdf" | "xlsx">("review.dlFormat", "pdf");
  const [dlInclude, setDlInclude] = useRememberedState<"all" | "open" | "screen">("review.dlInclude", "all");
  const [downloading, setDownloading] = useState(false);
  const download = async () => {
    setDownloading(true);
    try {
      await api.downloadReview(engagementId, {
        format: dlFormat,
        include: dlInclude === "screen" ? (showCleared ? "screen" : "screen_open") : dlInclude,
        stage: stage === "ALL" ? "" : stage,
        severity: severity === "ALL" ? "" : severity,
      });
      setDownloadOpen(false);
    } catch (e) {
      toast.error(e instanceof Error ? e.message : "Could not make the download");
    } finally {
      setDownloading(false);
    }
  };
  const [collapsedGroups, setCollapsedGroups] = useState<Set<string>>(new Set());
  // A group shows its first few points; Show more opens the rest (so the page stays short, no group split over pages)
  const [fullGroups, setFullGroups] = useState<Set<string>>(new Set());
  const [showComputation, setShowComputation] = useState(false);

  const runPipeline = async () => {
    // In the background: the page shows the progress and reads the points again when the checks finish
    if (onRunChecks) {
      await onRunChecks();
      return;
    }
    setIsRunning(true);
    try {
      const res = await api.runSequentialReview(engagementId);
      toast.success("Review finished", {
        description: `${plural(res.total_findings, "point")} to look at, ${plural(res.total_journals, "journal")} proposed.`,
      });
      onReviewCompleted();
    } catch (err: any) {
      if (err instanceof SetupGapsError) {
        setGaps(err.gaps);
        toast.warning("Finish the client setup first", { description: err.gaps.join(" · ") });
        return;
      }
      toast.error("Review failed", { description: err.message || "The review could not run." });
    } finally {
      setIsRunning(false);
    }
  };

  const checksRunning = checks?.status === "RUNNING";
  const running = isRunning || checksRunning;

  const ctFinding = findings.find((f) => f.procedure_ref === "CT-01");
  const computation = ctFinding ? parseComputation(ctFinding.finding_details || "") : null;
  const ctTotal = computation?.rows.find((r) => /^Total tax chargeable/.test(r.label))?.amount;

  const counts = useMemo(() => {
    // The points to act on, counted as the sidebar counts them (lib/jobState: points for information only are not)
    const open = pointsToAct(findings, journals);
    return {
      ALL: open.length,
      STAGE_1_ACCOUNTING: open.filter((f) => stageOf(f) === "STAGE_1_ACCOUNTING").length,
      STAGE_2_VAT: open.filter((f) => stageOf(f) === "STAGE_2_VAT").length,
      STAGE_3_CT600: open.filter((f) => stageOf(f) === "STAGE_3_CT600").length,
      cleared: findings.filter((f) => f.status === "CLEARED").length,
    };
  }, [findings, journals]);

  // Points to show, grouped by the check that raised them; most serious groups first
  const groups = useMemo(() => {
    const shown = findings.filter(
      (f) =>
        f.procedure_ref !== "CT-01" &&
        (stage === "ALL" || stageOf(f) === stage) &&
        matchesSeverity(f, severity) &&
        (areaFilter === "ALL" || areaOfPoint(f).key === areaFilter) &&
        (showCleared || f.status !== "CLEARED")
    );
    const byCheck = new Map<string, AuditFinding[]>();
    const order = (f: AuditFinding) => SEVERITY_ORDER.indexOf((f.severity || "LOW").toUpperCase());
    for (const f of [...shown].sort((a, b) => order(a) - order(b))) {
      const key = f.procedure_name || f.procedure_ref;
      byCheck.set(key, [...(byCheck.get(key) || []), f]);
    }
    const rank = (fs: AuditFinding[]) => Math.min(...fs.map((f) => SEVERITY_ORDER.indexOf((f.severity || "LOW").toUpperCase())));
    const size = (fs: AuditFinding[]) => fs.reduce((t, f) => t + Math.abs(Number(f.quantified_amount) || 0), 0);
    if (biggestFirst) {
      for (const [k, fs] of byCheck) byCheck.set(k, [...fs].sort((a, b) => Math.abs(Number(b.quantified_amount) || 0) - Math.abs(Number(a.quantified_amount) || 0)));
      return [...byCheck.entries()].sort((a, b) => size(b[1]) - size(a[1]));
    }
    return [...byCheck.entries()].sort((a, b) => rank(a[1]) - rank(b[1]) || b[1].length - a[1].length);
  }, [findings, stage, showCleared, severity, areaFilter, biggestFirst]);
  const areaOptions = useMemo(() => {
    const by = new Map<string, { label: string; n: number }>();
    for (const f of findings) {
      if (f.procedure_ref === "CT-01" || f.status === "CLEARED") continue;
      const a = areaOfPoint(f);
      by.set(a.key, { label: a.label, n: (by.get(a.key)?.n || 0) + 1 });
    }
    return [{ value: "ALL", label: "All areas" },
            ...Array.from(by, ([key, a]) => ({ value: key, label: `${a.label} (${a.n})` })).sort((a, b) => a.label.localeCompare(b.label))];
  }, [findings]);

  const toggle = <T,>(set: Set<T>, value: T) => {
    const next = new Set(set);
    if (next.has(value)) next.delete(value);
    else next.add(value);
    return next;
  };

  // One point's card (the same card as the area pages), with its ledger lines link
  const pointCard = (f: AuditFinding) => (
    <PointCard
      engagementId={engagementId}
      finding={f}
      journal={journals.find((j) => j.finding_id === f.id)}
      signoffs={signoffs[String(f.id)]}
      onSignoffs={setSignoffs}
      onClear={(id, note) => onClearFinding(id, note)}
      showArea
      onJournalsUpdated={onReviewCompleted}
      links={onOpenAccount && accountOf(f) ? (
        <button type="button" onClick={() => onOpenAccount(accountOf(f)!)}
                className="inline-flex items-center gap-1 text-[11px] font-medium text-slate-500 hover:text-teal-800"
                title={`Ledger lines of ${accountOf(f)}`}>
          <BookOpenText className="h-3 w-3" /> Ledger lines
        </button>
      ) : undefined}
    />
  );

  return (
    <div className="space-y-5">
      <Card className="px-4 py-3.5">
        <SectionHeader
          icon={ListChecks}
          title="Review" page
          description="Runs every check: the accounts checks, the VAT returns against the ledger, and the corporation tax computation. Nothing is posted: journals only appear as proposals."
          actions={
            <div className="flex flex-wrap gap-2">
              <Button variant="outline" size="sm" onClick={() => setDownloadOpen(true)}>
                <Download className="mr-1.5 h-3.5 w-3.5" /> Download
              </Button>
              <Button variant="outline" size="sm" onClick={() => setPicking(true)}>
                <Mail className="mr-1.5 h-3.5 w-3.5" /> Make client email
              </Button>
              <Button variant="primary" size="sm" onClick={runPipeline} disabled={running || blocked || gaps === null}
                      title={blocked ? "Finish the client setup first" : undefined}>
                <RefreshCw className={cn("mr-1.5 h-3.5 w-3.5", running && "animate-spin")} />
                {checksRunning ? `Checking: ${checks?.step_label || "the books"}…` : isRunning ? "Running the review…" : "Run review"}
              </Button>
            </div>
          }
        />
      </Card>

      <Modal isOpen={picking} onClose={() => setPicking(false)} title="Which points to ask the client?"
             description="Tick the open points the client must answer. You can reword them in the next step.">
        <div className="space-y-3 text-xs">
          <div className="flex gap-3 text-[11px]">
            <button className="text-teal-800 hover:underline"
                    onClick={() => setPicked(new Set([...STANDARD_QUESTIONS.map((q) => q.id), ...askable.map((f) => f.id)]))}>Tick all</button>
            <button className="text-slate-500 hover:underline" onClick={() => setPicked(new Set())}>Clear</button>
          </div>
          <div className="max-h-[50vh] space-y-1 overflow-y-auto rounded-lg border border-slate-200 p-2">
            <p className="px-2 pt-1 text-[11px] font-semibold text-slate-500">Asked of every client</p>
            {STANDARD_QUESTIONS.map((q) => (
              <label key={q.id} className="flex cursor-pointer items-start gap-2 rounded-md px-2 py-1.5 hover:bg-slate-50">
                <input type="checkbox" className="mt-0.5" checked={picked.has(q.id)}
                       onChange={(e) => setPicked((p) => { const n = new Set(p); if (e.target.checked) n.add(q.id); else n.delete(q.id); return n; })} />
                <span className="text-slate-800">{q.text}</span>
              </label>
            ))}
            {askable.length > 0 && <p className="px-2 pt-2 text-[11px] font-semibold text-slate-500">From the review</p>}
            {askable.map((f) => (
              <label key={f.id} className="flex cursor-pointer items-start gap-2 rounded-md px-2 py-1.5 hover:bg-slate-50">
                <input type="checkbox" className="mt-0.5" checked={picked.has(f.id)}
                       onChange={(e) => setPicked((p) => { const n = new Set(p); if (e.target.checked) n.add(f.id); else n.delete(f.id); return n; })} />
                <span>
                  <span className="font-medium text-slate-800">{f.finding_title}</span>
                  <span className="block text-[11px] text-slate-500 line-clamp-2">{f.finding_details}</span>
                </span>
              </label>
            ))}
          </div>
          <div className="flex justify-end gap-2">
            <Button size="sm" variant="outline" onClick={() => setPicking(false)}>Cancel</Button>
            <Button size="sm" variant="primary" disabled={!picked.size} onClick={() => { setPicking(false); setEmailOpen(true); }}>
              Make email ({picked.size})
            </Button>
          </div>
        </div>
      </Modal>
      <ClientEmailDialog isOpen={emailOpen} onClose={() => setEmailOpen(false)} client={clientName} yearEnd={yearEnd} groups={emailGroups} />

      <Modal isOpen={downloadOpen} onClose={() => setDownloadOpen(false)} title="Download the review points"
             description="A record of this review to send or keep on file: each point with its status and how it was cleared.">
        <div className="space-y-4 text-xs">
          <div className="space-y-1.5">
            <p className="font-semibold text-slate-700">File</p>
            {([["pdf", "PDF report", "To send or keep on file"], ["xlsx", "Excel list", "To sort, filter or add comments"]] as const).map(([v, label, hint]) => (
              <label key={v} className="flex cursor-pointer items-start gap-2 rounded-md px-2 py-1.5 hover:bg-slate-50">
                <input type="radio" name="dl-format" className="mt-0.5" checked={dlFormat === v} onChange={() => setDlFormat(v)} />
                <span><span className="font-medium text-slate-800">{label}</span> <span className="text-slate-500">· {hint}</span></span>
              </label>
            ))}
          </div>
          <div className="space-y-1.5">
            <p className="font-semibold text-slate-700">Points</p>
            {([["all", "All points (open and cleared)", "The full record"], ["open", "Open points only", "What still needs doing"],
               ["screen", "What is on screen now", `${stage === "ALL" ? "All stages" : `${STAGES.find((s) => s.id === stage)?.label} stage`},${severity === "ALL" ? "all severities" : `${severity.toLowerCase()} severity`}${showCleared ? ", with cleared" : ""}`]] as const).map(([v, label, hint]) => (
              <label key={v} className="flex cursor-pointer items-start gap-2 rounded-md px-2 py-1.5 hover:bg-slate-50">
                <input type="radio" name="dl-include" className="mt-0.5" checked={dlInclude === v} onChange={() => setDlInclude(v)} />
                <span><span className="font-medium text-slate-800">{label}</span> <span className="text-slate-500">· {hint}</span></span>
              </label>
            ))}
          </div>
          <div className="flex justify-end gap-2">
            <Button size="sm" variant="outline" onClick={() => setDownloadOpen(false)}>Cancel</Button>
            <Button size="sm" variant="primary" disabled={downloading} onClick={download}>
              <Download className="mr-1.5 h-3.5 w-3.5" /> {downloading ? "Making the file…" : "Download"}
            </Button>
          </div>
        </div>
      </Modal>

      {blocked && (
        <div className="flex items-center justify-between gap-3 rounded-xl border border-amber-200 bg-amber-50 px-4 py-2.5">
          <p className="min-w-0 text-xs text-amber-900">
            <Lock className="-mt-0.5 mr-1.5 inline h-3.5 w-3.5" />
            <span className="font-semibold">The review waits for the client setup:</span>{" "}
            {gaps!.map((g) => g.replace(/ (not chosen|not entered|not set|not answered)$/i, "")
                              .replace(/^([A-Z])(?=[a-z])/, (c) => c.toLowerCase())).join(", ")}
          </p>
          {onGoToSetup && (
            <Button variant="outline" size="sm" onClick={onGoToSetup} className="h-7 shrink-0 bg-white text-xs">
              Go to setup
            </Button>
          )}
        </div>
      )}

      {ctFinding && computation && (
        <Card className="overflow-hidden">
          <button
            type="button"
            onClick={() => setShowComputation(!showComputation)}
            className="flex w-full flex-wrap items-center justify-between gap-3 px-5 py-4 text-left transition-colors hover:bg-teal-50/40"
          >
            <span className="flex items-center gap-3">
              <span className="flex h-8 w-8 items-center justify-center rounded-lg bg-teal-50 text-teal-700">
                <Calculator className="h-4 w-4" />
              </span>
              <span>
                <span className="block text-sm font-semibold text-slate-900">
                  Corporation tax{ctTotal ? <>: <span className="font-mono">{ctTotal}</span></> : null}
                </span>
                <span className="block text-[11px] text-slate-500">Draft, check before filing. Same figures as the H1 tab of the workbook.</span>
              </span>
            </span>
            <span className="inline-flex items-center gap-1 text-xs font-medium text-teal-800">
              {showComputation ? "Hide" : "Show"} the computation
              <ChevronDown className={cn("h-3.5 w-3.5 transition", showComputation && "rotate-180")} />
            </span>
          </button>
          {showComputation && computation.rows.length > 0 ? (
            <table className="w-full text-xs">
              <thead className="bg-slate-50 text-[11px] uppercase tracking-wide text-slate-500">
                <tr>
                  <th className="px-5 py-2 text-left font-semibold">Line</th>
                  <th className="w-24 px-3 py-2 text-left font-semibold">CT600 box</th>
                  <th className="w-36 px-5 py-2 text-right font-semibold">£</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-100">
                {computation.rows.map((r, i) => {
                  const total = /^(Profits chargeable|Corporation tax chargeable|Total tax)/.test(r.label);
                  return (
                    <tr key={i} className={total ? "bg-teal-50/50 font-semibold text-slate-900" : "text-slate-700"}>
                      <td className="px-5 py-1.5">{r.label}</td>
                      <td className="px-3 py-1.5 font-mono text-slate-500">{r.box || ""}</td>
                      <td className="px-5 py-1.5 text-right font-mono">{r.amount.replace("£", "")}</td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          ) : null}
          {showComputation && computation.notes.length > 0 && (
            <div className="space-y-1.5 border-t border-slate-100 bg-slate-50/60 px-5 py-3 text-[11px] leading-relaxed text-slate-600">
              {computation.notes.map((n, i) => (
                <p key={i}>{n}</p>
              ))}
            </div>
          )}
        </Card>
      )}

      {/* This year's additions: the app's suggested capital allowance, the accountant's choice */}
      {ctFinding && <CapitalAllowancesPanel engagementId={engagementId} />}

      {/* Which points to show (once the review has found any) */}
      {findings.length > 0 && (
      <Tabs
        label="Points by stage"
        items={STAGES.map((st) => ({ id: st.id, label: st.label, count: counts[st.id] }))}
        value={stage}
        onChange={setStage}
        actions={<>
          <CustomSelect value={areaFilter} onChange={setAreaFilter} align="right" title="Area" options={areaOptions} />
          <CustomSelect
            value={severity}
            onChange={setSeverity}
            align="right"
            title="How serious"
            options={[
              { value: "ALL", label: "All levels" },
              { value: "HIGH", label: "High and critical" },
              { value: "MEDIUM", label: "Medium" },
              { value: "LOW", label: "Low" },
            ]}
          />
          <label className="flex cursor-pointer items-center gap-2 text-xs text-slate-600">
            <input type="checkbox" checked={showCleared} onChange={(e) => setShowCleared(e.target.checked)} className="accent-teal-700" />
            Show cleared ({counts.cleared})
          </label>
          <label className="flex cursor-pointer items-center gap-2 text-xs text-slate-600">
            <input type="checkbox" checked={biggestFirst} onChange={(e) => setBiggestFirst(e.target.checked)} className="accent-teal-700" />
            Biggest first
          </label>
          {onClearMany && lowOpen.length > 0 && (
            <Button size="sm" variant="outline" className="h-8 text-xs" onClick={() => setAskClearLow(true)}
                    title="Clear every open low point in one go">
              <Check className="mr-1 h-3.5 w-3.5" /> Clear low points ({lowOpen.length})
            </Button>
          )}
          {groups.length > 1 && (
            <Button size="sm" variant="ghost" className="h-8 text-xs text-slate-500 hover:text-teal-800"
                    onClick={() => setCollapsedGroups(collapsedGroups.size >= groups.length ? new Set() : new Set(groups.map(([g]) => g)))}>
              {collapsedGroups.size >= groups.length ? "Expand all" : "Collapse all"}
            </Button>
          )}
        </>}
      />
      )}

      <Modal
        isOpen={askClearLow}
        onClose={() => !clearingLow && setAskClearLow(false)}
        title={`Clear ${plural(lowOpen.length, "low point")}?`}
        description="They stay on the list under Show cleared, with a note that they were cleared together as low points."
      >
        <div className="flex justify-end gap-2">
          <Button size="sm" variant="outline" disabled={clearingLow} onClick={() => setAskClearLow(false)}>Cancel</Button>
          <Button size="sm" variant="primary" disabled={clearingLow} onClick={clearLow}>
            {clearingLow ? <RefreshCw className="mr-1.5 h-3.5 w-3.5 animate-spin" /> : <Check className="mr-1.5 h-3.5 w-3.5" />}
            Clear {plural(lowOpen.length, "point")}
          </Button>
        </div>
      </Modal>

      {/* Points, grouped by check */}
      {groups.length === 0 ? (
        <EmptyState
          icon={CheckCircle2}
          art={findings.length ? "done" : "start"}
          title={findings.length ? "No open points here" : "The review has not run yet"}
          description={findings.length ? "Everything in this section is cleared." : "Press “Run review” to run all the checks."}
        />
      ) : (
        <div className="space-y-3">
          {groups.map(([check, items]) => {
            const open = items.filter((f) => f.status === "OPEN").length;
            const isCollapsed = collapsedGroups.has(check);
            const full = fullGroups.has(check) || items.length <= FIRST_POINTS + 1;
            const visible = full ? items : items.slice(0, FIRST_POINTS);
            // A check with one point: the card alone (its area is on the card; a box and heading around it repeat it)
            if (items.length === 1) return <ul key={check}>{pointCard(items[0])}</ul>;
            return (
              <Card key={check} className="overflow-hidden">
                <button
                  onClick={() => setCollapsedGroups(toggle(collapsedGroups, check))}
                  className="flex w-full items-center justify-between gap-3 bg-slate-50/70 px-4 py-2.5 text-left transition-colors hover:bg-teal-50/60"
                >
                  <div className="flex min-w-0 items-center gap-2">
                    <ChevronDown className={cn("h-4 w-4 shrink-0 text-slate-400 transition", isCollapsed && "-rotate-90")} />
                    <span className="truncate text-[13px] font-semibold text-slate-900" title={check}>{checkName(check)}</span>
                  </div>
                  <span className="shrink-0 text-[11px] text-slate-500">
                    {open} open{items.length > open ? ` · ${items.length - open} cleared` : ""}
                  </span>
                </button>
                {!isCollapsed && (
                  <ul className="space-y-0.5 py-1">
                    {visible.map((f) => (
                      <div key={f.id} className="px-3 py-2">
                        {pointCard(f)}
                      </div>
                    ))}
                    {items.length > FIRST_POINTS + 1 && (
                      <li className="px-3 pb-2">
                        <button type="button" onClick={() => setFullGroups(toggle(fullGroups, check))}
                                className="w-full rounded-lg border border-dashed border-slate-200 py-2 text-xs font-semibold text-teal-700 transition-colors hover:border-teal-300 hover:bg-teal-50/60">
                          {full ? "Show fewer" : `Show ${plural(items.length - FIRST_POINTS, "more point")}`}
                        </button>
                      </li>
                    )}
                  </ul>
                )}
              </Card>
            );
          })}
        </div>
      )}
    </div>
  );
}
