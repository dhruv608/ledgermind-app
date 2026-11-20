// The job's checklist down the left of the client page: the client, how far the job is, the background checks, the
// next step, and each step and working paper area with its state; folded to a rail of icons, or opened over the page.
import type { Dispatch, SetStateAction } from "react";
import Link from "next/link";
import { CheckCircle2, PanelLeftClose, PanelLeftOpen, RefreshCw, Clock, Layers } from "lucide-react";
import { codingState } from "@/lib/jobState";
import type { AreaSignoff, CheckRun, Mispostings, Reanalysis } from "@/lib/api";
import { plural, timeAgo } from "@/lib/formatters";
import type { ClientProfile, EngagementData, EngagementStatus } from "@/types/engagement";
import { clientFacts, EngagementHeader } from "@/components/clients/EngagementHeader";
import { JobDetailsLine } from "@/components/clients/JobDetailsLine";
import { cn } from "@/lib/utils";
import { CHECKLIST, CODING, TabId } from "./tabs";
import type { AreaTone, JobStatus } from "./jobStatus";

export interface ChecklistSidebarProps {
  view: JobStatus;
  engagement: EngagementData;
  profile: ClientProfile | null;
  status: EngagementStatus | null;
  checks: CheckRun | null;
  startChecks: () => void;
  setChecksOpen: Dispatch<SetStateAction<boolean>>;
  setQuestionsOpen: Dispatch<SetStateAction<boolean>>;
  tab: TabId;
  activeArea: string | null;
  goToTab: (next: TabId, force?: boolean) => void;
  openArea: (key: string, evidence?: boolean) => void;
  checklistOn: boolean;
  setChecklistOn: (value: boolean) => void;
  drawer: boolean;
  setDrawer: Dispatch<SetStateAction<boolean>>;
  areaSignoffs: Record<string, AreaSignoff[]>;
  reanalysis: Reanalysis["summary"] | null;
  mispostings: Mispostings["summary"] | null;
  isGenerating: boolean;
  handleGenerateWorkpaper: () => void;
  setIsDeleteModalOpen: Dispatch<SetStateAction<boolean>>;
}

const toneStyle: Record<AreaTone, string> = {
  stop: "bg-rose-100 text-rose-800",
  needs: "bg-amber-50 text-amber-800",
  fix: "bg-sky-100 text-sky-800",
  wait: "bg-slate-100 text-slate-600",
  done: "bg-emerald-50 text-emerald-700",
};

export function ChecklistSidebar({
  view, engagement, profile, status, checks, startChecks, setChecksOpen, setQuestionsOpen, tab, activeArea, goToTab,
  openArea, checklistOn, setChecklistOn, drawer, setDrawer, areaSignoffs, reanalysis, mispostings, isGenerating,
  handleGenerateWorkpaper, setIsDeleteModalOpen,
}: ChecklistSidebarProps) {
  const {
    setupStarted, workbookState, hasAccounts, tabById, areaStatus, workAreas, sidebarAreas, workAreaStatus, allRows,
    countOf, next,
  } = view;
  // The checklist's contents (the client, how far the job is, each section and area with its state), shown docked on
  // the left or, from the folded rail, over the page
  const pick = (go: () => void) => {
    go();
    setDrawer(false);
  };
  const openChecklist = () => {
    setChecklistOn(true);
    setDrawer(true);
  };
  const dotStyle: Record<AreaTone, string> = {
    stop: "bg-rose-500",
    needs: "bg-amber-400",
    fix: "bg-sky-500",
    wait: "bg-slate-300",
    done: "bg-emerald-500",
  };
  // A step's heading: its number in a terra circle, then its name ("1 · Set up")
  const step = (label: string) => {
    const [n, name] = label.split(" · ");
    return (
      <span className="flex items-center gap-1.5 text-[10.5px] font-bold uppercase tracking-wide text-slate-500">
        <span className="grid h-4.5 w-4.5 place-items-center rounded-full bg-terra-100 text-[10px] font-bold text-terra-700">{n}</span>
        {name}
      </span>
    );
  };
  const checklistBody = (
    <>
          {/* Who the client is (the header beside it then shows only the next step) */}
          <div className="px-1">
            <Link href="/" className="text-[11px] text-slate-400 transition hover:text-teal-700">← Clients</Link>
            <h1 className="mt-0.5 text-sm font-bold leading-snug text-slate-900">{engagement.client_name}</h1>
            <p className="mt-0.5 text-[11px] leading-relaxed text-slate-500">{clientFacts(engagement, profile).join(" · ")}</p>
            <JobDetailsLine engagementId={engagement.engagement_id} />
          </div>
          {/* How far the job is: one quiet line (each item below says its own state) */}
          <div className="border-b border-slate-100 px-1 pb-3">
            <p className="text-[11px] font-semibold text-slate-600">{countOf(["done"])} of {allRows.length} done</p>
            <div className="mt-1.5 h-1 overflow-hidden rounded-full bg-slate-100">
              <div className="h-full rounded-full bg-teal-600 transition-all"
                   style={{ width: `${allRows.length ? (100 * countOf(["done"])) / allRows.length : 0}%` }} />
            </div>
            {/* The checks in the background: the area being checked while they run, then when they last ran */}
            {checks?.status === "RUNNING" ? (
              <button type="button" onClick={() => setChecksOpen(true)} title="See each step"
                      className="mt-3 block w-full rounded-lg bg-sky-50 px-2 py-1.5 text-left hover:bg-sky-100">
                <p className="flex items-center gap-1.5 text-[11px] font-semibold text-sky-900">
                  <RefreshCw className="h-3 w-3 animate-spin" /> Checking the books
                </p>
                <p className="mt-0.5 truncate text-[10.5px] text-sky-800">
                  {checks.step_label} · {(checks.steps_done ?? 0) + 1} of {checks.steps_total}
                </p>
                <div className="mt-1 h-1 overflow-hidden rounded-full bg-sky-100">
                  <div className="h-full rounded-full bg-sky-500 transition-all"
                       style={{ width: `${(100 * ((checks.steps_done ?? 0) + 1)) / (checks.steps_total || 1)}%` }} />
                </div>
              </button>
            ) : checks?.status === "NONE" ? (
              // Not answered yet: the questions popup; answered but details still missing: the Client details tab
              <button type="button" onClick={() => (setupStarted ? goToTab("setup") : setQuestionsOpen(true))}
                      className="mt-3 block w-full rounded-lg border border-amber-200 bg-amber-50 px-2 py-1.5 text-left hover:bg-amber-100">
                <p className="flex items-center gap-1.5 text-[11px] font-semibold text-amber-900">
                  <Clock className="h-3 w-3" /> {setupStarted ? "Checks waiting for a few details" : "Checks waiting for a few answers"}
                </p>
                <p className="mt-0.5 text-[10.5px] text-amber-800">
                  {setupStarted ? "Add them on Client details: the checks start by themselves" : "Answer now: the checks start by themselves"}
                </p>
              </button>
            ) : checks ? (
              <p className="mt-2 text-[10.5px] text-slate-400">
                {checks.status === "FAILED" ? <span className="text-rose-600">Checks stopped</span>
                  : <>Checked {timeAgo(checks.finished_at)}</>}
                {checks.status === "DONE" && checks.summary && (
                  <>{" · "}<span className="text-slate-600">{plural(checks.summary.points ?? 0, "point")}, {plural(checks.summary.journals ?? 0, "journal")}</span></>
                )}
                {" · "}
                <button type="button" onClick={() => setChecksOpen(true)} className="font-medium text-teal-700 hover:underline">See details</button>
                {" · "}
                <button type="button" onClick={startChecks} className="font-medium text-teal-700 hover:underline">Check again</button>
              </p>
            ) : null}
          </div>
          {/* The one next thing to do, with its button and the job's actions */}
          <EngagementHeader
            variant="side"
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
          {CHECKLIST.map((group) => {
            const items = group.ids.map((gid) => tabById[gid]).filter(Boolean);
            if (!items.length && !group.coding && !group.papers) return null;
            if (group.papers && !(workAreas.length > 0 || hasAccounts)) return null;
            return (
              <div key={group.label} className="space-y-4">
              {!group.papers && (
              <div>
                <p className="mb-1 px-2">{step(group.label)}</p>
                <ul className="space-y-0.5">
                  {items.map(({ id: tabId, label, icon: Icon }) => {
                    const active = tab === tabId;
                    const st = areaStatus[tabId];
                    return (
                      <li key={tabId}>
                        <button
                          onClick={() => pick(() => goToTab(tabId))}
                          aria-current={active ? "page" : undefined}
                          className={cn(
                            "flex w-full items-center gap-2 rounded-lg px-2 py-1.5 text-left text-xs font-semibold transition",
                            active
                              ? "bg-teal-700 text-white shadow-sm"
                              : "text-slate-600 hover:bg-teal-50 hover:text-teal-900"
                          )}
                        >
                          <Icon className="h-3.5 w-3.5 shrink-0" />
                          <span className="flex-1 truncate">{label}</span>
                          {st && (
                            <span className={cn("shrink-0 whitespace-nowrap rounded-full px-1.5 py-px text-[10px] font-bold", toneStyle[st.tone])}>
                              {st.tone === "done" ? <CheckCircle2 className="inline h-3 w-3 -mt-px" aria-hidden="true" /> : null} {st.text}
                            </span>
                          )}
                        </button>
                      </li>
                    );
                  })}
                  {group.coding && hasAccounts && (() => {
                      // Costs in the wrong account: re-analysis and the misposting review in one place
                      const active = tab === "area" && CODING.includes(activeArea || "");
                      const st = codingState(reanalysis, mispostings);
                      return (
                        <li>
                          <button
                            onClick={() => pick(() => openArea("coding"))}
                            aria-current={active ? "page" : undefined}
                            className={cn(
                              "flex w-full items-center gap-2 rounded-lg px-2 py-1.5 text-left text-xs font-semibold transition",
                              active ? "bg-teal-700 text-white shadow-sm" : "text-slate-600 hover:bg-teal-50 hover:text-teal-900"
                            )}
                          >
                            <span className="flex-1 truncate">Coding review</span>
                            {st && (
                              <span className={cn("shrink-0 whitespace-nowrap rounded-full px-1.5 py-px text-[10px] font-bold", toneStyle[st.tone])}>
                                {st.tone === "done" ? <CheckCircle2 className="inline h-3 w-3 -mt-px" aria-hidden="true" /> : null} {st.text}
                              </span>
                            )}
                          </button>
                        </li>
                      );
                    })()}
                </ul>
              </div>
              )}
              {group.papers && (
                <div>
                  <div className="mb-1 px-2">
                    <button type="button" onClick={() => pick(() => goToTab("papers"))}
                            className={cn("block text-left transition hover:opacity-80")}
                            title="All the working papers, with their figures and status">{step(group.label)}</button>
                    {sidebarAreas.length > 0 && (
                      <span className="mt-0.5 block pl-6 text-[10.5px] text-slate-400" title="Areas approved by the partner (prepared, reviewed and approved)">
                        {sidebarAreas.filter((a) => (areaSignoffs[a.key] || []).some((s) => s.role === "PARTNER")).length} of {sidebarAreas.length} signed off
                      </span>
                    )}
                  </div>
                  <ul className="space-y-0.5">

                    {sidebarAreas.map((a) => {
                      const active = tab === "area" && activeArea === a.key;
                      const st = workAreaStatus(a.key);
                      return (
                        <li key={a.key}>
                          <button
                            onClick={() => pick(() => openArea(a.key))}
                            aria-current={active ? "page" : undefined}
                            className={cn(
                              "flex w-full items-center gap-2 rounded-lg px-2 py-1.5 text-left text-xs font-semibold transition",
                              active ? "bg-teal-700 text-white shadow-sm" : "text-slate-600 hover:bg-teal-50 hover:text-teal-900"
                            )}
                          >
                            <span className="flex-1 truncate">{a.label}</span>
                            <span className={cn("shrink-0 whitespace-nowrap rounded-full px-1.5 py-px text-[10px] font-bold", toneStyle[st.tone])}>
                              {st.tone === "done" ? <CheckCircle2 className="inline h-3 w-3 -mt-px" aria-hidden="true" /> : null} {st.text}
                            </span>
                          </button>
                        </li>
                      );
                    })}
                  </ul>
                </div>
              )}
              </div>
            );
          })}
    </>
  );

  return (
      <aside aria-label="Client checklist">
        <nav className={cn("no-scrollbar sticky top-20 h-[calc(100vh-6rem)] w-[14.5rem] space-y-4 overflow-y-auto rounded-xl border border-slate-200 bg-white p-3 shadow-sm",
                           checklistOn ? "hidden @[60rem]:block" : "hidden")}>
          <button type="button" onClick={() => { setChecklistOn(false); setDrawer(false); }}
                  className="float-right -mr-1 -mt-1 rounded-md p-1 text-slate-400 transition hover:bg-slate-100 hover:text-slate-700"
                  title="Fold the checklist (more room for the tables)" aria-label="Fold the checklist">
            <PanelLeftClose className="h-3.5 w-3.5" />
          </button>
          {checklistBody}
        </nav>
        <nav className={cn("no-scrollbar sticky top-20 flex h-[calc(100vh-6rem)] w-12 flex-col items-center gap-1 overflow-y-auto rounded-xl border border-slate-200 bg-white py-2 shadow-sm",
                           checklistOn && "@[60rem]:hidden")}>
          <button type="button" onClick={openChecklist}
                  className="mb-1 rounded-md p-2 text-slate-400 transition hover:bg-slate-100 hover:text-slate-700"
                  title="Open the checklist" aria-label="Open the checklist">
            <PanelLeftOpen className="h-4 w-4" />
          </button>
          {checks?.status === "RUNNING" && (
            <span className="mb-1 rounded-lg bg-sky-50 p-2 text-sky-700" title={`Checking the books: ${checks.step_label}`}>
              <RefreshCw className="h-4 w-4 animate-spin" />
            </span>
          )}
          {CHECKLIST.map((group, gi) => (
            <div key={group.label} className={cn("flex flex-col items-center gap-1", gi > 0 && "border-t border-slate-100 pt-1")}>
              {group.ids.map((gid) => tabById[gid]).filter(Boolean).map(({ id: tabId, label, icon: Icon }) => {
                const st = areaStatus[tabId];
                return (
                  <button key={tabId} type="button" onClick={() => goToTab(tabId)}
                          title={st ? `${label}: ${st.text}` : label} aria-label={label}
                          aria-current={tab === tabId ? "page" : undefined}
                          className={cn("relative rounded-lg p-2 transition",
                                        tab === tabId ? "bg-teal-700 text-white shadow-sm" : "text-slate-500 hover:bg-teal-50 hover:text-teal-900")}>
                    <Icon className="h-4 w-4" />
                    {st && <span className={cn("absolute right-1 top-1 h-1.5 w-1.5 rounded-full", dotStyle[st.tone])} />}
                  </button>
                );
              })}
              {group.papers && (workAreas.length > 0 || hasAccounts) && (
                <button type="button" onClick={() => goToTab("papers")} title="Working papers" aria-label="Working papers"
                        className={cn("rounded-lg p-2 transition",
                                      tab === "area" || tab === "papers" ? "bg-teal-700 text-white shadow-sm" : "text-slate-500 hover:bg-teal-50 hover:text-teal-900")}>
                  <Layers className="h-4 w-4" />
                </button>
              )}
            </div>
          ))}
        </nav>
        {/* Opened from the rail: the whole checklist over the page */}
        {drawer && (
          <div className={cn("fixed inset-0 z-50", checklistOn && "@[60rem]:hidden")}>
            <div className="absolute inset-0 bg-slate-900/20" onClick={() => setDrawer(false)} />
            <nav className="no-scrollbar absolute inset-y-0 left-0 w-[16rem] space-y-4 overflow-y-auto border-r border-slate-200 bg-white p-3 shadow-xl">
              <button type="button" onClick={() => setDrawer(false)}
                      className="float-right -mr-1 -mt-1 rounded-md p-1 text-slate-400 transition hover:bg-slate-100 hover:text-slate-700"
                      title="Close" aria-label="Close the checklist">
                <PanelLeftClose className="h-3.5 w-3.5" />
              </button>
              {checklistBody}
            </nav>
          </div>
        )}
      </aside>
  );
}
