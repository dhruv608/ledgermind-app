"use client";

import { useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { Loader2 } from "lucide-react";
import { toast } from "@/lib/notify";
import type { StatementLine } from "@/lib/api";
import { api } from "@/lib/api";
import { CustomSelect } from "@/components/ui/custom-select";
import { jobKeys, useProposedJournals } from "@/lib/queries/job";
import { cn } from "@/lib/utils";

/**
 * The action on a statement line that is not in the books (DLA, Move to cash ...): post it to the director's loan,
 * cash in hand or any account, as a journal proposed against the bank account. The line then shows its journal; it
 * is approved or rejected on the Journals step like any other.
 */
const DLA = 5400;
const CASH = 4830;
type ChartCode = { std_code: number; std_name: string; category?: string; financial_class?: string; is_extended?: boolean };
const tag = (l: StatementLine) => `[${l.id}]`;

export function UnrecordedAction({ engagementId, bankCode, line }: { engagementId: string; bankCode: number; line: StatementLine }) {
  const qc = useQueryClient();
  const journals = useProposedJournals(engagementId).data ?? [];
  const chart = useQuery({ queryKey: ["chart"], queryFn: () => api.getMasterCOA() as Promise<ChartCode[]>, staleTime: Infinity });
  const [saving, setSaving] = useState(false);
  const posted = journals.find((j) => j.status !== "REJECTED" && j.description.includes(tag(line)));
  if (posted) {
    return (
      <span className={cn("rounded-full px-1.5 py-px text-[10px] font-semibold", posted.status === "APPROVED" ? "bg-emerald-50 text-emerald-700" : "bg-sky-50 text-sky-700")}>
        {posted.journal_ref} {posted.status === "APPROVED" ? "approved" : "to decide"}
      </span>
    );
  }
  const options = [
    { value: String(DLA), label: "Director's loan", group: "Usual" },
    { value: String(CASH), label: "Move to cash in hand", group: "Usual" },
    ...(chart.data || []).filter((c) => !c.is_extended && c.std_code !== bankCode)
      .map((c) => ({ value: String(c.std_code), label: `${String(c.std_code).padStart(4, "0")} ${c.std_name}`, description: c.category, group: "Firm chart" })),
  ];
  const post = async (value: string) => {
    const code = Number(value);
    const amount = Math.abs(line.amount);
    // Money in: Dr bank, Cr the account; money out: Dr the account, Cr bank
    const into = line.amount > 0;
    setSaving(true);
    try {
      const j = await api.createManualJournal(engagementId, `Bank line ${line.date ?? ""} ${line.description}`.slice(0, 220) + ` ${tag(line)}`, [
        { account_code: into ? bankCode : code, debit: amount, credit: 0, narrative: line.description.slice(0, 100) },
        { account_code: into ? code : bankCode, debit: 0, credit: amount, narrative: line.description.slice(0, 100) },
      ]);
      toast.success(`Journal ${j.journal_ref} proposed`, { description: "Approve it on the Journals step." });
      await qc.invalidateQueries({ queryKey: jobKeys.journals(engagementId) });
    } catch (e) {
      toast.error((e as Error).message);
    } finally {
      setSaving(false);
    }
  };
  if (saving) return <Loader2 className="h-3.5 w-3.5 animate-spin text-slate-400" />;
  return (
    <CustomSelect size="sm" searchable searchPlaceholder="Type a code or name" placeholder="Post to…" align="right"
                  value="" options={options} onChange={(v) => post(String(v))} buttonClassName="h-6 text-[11px]" />
  );
}
