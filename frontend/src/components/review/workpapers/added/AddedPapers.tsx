"use client";

import { useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { ChevronRight, FilePlus2, Trash2 } from "lucide-react";
import { toast } from "@/lib/notify";
import type { CustomPaper } from "@/lib/api";
import { api } from "@/lib/api";
import { Button } from "@/components/ui/button";
import { wp } from "@/components/review/area/WorkpaperParts";
import { AddPaperDialog, type AccountOption } from "@/components/review/workpapers/added/AddPaperDialog";
import { CustomPaperView } from "@/components/review/workpapers/added/CustomPaperView";
import { jobKeys, useCustomPapers } from "@/lib/queries/job";
import { cn } from "@/lib/utils";

/**
 * The working papers the accountant added to an area (Add New Workpaper / Add New Reconciliation): a list under the
 * area's own papers, each opening in place.
 */
const { money } = wp;
const KIND_LABEL = { DETAILED: "Detailed", SUPPORTING: "Supporting", RECONCILIATION: "Reconciliation", LOAN_SCHEDULE: "Loan schedule" } as const;

export function AddedPapers({ engagementId, area, accounts, onAttach, yearEnd }: {
  engagementId: string;
  /** The job's year end (yyyy-mm-dd), for a loan schedule's split */
  yearEnd?: string;
  area: string;
  accounts: AccountOption[];
  onAttach: () => void;
}) {
  const qc = useQueryClient();
  const all = useCustomPapers(engagementId).data ?? [];
  const papers = all.filter((p) => p.area === area);
  const [adding, setAdding] = useState(false);
  const [openId, setOpenId] = useState<number | null>(null);
  const refresh = () => qc.invalidateQueries({ queryKey: jobKeys.customPapers(engagementId) });
  const open = papers.find((p) => p.id === openId);

  const remove = async (p: CustomPaper) => {
    if (!window.confirm(`Remove the working paper "${p.name}"?`)) return;
    try {
      await api.deleteCustomPaper(engagementId, p.id);
      if (openId === p.id) setOpenId(null);
      await refresh();
    } catch (e) {
      toast.error((e as Error).message);
    }
  };

  return (
    <div className="overflow-hidden rounded-xl border border-slate-200 bg-white shadow-2xs">
      <div className="flex flex-wrap items-center justify-between gap-2 px-4 py-3">
        <div>
          <h3 className="text-sm font-bold text-slate-900">Added working papers</h3>
          <p className="text-[11px] text-slate-500">
            {papers.length ? "Papers added to this area by hand." : "Add a Detailed T for any account, a supporting note, or a reconciliation of your own."}
          </p>
        </div>
        <Button variant="outline" size="sm" className="h-8 text-xs" onClick={() => setAdding(true)}>
          <FilePlus2 className="mr-1.5 h-3.5 w-3.5" /> Add workpaper
        </Button>
      </div>
      {papers.length > 0 && (
        <ul className="divide-y divide-slate-100 border-t border-slate-100">
          {papers.map((p) => (
            <li key={p.id}>
              <div className={cn("group flex cursor-pointer items-center gap-3 px-4 py-2 text-xs hover:bg-teal-50/40", openId === p.id && "bg-teal-50/40")}
                   onClick={() => setOpenId(openId === p.id ? null : p.id)}>
                <ChevronRight className={cn("h-3.5 w-3.5 text-slate-400 transition", openId === p.id && "rotate-90")} />
                <span className="font-medium text-slate-800">{p.name}</span>
                <span className="rounded-full bg-slate-100 px-1.5 py-px text-[10px] text-slate-500">{KIND_LABEL[p.kind]}</span>
                {p.kind === "RECONCILIATION" && (
                  <span className={cn("ml-auto font-mono text-[11px] tabular-nums", Math.abs(p.difference) >= 0.005 ? "text-rose-700" : "text-emerald-700")}>
                    {Math.abs(p.difference) >= 0.005 ? `Difference ${money(p.difference)}` : "Agrees"}
                  </span>
                )}
                <button type="button" aria-label={`Remove ${p.name}`} onClick={(e) => { e.stopPropagation(); remove(p); }}
                        className={cn("rounded p-1 text-slate-400 opacity-0 transition hover:bg-rose-50 hover:text-rose-600 group-hover:opacity-100", p.kind !== "RECONCILIATION" && "ml-auto")}>
                  <Trash2 className="h-3.5 w-3.5" />
                </button>
              </div>
              {open?.id === p.id && (
                <div className="border-t border-slate-100 bg-slate-50/40 p-4">
                  <CustomPaperView engagementId={engagementId} paper={p} onSaved={refresh} onAttach={onAttach} yearEnd={yearEnd} />
                </div>
              )}
            </li>
          ))}
        </ul>
      )}
      {adding && (
        <AddPaperDialog engagementId={engagementId} area={area} accounts={accounts} onClose={() => setAdding(false)}
                        onAdded={async (p) => { setAdding(false); await refresh(); setOpenId(p.id); }} />
      )}
    </div>
  );
}
