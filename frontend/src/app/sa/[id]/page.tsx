"use client";

// An individual's Self Assessment return. It opens on the Overview (the result, the steps, each kind of income and
// what to look at); the checklist down the left shows each page's state and amount, and the result stays in the
// header while figures change. Pages not built yet (last year, the pack, points, queries) are not shown.
import { use, useCallback, useEffect, useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { toast } from "@/lib/notify";
import type { LucideIcon } from "lucide-react";
import { ArrowLeft, Calculator, CheckCircle2, ClipboardList, Globe, FileSpreadsheet, History, LayoutDashboard, ListChecks, MessageSquareMore, PanelLeftClose,
         PanelLeftOpen, Trash2, TrendingUp, UserRound, Users } from "lucide-react";
import { useRememberedState } from "@/hooks/useRememberedState";
import { api, SaJob, SaOverview as OverviewData, SaState } from "@/lib/api";
import { Button } from "@/components/ui/button";
import { ConfirmDialog } from "@/components/ui/confirm-dialog";
import { SOURCE_LABELS } from "@/components/sa/NewIndividualModal";
import { SaDocuments } from "@/components/sa/SaDocuments";
import { PAGES, SaIncomePage } from "@/components/sa/SaIncomePage";
import { SaTaxCalc } from "@/components/sa/SaTaxCalc";
import { SaPropertyPage } from "@/components/sa/SaPropertyPage";
import { SaTradePage } from "@/components/sa/SaTradePage";
import { SaLastYear } from "@/components/sa/SaLastYear";
import { SaQueries } from "@/components/sa/SaQueries";
import { SaBoxes } from "@/components/sa/SaBoxes";
import { SaPack } from "@/components/sa/SaPack";
import { SaFamily } from "@/components/sa/SaFamily";
import { SaCapitalGains } from "@/components/sa/SaCapitalGains";
import { SaForeign } from "@/components/sa/SaForeign";
import { SaOverview, SECTION_ICONS, STATE_DOT, money, statePill } from "@/components/sa/SaOverview";
import { PILL, SaHead, TABLE_WRAP, text } from "@/components/sa/SaChrome";
import { SaDocViewer } from "@/components/sa/SaDocViewer";
import { cn } from "@/lib/utils";

type Item = { id: string; label: string; icon: LucideIcon; state?: SaState; amount?: string; soon?: boolean };

// Pages still to come, and what they will hold
const SOON: Record<string, [string, string]> = {
  points: ["Stage 6", "Every point the checks raise on this return, with filters, as on a company."],
};

function Details({ job, onDelete }: { job: SaJob; onDelete: () => void }) {
  const rows: [string, React.ReactNode][] = [
    ["Tax year", job.tax_year],
    ["Last year", job.first_return ? "First return with us" : "Returning client"],
    ["UTR", job.utr || "—"],
    ["NI number", job.ni_number || "—"],
    ["Director of", job.company ? <Link href={`/clients/${job.company.engagement_id}`} className="text-teal-700 hover:underline">{job.company.name}</Link> : "—"],
    ["Kinds of income", job.sources.map((s) => SOURCE_LABELS[s]).join(", ")],
  ];
  return (
    <div className="space-y-4">
      <SaHead title="Client details" meta="Who this return is for, the tax year and the kinds of income it covers."
                  actions={<Button variant="outline" size="sm" onClick={onDelete} className="hover:text-rose-600 hover:border-rose-300">
                    <Trash2 className="w-3.5 h-3.5 mr-1" /> Delete return
                  </Button>} />
      <section className={TABLE_WRAP}>
        <dl className="divide-y divide-slate-100 text-sm">
          {rows.map(([k, v]) => (
            <div key={k} className="grid grid-cols-[11rem_1fr] gap-4 px-5 py-2.5"><dt className="text-slate-500">{k}</dt><dd className="text-slate-900">{v}</dd></div>
          ))}
        </dl>
      </section>
    </div>
  );
}

function NotYet({ id, title }: { id: string; title: string }) {
  const [stage, words] = SOON[id] || ["Later", "This page comes in a later stage."];
  return (
    <SaHead title={title} state={{ text: `Coming in ${stage.toLowerCase()}`, tone: "empty" }} meta={words} />
  );
}

export default function SaJobPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = use(params);
  const router = useRouter();
  const [job, setJob] = useState<SaJob | null>(null);
  const [view, setView] = useState<OverviewData | null>(null);
  const [error, setError] = useState("");
  const [page, setPage] = useState("overview");
  const [doc, setDoc] = useState<number | null>(null);
  const [confirming, setConfirming] = useState(false);
  // A document checked in the viewer: the open page loads again with its figures
  const [ver, setVer] = useState(0);
  // The checklist open, or folded to a rail of icons (with their state) for more room: remembered, as on a company
  const [sideOn, setSideOn] = useRememberedState<boolean>("sa.checklist", true);

  const refresh = useCallback(() => { api.getSaOverview(id).then(setView).catch(() => {}); }, [id]);

  useEffect(() => {
    api.getSaJob(id).then(setJob).catch((e) => setError(e.message));
    refresh();
    // The page named in the address (#tax): on opening, and when it changes (back button, a link)
    const follow = () => setPage(window.location.hash.slice(1) || "overview");
    follow();
    window.addEventListener("hashchange", follow);
    return () => window.removeEventListener("hashchange", follow);
  }, [id, refresh]);

  const open = (p: string) => {
    setPage(p);
    window.history.pushState(null, "", `#${p}`);
    refresh();
  };

  const remove = async () => {
    try {
      await api.deleteSaJob(id);
      toast.success("Return deleted", { description: `${job?.person_name} ${job?.tax_year}` });
      router.push("/");
    } catch (e: any) {
      toast.error("Return not deleted", { description: e.message });
    }
  };

  if (error) return <p className="text-sm text-rose-600">{error}</p>;
  if (!job) return <div className="skeleton h-40 rounded-2xl" />;

  const sections = view?.sections || [];
  const groups: { label: string; items: Item[] }[] = [
    { label: "", items: [{ id: "overview", label: "Overview", icon: LayoutDashboard }] },
    { label: "Prepare", items: [
      { id: "documents", label: "Documents", icon: SECTION_ICONS.documents, state: view?.documents.state,
        amount: view ? String(view.documents.count) : undefined },
      { id: "last-year", label: "Last year", icon: History },
      { id: "details", label: "Client details", icon: UserRound },
    ] },
    { label: "Income", items: sections.map((s): Item => ({ id: s.id, label: s.label, icon: SECTION_ICONS[s.id], state: s.state,
                                                       amount: s.state === "empty" ? "none" : money(s.amount).replace(/\.\d\d/, ""),
                                                       soon: s.id in SOON }))
                                     // Capital gains is always open: a sale can turn up in any year (R-SA108-01: asked every year)
                                     .concat(sections.some((s) => s.id === "foreign") ? [] : [{ id: "foreign", label: "Foreign income", icon: SECTION_ICONS.foreign || Globe }])
                                     .concat(sections.some((s) => s.id === "capital_gains") ? [] : [{ id: "capital_gains", label: "Capital gains", icon: SECTION_ICONS.capital_gains || TrendingUp }])
                                     .concat([{ id: "family", label: "Family and loans", icon: Users }]) },
    { label: "Review", items: [
      { id: "points", label: "All points", icon: ListChecks, soon: true },
      { id: "queries", label: "Queries", icon: MessageSquareMore,
        state: view?.queries ? (view.queries.blocks || view.queries.client || view.queries.decisions ? "look" : "done") : undefined,
        amount: view?.queries ? (view.queries.blocks ? `${view.queries.blocks} block${view.queries.blocks > 1 ? "s" : ""}`
                                 : String(view.queries.client + view.queries.decisions)) : undefined },
    ] },
    { label: "Finish", items: [
      { id: "tax", label: "Tax calculation", icon: Calculator },
      { id: "boxes", label: "TaxCalc figures", icon: ClipboardList },
      { id: "pack", label: "Working paper pack", icon: FileSpreadsheet },
    ] },
  ];
  const all = groups.flatMap((g) => g.items);
  const current = all.find((p) => p.id === page) || all[0];
  const r = view?.result;

  const body = () => {
    switch (current.id) {
      case "overview": return view ? <SaOverview data={view} open={open} openDoc={setDoc} /> : <div className="skeleton h-64 rounded-2xl" />;
      case "documents": return <SaDocuments jobId={job.id} taxYear={job.tax_year} onChange={refresh} onOpen={setDoc} />;
      case "details": return <Details job={job} onDelete={() => setConfirming(true)} />;
      case "tax": return <SaTaxCalc jobId={job.id} />;
      case "boxes": return <SaBoxes jobId={job.id} onOpenDoc={setDoc} />;
      case "pack": return <SaPack jobId={job.id} onOpen={open} />;
      case "family": return <SaFamily jobId={job.id} onOpen={open} onChange={refresh} />;
      case "capital_gains": return <SaCapitalGains jobId={job.id} onOpen={open} onChange={refresh} />;
      case "foreign": return <SaForeign jobId={job.id} taxYear={job.tax_year} onOpen={open} onChange={refresh} />;
      case "last-year": return <SaLastYear jobId={job.id} />;
      case "queries": return <SaQueries jobId={job.id} onOpen={open} />;
      case "property": return <SaPropertyPage jobId={job.id} taxYear={job.tax_year} onChange={refresh} />;
      case "self_employment": return <SaTradePage jobId={job.id} onChange={refresh} />;
      default:
        return current.soon ? <NotYet id={current.id} title={current.label} /> : PAGES[current.id.toUpperCase()]
          ? <SaIncomePage jobId={job.id} source={current.id.toUpperCase()} company={job.company?.name} onChange={refresh} onOpenDoc={setDoc} />
          : <NotYet id={current.id} title={current.label} />;
    }
  };

  // Where the return stands, for the top of the checklist (as a company's "0 of 5 done")
  const tracked = all.filter((i) => i.state && !i.soon && i.id !== "reliefs");
  const doneCount = tracked.filter((i) => i.state === "done").length;
  const nextItem = view?.look[0];
  const pill = (i: Item) => {
    if (i.soon) return { text: "Soon", tone: "bg-slate-100 text-slate-400" };
    if (i.id === "documents" && view) {
      return view.documents.look ? { text: `${view.documents.look} to check`, tone: PILL.look }
        : view.documents.count ? { text: "Done", tone: PILL.done } : { text: "None yet", tone: PILL.empty };
    }
    const p = i.state ? statePill(i.state) : null;
    return p ? { text: p.text, tone: PILL[p.tone] } : null;
  };
  const identity = (
    <div className="space-y-2">
      <Link href="/" className="inline-flex items-center gap-1 text-xs text-slate-500 hover:text-teal-700">
        <ArrowLeft className="w-3.5 h-3.5" /> Clients
      </Link>
      <div>
        <p className="text-base font-semibold leading-snug text-slate-900">{job.person_name}</p>
        <p className={text.meta}>
          Self Assessment {job.tax_year} · {job.first_return ? "First return with us" : "Returning client"}
          {job.company && <> · Director of <Link href={`/clients/${job.company.engagement_id}`} className="text-teal-700 hover:underline">{job.company.name}</Link></>}
        </p>
      </div>
      {tracked.length > 0 && (
        <div>
          <p className="text-xs font-semibold text-slate-700">{doneCount} of {tracked.length} done</p>
          <div className="mt-1 h-1.5 rounded-full bg-slate-100 overflow-hidden">
            <div className="h-full rounded-full bg-teal-600 transition-all" style={{ width: `${(doneCount / tracked.length) * 100}%` }} />
          </div>
        </div>
      )}
      {nextItem && (
        <div className="rounded-xl border border-slate-200 bg-slate-50 p-3">
          <p className="text-xs text-slate-700"><span className="font-semibold">Next:</span> {nextItem.text}</p>
          <button type="button" onClick={() => (nextItem.doc_id ? setDoc(nextItem.doc_id) : open(nextItem.page))}
                  className="mt-2 w-full rounded-lg border border-slate-300 bg-white px-3 py-1.5 text-xs font-semibold text-slate-700 hover:border-teal-400 hover:text-teal-800 cursor-pointer">
            Open
          </button>
        </div>
      )}
    </div>
  );

  return (
    <div className="space-y-4">
      <div className={cn("grid grid-cols-1 gap-4 lg:gap-5", sideOn ? "lg:grid-cols-[14.5rem_minmax(0,1fr)]" : "lg:grid-cols-[3rem_minmax(0,1fr)]")}>
        <aside aria-label="Return checklist">
          <nav className={cn("no-scrollbar sticky top-20 max-h-[calc(100vh-6rem)] overflow-y-auto space-y-4 rounded-xl border border-slate-200 bg-white p-3 shadow-sm",
                             sideOn ? "hidden lg:block" : "hidden")}>
            <button type="button" onClick={() => setSideOn(false)} title="Fold the checklist (more room)" aria-label="Fold the checklist"
                    className="float-right -mr-1 -mt-1 rounded-md p-1 text-slate-400 transition hover:bg-slate-100 hover:text-slate-700">
              <PanelLeftClose className="h-3.5 w-3.5" />
            </button>
            {identity}
            {groups.map((g, gi) => g.items.length > 0 && (
              <div key={gi}>
                {g.label && <p className={cn("px-2 pb-1", text.label)}>{g.label}</p>}
                <ul className="space-y-0.5">
                  {g.items.map((it) => {
                    const { id: pid, label, icon: Icon, amount, soon } = it;
                    const p = pid === "overview" || pid === "details" || pid === "tax" ? null : pill(it);
                    return (
                      <li key={pid}>
                        <button type="button" onClick={() => open(pid)} aria-current={current.id === pid ? "page" : undefined}
                                title={amount && amount !== "none" ? `${label}: ${amount}` : label}
                                className={cn("flex w-full items-center gap-2 rounded-lg px-2 py-1.5 text-left text-xs font-semibold transition",
                                  current.id === pid ? "bg-teal-50 text-teal-800 ring-1 ring-teal-200"
                                    : soon ? "text-slate-400 hover:bg-slate-50" : "text-slate-600 hover:bg-slate-50 hover:text-slate-900")}>
                          <Icon className="h-3.5 w-3.5 shrink-0" />
                          <span className="flex-1 truncate">{label}</span>
                          {p && (
                            <span className={cn("shrink-0 whitespace-nowrap rounded-full px-1.5 py-px text-[10px] font-bold", p.tone)}>
                              {p.text === "Done" ? <CheckCircle2 className="inline h-3 w-3 -mt-px" aria-hidden="true" /> : null} {p.text}
                            </span>
                          )}
                        </button>
                      </li>
                    );
                  })}
                </ul>
              </div>
            ))}
          </nav>
          {/* Folded: a rail of icons, each with its state as a dot */}
          <nav className={cn("no-scrollbar sticky top-20 max-h-[calc(100vh-6rem)] overflow-y-auto flex-col items-center gap-1 rounded-xl border border-slate-200 bg-white py-2 shadow-sm",
                             sideOn ? "hidden" : "hidden lg:flex")}>
            <button type="button" onClick={() => setSideOn(true)} title="Open the checklist" aria-label="Open the checklist"
                    className="mb-1 rounded-md p-2 text-slate-400 transition hover:bg-slate-100 hover:text-slate-700">
              <PanelLeftOpen className="h-4 w-4" />
            </button>
            {groups.map((g, gi) => g.items.length > 0 && (
              <div key={gi} className={cn("flex flex-col items-center gap-1", gi > 0 && "border-t border-slate-100 pt-1")}>
                {g.items.map(({ id: pid, label, icon: Icon, state, amount }) => (
                  <button key={pid} type="button" onClick={() => open(pid)} aria-label={label} aria-current={current.id === pid ? "page" : undefined}
                          title={amount ? `${label}: ${amount}` : label}
                          className={cn("relative rounded-lg p-2 transition",
                            current.id === pid ? "bg-teal-50 text-teal-800 ring-1 ring-teal-200" : "text-slate-500 hover:bg-slate-50 hover:text-slate-900")}>
                    <Icon className="h-4 w-4" />
                    {state && <span className={cn("absolute right-1 top-1 h-1.5 w-1.5 rounded-full", STATE_DOT[state])} />}
                  </button>
                ))}
              </div>
            ))}
          </nav>
          <div className="lg:hidden mb-3 rounded-xl border border-slate-200 bg-white p-3 shadow-sm">{identity}</div>
          <div className="lg:hidden no-scrollbar flex gap-1.5 overflow-x-auto pb-1">
            {all.map(({ id: pid, label, icon: Icon, state }) => (
              <button key={pid} type="button" onClick={() => open(pid)}
                      className={cn("flex shrink-0 items-center gap-1.5 rounded-full border px-3 py-1 text-xs font-semibold",
                        current.id === pid ? "border-teal-300 bg-teal-50 text-teal-800" : "border-slate-200 bg-white text-slate-600")}>
                <Icon className="h-3.5 w-3.5" /> {label}
                {state && <span className={cn("h-1.5 w-1.5 rounded-full", STATE_DOT[state])} />}
              </button>
            ))}
          </div>
        </aside>

        <main key={ver} className="min-w-0 space-y-4">{body()}</main>
      </div>

      <SaDocViewer jobId={job.id} docId={doc} onClose={() => setDoc(null)} onSaved={() => { refresh(); setVer((v) => v + 1); }} />
      <ConfirmDialog
        isOpen={confirming}
        onClose={() => setConfirming(false)}
        onConfirm={remove}
        title={`Delete ${job.person_name}'s ${job.tax_year} return?`}
        description="The return, its documents and what was read from them are removed."
        confirmText="Delete"
      />
    </div>
  );
}
