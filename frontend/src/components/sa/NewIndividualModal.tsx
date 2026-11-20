"use client";

// A new Self Assessment return: the person, the tax year and the kinds of income they have (one short screen).
import React, { useMemo, useState } from "react";
import { Modal } from "@/components/ui/dialog";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { CustomSelect } from "@/components/ui/custom-select";
import { api, SaJob, SaSource } from "@/lib/api";
import { ClientListItem } from "@/types/engagement";

export const SOURCE_LABELS: Record<SaSource, string> = {
  EMPLOYMENT: "Employment",
  SELF_EMPLOYMENT: "Self-employment",
  PROPERTY: "Property",
  SAVINGS: "Savings interest",
  DIVIDENDS: "Dividends / director",
  PENSIONS: "Pensions and benefits",
  FOREIGN: "Foreign income",
  CAPITAL_GAINS: "Capital gains",
};
const TAX_YEARS = ["2025-26", "2024-25"];

interface NewIndividualModalProps {
  isOpen: boolean;
  onClose: () => void;
  onBack: () => void;
  companies: ClientListItem[];
  onCreated: (job: SaJob) => void;
}

export function NewIndividualModal({ isOpen, onClose, onBack, companies, onCreated }: NewIndividualModalProps) {
  const [name, setName] = useState("");
  const [taxYear, setTaxYear] = useState(TAX_YEARS[0]);
  const [sources, setSources] = useState<SaSource[]>([]);
  const [firstReturn, setFirstReturn] = useState(false);
  const [company, setCompany] = useState("");
  const [utr, setUtr] = useState("");
  const [ni, setNi] = useState("");
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");

  // One entry per company (its latest year), for "director of"
  const companyOptions = useMemo(() => {
    const latest = new Map<string, ClientListItem>();
    for (const c of companies) {
      const seen = latest.get(c.client_name);
      if (!seen || String(c.period_end_date) > String(seen.period_end_date)) latest.set(c.client_name, c);
    }
    return [{ value: "", label: "Not a director of a client" },
            ...[...latest.values()].sort((a, b) => a.client_name.localeCompare(b.client_name))
              .map((c) => ({ value: c.engagement_id, label: c.client_name }))];
  }, [companies]);

  const toggle = (s: SaSource) =>
    setSources((prev) => (prev.includes(s) ? prev.filter((x) => x !== s) : [...prev, s]));

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!name.trim()) return setError("Enter the person's name.");
    if (!sources.length) return setError("Tick at least one kind of income.");
    setSaving(true);
    setError("");
    try {
      const job = await api.createSaJob({
        person_name: name.trim(), tax_year: taxYear, sources, first_return: firstReturn,
        company_engagement_id: company || undefined, utr: utr.trim() || undefined, ni_number: ni.trim() || undefined,
      });
      onCreated(job);
    } catch (err: any) {
      setError(err.message || "Could not create the return.");
    } finally {
      setSaving(false);
    }
  };

  return (
    <Modal isOpen={isOpen} onClose={onClose} title="New Self Assessment return"
           description="Who it is for, the tax year and the kinds of income they have. Documents come next.">
      <form onSubmit={submit} className="space-y-5 pt-4">
        <div className="grid grid-cols-1 sm:grid-cols-[1fr_9rem] gap-3">
          <label className="space-y-1">
            <span className="text-xs font-semibold text-slate-700">Name</span>
            <Input value={name} onChange={(e) => setName(e.target.value)} placeholder="e.g. Maria Smith" autoFocus />
          </label>
          <div className="space-y-1">
            <span className="text-xs font-semibold text-slate-700">Tax year</span>
            <CustomSelect value={taxYear} onChange={setTaxYear} fullWidth
                          options={TAX_YEARS.map((y) => ({ value: y, label: y }))} />
          </div>
        </div>

        <fieldset className="space-y-2">
          <legend className="text-xs font-semibold text-slate-700">Kinds of income</legend>
          <div className="grid grid-cols-2 sm:grid-cols-4 gap-2">
            {(Object.keys(SOURCE_LABELS) as SaSource[]).map((s) => {
              const on = sources.includes(s);
              return (
                <label key={s}
                       className={`flex items-center gap-2 rounded-lg border px-2.5 py-2 text-xs cursor-pointer transition-colors ${
                         on ? "border-teal-400 bg-teal-50 text-teal-900" : "border-slate-200 text-slate-700 hover:border-slate-300"}`}>
                  <input type="checkbox" checked={on} onChange={() => toggle(s)} className="accent-teal-600" />
                  {SOURCE_LABELS[s]}
                </label>
              );
            })}
          </div>
        </fieldset>

        <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
          <div className="space-y-1">
            <span className="text-xs font-semibold text-slate-700">Last year</span>
            <CustomSelect value={firstReturn ? "first" : "returning"} onChange={(v) => setFirstReturn(v === "first")}
                          fullWidth options={[
                            { value: "returning", label: "Returning client (we did last year's return)" },
                            { value: "first", label: "First return with us" },
                          ]} />
          </div>
          <div className="space-y-1">
            <span className="text-xs font-semibold text-slate-700">Director of</span>
            <CustomSelect value={company} onChange={setCompany} fullWidth searchable options={companyOptions} />
          </div>
        </div>

        <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
          <label className="space-y-1">
            <span className="text-xs font-semibold text-slate-700">UTR <span className="font-normal text-slate-400">(optional)</span></span>
            <Input value={utr} onChange={(e) => setUtr(e.target.value)} placeholder="10 digits" autoComplete="off"
                   inputMode="numeric" />
          </label>
          <label className="space-y-1">
            <span className="text-xs font-semibold text-slate-700">NI number <span className="font-normal text-slate-400">(optional)</span></span>
            <Input value={ni} onChange={(e) => setNi(e.target.value)} placeholder="QQ123456C" autoComplete="off" />
          </label>
        </div>
        <p className="text-[11px] text-slate-400 -mt-2">Once saved, the UTR and NI number show only their last 3 characters.</p>

        {error && <p className="text-xs text-rose-600">{error}</p>}

        <div className="flex items-center justify-between pt-2 border-t border-slate-100">
          <Button type="button" variant="ghost" size="sm" onClick={onBack}>Back</Button>
          <Button type="submit" variant="primary" disabled={saving}>{saving ? "Creating..." : "Create return"}</Button>
        </div>
      </form>
    </Modal>
  );
}
