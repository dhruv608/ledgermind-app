"use client";

import { useState } from "react";
import { Loader2 } from "lucide-react";
import { toast } from "@/lib/notify";
import type { CustomPaper, CustomPaperKind } from "@/lib/api";
import { api } from "@/lib/api";
import { Button } from "@/components/ui/button";
import { CustomSelect } from "@/components/ui/custom-select";
import { Modal } from "@/components/ui/dialog";
import { cn } from "@/lib/utils";

/** Add a working paper (Add New Workpaper: name, account, type Detailed / Supporting; Add New Reconciliation:
 * name, then debit and credit details on the paper itself). */
export interface AccountOption { code: number; name: string }
const KINDS: { id: CustomPaperKind; label: string; help: string }[] = [
  { id: "DETAILED", label: "Detailed", help: "A T for an account: opening, the year's lines, journals, closing." },
  { id: "SUPPORTING", label: "Supporting", help: "A note with its documents, for anything the other papers do not show." },
  { id: "RECONCILIATION", label: "Reconciliation", help: "Debit and credit details of your own, and the difference." },
  { id: "LOAN_SCHEDULE", label: "Loan schedule", help: "A loan's instalments, interest and principal, and its split at the year end." },
];
const field = "w-full rounded-md border border-slate-300 bg-white px-2.5 py-1.5 text-xs text-slate-800 focus:outline-none focus:ring-2 focus:ring-teal-200";

export function AddPaperDialog({ engagementId, area, accounts, onClose, onAdded }: {
  engagementId: string;
  area: string;
  accounts: AccountOption[];
  onClose: () => void;
  onAdded: (p: CustomPaper) => void;
}) {
  const [name, setName] = useState("");
  const [kind, setKind] = useState<CustomPaperKind>("DETAILED");
  const [code, setCode] = useState<number | null>(null);
  const [saving, setSaving] = useState(false);
  const options = accounts.map((a) => ({ value: String(a.code), label: `${a.code} ${a.name}` }));

  const save = async () => {
    setSaving(true);
    try {
      onAdded(await api.addCustomPaper(engagementId, { area, kind, name, codes: kind === "DETAILED" && code !== null ? [code] : [] }));
    } catch (e) {
      toast.error((e as Error).message);
    } finally {
      setSaving(false);
    }
  };
  const ready = name.trim() && (kind !== "DETAILED" || code !== null);

  return (
    <Modal isOpen onClose={onClose} title="Add workpaper" description="A paper of your own in this area, kept with the job.">
      <div className="space-y-4">
        <label className="block space-y-1">
          <span className="text-[11px] font-semibold text-slate-600">Name</span>
          <input autoFocus value={name} onChange={(e) => setName(e.target.value)} placeholder="e.g. Director's car loan" className={field} />
        </label>
        <div className="space-y-1">
          <span className="text-[11px] font-semibold text-slate-600">Type</span>
          <div className="grid gap-2 sm:grid-cols-2">
            {KINDS.map((k) => (
              <button key={k.id} type="button" onClick={() => setKind(k.id)}
                      className={cn("rounded-lg border px-3 py-2 text-left transition",
                                    kind === k.id ? "border-teal-500 bg-teal-50/60 ring-1 ring-teal-200" : "border-slate-200 hover:border-slate-300")}>
                <span className="block text-xs font-semibold text-slate-800">{k.label}</span>
                <span className="block text-[11px] leading-snug text-slate-500">{k.help}</span>
              </button>
            ))}
          </div>
        </div>
        {kind === "DETAILED" && (
          <div className="space-y-1">
            <span className="text-[11px] font-semibold text-slate-600">Account</span>
            <CustomSelect fullWidth searchable searchPlaceholder="Type a code or name" placeholder="Pick the account…"
                          value={code === null ? "" : String(code)} options={options} onChange={(v) => setCode(Number(v))} />
          </div>
        )}
        <div className="flex justify-end gap-2 pt-1">
          <Button variant="outline" size="sm" className="h-8 text-xs" onClick={onClose}>Cancel</Button>
          <Button variant="primary" size="sm" className="h-8 text-xs" disabled={!ready || saving} onClick={save}>
            {saving && <Loader2 className="mr-1.5 h-3.5 w-3.5 animate-spin" />} Create
          </Button>
        </div>
      </div>
    </Modal>
  );
}
