"use client";

import { useEffect, useState } from "react";
import { toast } from "@/lib/notify";
import { ArrowRight, Check, ChevronDown, ChevronRight, RefreshCw, X } from "lucide-react";
import { api } from "@/lib/api";
import type { Reanalysis, ReanalysisGroup } from "@/lib/api";
import { Button } from "@/components/ui/button";
import { SkeletonRows } from "@/components/common/SkeletonRows";
import { cn } from "@/lib/utils";
import { formatCurrency } from "@/lib/formatters";

interface ReanalysisPanelProps {
  engagementId: string;
  /** After a decision: the journals, statuses and counts change */
  onChanged: () => void;
  onLoaded?: (r: Reanalysis) => void;
}

const money = (n: number) => formatCurrency(n);
const BAND: Record<string, string> = {
  High: "bg-emerald-50 text-emerald-700",
  Medium: "bg-sky-100 text-sky-800",
  Low: "bg-slate-100 text-slate-600",
};
const OUTCOME: Record<string, string> = {
  propose: "Move",
  journal: "Journal",
  "accountant query": "Ask the accountant",
  "client query": "Ask the client",
};

/** Costs in the wrong place: one row per merchant moved from one code to another, with the reason and how sure
 * the app is. Approving posts the journal and teaches the app this client's choice. */
export function ReanalysisPanel({ engagementId, onChanged, onLoaded }: ReanalysisPanelProps) {
  const [data, setData] = useState<Reanalysis | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [openKey, setOpenKey] = useState<string | null>(null);
  const [busy, setBusy] = useState<string | null>(null);

  const fetchData = () =>
    api.getReanalysis(engagementId)
      .then((r) => {
        setData(r);
        onLoaded?.(r);
      })
      .catch((e) => setError(e.message));
  const load = () => {
    setError(null);
    fetchData();
  };
  // Another job: clear the old error at once (during render); the effect below loads
  const [loadedFor, setLoadedFor] = useState(engagementId);
  if (engagementId !== loadedFor) {
    setLoadedFor(engagementId);
    setError(null);
  }
  useEffect(() => {
    fetchData();
    // eslint-disable-next-line react-hooks/exhaustive-deps -- loads once per job: fetchData (and the parent's onLoaded) is recreated each render
  }, [engagementId]);

  const decide = async (g: ReanalysisGroup, action: "APPROVE" | "REJECT") => {
    setBusy(g.key);
    try {
      await api.decideReanalysis(engagementId, g.key, action);
      toast.success(action === "APPROVE" ? `${g.merchant} moved to ${g.to_name}` : `${g.merchant} left on ${g.from_name}`, {
        description: action === "APPROVE" ? "Journal posted. The app will remember this for the client." : "The app will not suggest this again for the client.",
      });
      load();
      onChanged();
    } catch (e: any) {
      toast.error("Could not save the decision", { description: e.message });
    } finally {
      setBusy(null);
    }
  };

  if (error) {
    return (
      <div className="rounded-xl border border-rose-200 bg-white p-4 text-xs text-rose-700">
        {error} <button className="ml-2 underline" onClick={load}>Try again</button>
      </div>
    );
  }
  if (!data) {
    return (
      <div className="overflow-hidden rounded-xl border border-slate-200 bg-white">
        <SkeletonRows rows={5} columns={4} label="Reading the ledger" />
      </div>
    );
  }

  const open = data.groups.filter((g) => !g.decision);
  const moves = open.filter((g) => g.outcome === "propose" || g.outcome === "journal");
  const questions = open.filter((g) => g.outcome === "accountant query" || g.outcome === "client query");
  const decided = data.groups.filter((g) => g.decision);

  const row = (g: ReanalysisGroup) => {
    const expanded = openKey === g.key;
    return (
      <li key={g.key} className="rounded-lg border border-slate-200 bg-white">
        <div className="flex flex-wrap items-center gap-2 px-3 py-2.5">
          <button type="button" onClick={() => setOpenKey(expanded ? null : g.key)} className="flex min-w-0 flex-1 items-start gap-2 text-left" aria-expanded={expanded}>
            {expanded ? <ChevronDown className="mt-0.5 h-3.5 w-3.5 shrink-0 text-slate-400" /> : <ChevronRight className="mt-0.5 h-3.5 w-3.5 shrink-0 text-slate-400" />}
            <span className="min-w-0">
              <span className="block text-xs font-semibold text-slate-800">
                {g.merchant} <span className="font-normal text-slate-500">· {g.lines.length} line{g.lines.length === 1 ? "" : "s"}</span>
              </span>
              <span className="mt-0.5 flex flex-wrap items-center gap-1 text-[11px] text-slate-500">
                {g.from_code} {g.from_name} <ArrowRight className="h-3 w-3" /> <span className="font-medium text-slate-700">{g.to_code} {g.to_name}</span>
                <span className="text-slate-300">·</span> {g.reason} {g.reason_text}
              </span>
            </span>
          </button>
          <span className="shrink-0 text-xs font-medium tabular-nums text-slate-700">{money(g.total)}</span>
          <span className={cn("shrink-0 rounded-full px-1.5 py-px text-[10px] font-bold", BAND[g.band])}>
            {g.band} {Math.round(g.confidence * 100)}%
          </span>
          {g.decision ? (
            <span className={cn("shrink-0 rounded-full px-2 py-0.5 text-[10.5px] font-bold",
              g.decision === "APPROVED" ? "bg-emerald-50 text-emerald-700" : "bg-slate-100 text-slate-600")}>
              {g.decision === "APPROVED" ? "Moved" : "Left as posted"}
            </span>
          ) : (
            <span className="flex shrink-0 gap-1">
              <Button variant="outline" size="sm" className="h-7 px-2 text-xs" disabled={busy === g.key} onClick={() => decide(g, "REJECT")}>
                <X className="mr-1 h-3.5 w-3.5" /> Leave
              </Button>
              <Button variant="primary" size="sm" className="h-7 px-2 text-xs" disabled={busy === g.key} onClick={() => decide(g, "APPROVE")}>
                <Check className="mr-1 h-3.5 w-3.5" /> Move
              </Button>
            </span>
          )}
        </div>
        {expanded && (
          <div className="border-t border-slate-100 px-3 py-2.5">
            <p className="mb-2 text-[11px] text-slate-500">
              {OUTCOME[g.outcome] || g.outcome}. Why: client history {g.evidence.C ?? 0}, firm history {g.evidence.F ?? 0},
              account card {g.evidence.D ?? 0}, type of merchant {g.evidence.X ?? 0}.
            </p>
            <table className="w-full text-[11px]">
              <tbody>
                {g.lines.map((l, i) => (
                  <tr key={i} className="border-t border-slate-50">
                    <td className="py-1 pr-2 text-slate-500">{l.date}</td>
                    <td className="py-1 pr-2 text-slate-700">{l.description || l.account}</td>
                    <td className="py-1 text-right tabular-nums text-slate-700">{money(l.amount)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </li>
    );
  };

  return (
    <div className="space-y-4">
      <div className="flex items-start justify-between gap-3 rounded-xl border border-slate-200 bg-white px-4 py-3 shadow-2xs">
        <div className="min-w-0 flex-1">
          <h2 className="text-sm font-bold text-slate-900">Re-analysis</h2>
          <p className="mt-0.5 text-xs text-slate-500">
            Costs that look to be in the wrong place. {data.summary.lines_read} cost lines read: {moves.length} move{moves.length === 1 ? "" : "s"} ready,{" "}
            {questions.length} question{questions.length === 1 ? "" : "s"}, {data.summary.unclear_lines} line{data.summary.unclear_lines === 1 ? "" : "s"} too unclear to say.
          </p>
        </div>
        <Button variant="outline" size="sm" className="h-8 w-8 p-0" onClick={load}
                title="Work the moves out again (after a change elsewhere)" aria-label="Work the moves out again">
          <RefreshCw className="h-3.5 w-3.5" />
        </Button>
      </div>

      {moves.length > 0 && (
        <section>
          <h3 className="mb-2 text-xs font-bold uppercase tracking-wide text-slate-400">Moves ready</h3>
          <ul className="space-y-1.5">{moves.map(row)}</ul>
        </section>
      )}
      {questions.length > 0 && (
        <section>
          <h3 className="mb-2 text-xs font-bold uppercase tracking-wide text-slate-400">Questions</h3>
          <ul className="space-y-1.5">{questions.map(row)}</ul>
        </section>
      )}
      {open.length === 0 && (
        <p className="rounded-xl border border-emerald-100 bg-emerald-50/60 px-4 py-3 text-xs text-emerald-800">
          Nothing looks out of place.
        </p>
      )}
      {decided.length > 0 && (
        <section>
          <h3 className="mb-2 text-xs font-bold uppercase tracking-wide text-slate-400">Decided</h3>
          <ul className="space-y-1.5 opacity-80">{decided.map(row)}</ul>
        </section>
      )}
    </div>
  );
}
