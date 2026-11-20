"use client";

import { useEffect, useState } from "react";
import { toast } from "@/lib/notify";
import { Check, Circle, Landmark, Loader2, Plus, X } from "lucide-react";
import { api } from "@/lib/api";
import type { ClientProfile, SetupStatus } from "@/types/engagement";
import { UK_INDUSTRIES } from "@/lib/badges";
import { Modal } from "@/components/ui/dialog";
import { Button } from "@/components/ui/button";
import { CustomSelect } from "@/components/ui/custom-select";
import { cn } from "@/lib/utils";

/** Where an answer came from: the accountant's own answer, read from the files, or a guess to check */
type Origin = "saved" | "files" | "guess" | null;
type Answer<T> = { value: T; origin: Origin; reason?: string };
/** What the upload read, shown beside the questions */
export type ReadFromFiles = { files: number; accounts: number; lines: number };

const FRAMEWORKS = [
  { value: "FRS102_1A", label: "FRS 102 1A" },
  { value: "FRS105", label: "FRS 105" },
  { value: "FULL_FRS102", label: "Full FRS 102" },
];
const CIS = [
  { value: "NONE", label: "Not in CIS" },
  { value: "CONTRACTOR", label: "Contractor" },
  { value: "SUBCONTRACTOR", label: "Subcontractor" },
  { value: "BOTH", label: "Both" },
];
// Why each question is asked, in one line under it
const WHY: Record<string, string> = {
  "Accounts framework": "Decides the accounts layout and which disclosure checks apply.",
  "Industry": "Turns on the checks for this kind of business.",
  "VAT registered": "Turns the VAT checks on or off.",
  "Runs a payroll (PAYE)": "Turns the PAYE, pension and net wages checks on or off.",
  "In the Construction Industry Scheme": "Turns on the CIS deduction checks.",
  "Directors": "Searched in the ledger for the loan account, salary and dividends.",
  "Materiality": "Differences below this are not raised as points.",
  "Director works from home": "Paid back through the director's loan (HMRC's flat rate is £312 a year).",
  "Director's salary outside payroll": "Booked to directors' salaries and the director's loan.",
  "Dividends declared, not in the books": "From the board minutes or vouchers: booked to dividends and the director's loan.",
  "Rent received": "A letting business is taxed on the rent less its costs; part of the trade stays in the trading profit.",
};
const RENT = [
  { value: "LETTING", label: "Letting business" },
  { value: "TRADE", label: "Part of the trade" },
];
const longDate = (iso?: string) => (iso ? new Date(iso).toLocaleDateString("en-GB", { day: "numeric", month: "long", year: "numeric" }) : "");
const count = (n: number) => n.toLocaleString("en-GB");

/** The few answers the checks need, on one screen in three groups, each filled in from what is saved or what the files
 * suggest and marked so. Asked straight after an upload, before the client opens, and again from the client's left
 * list; every answer stays on the Client details tab for changing later. Saving starts the checks when nothing needed
 * is missing. onDone(saved): the questions are finished (saved) or put off (not saved). */
export function ClientQuestionsForm({ engagementId, clientName, read, onDone }: {
  engagementId: string;
  clientName: string;
  read?: ReadFromFiles;
  onDone: (saved: boolean, profile?: ClientProfile) => void;
}) {
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [periodEnd, setPeriodEnd] = useState<string | undefined>();
  const [cisAsked, setCisAsked] = useState(false);
  const [framework, setFramework] = useState<Answer<string>>({ value: "FRS102_1A", origin: null });
  const [industry, setIndustry] = useState<Answer<string>>({ value: "", origin: null });
  const [vat, setVat] = useState<Answer<boolean | null>>({ value: null, origin: null });
  const [payroll, setPayroll] = useState<Answer<boolean | null>>({ value: null, origin: null });
  const [cis, setCis] = useState<Answer<string>>({ value: "NONE", origin: null });
  const [directors, setDirectors] = useState<Answer<string[]>>({ value: [], origin: null });
  const [materiality, setMateriality] = useState<Answer<number | null>>({ value: null, origin: null });
  const [newDirector, setNewDirector] = useState("");
  const [lookingUp, setLookingUp] = useState(false);
  const [lookedUp, setLookedUp] = useState(false);
  // The director's use of home and salary outside the payroll: yes with an amount, no, or not answered (null)
  const [setupRaw, setSetupRaw] = useState<Record<string, any>>({});
  const [home, setHome] = useState<{ yes: boolean | null; amount: number | null }>({ yes: null, amount: null });
  const [salary, setSalary] = useState<{ yes: boolean | null; amount: number | null }>({ yes: null, amount: null });
  // Dividends declared in the year that the books do not hold (the board minutes / vouchers): yes with the total, no
  const [dividends, setDividends] = useState<{ yes: boolean | null; amount: number | null }>({ yes: null, amount: null });
  // Rent in the books: a letting business (with its costs, when there are other sales too) or part of the trade
  const [rent, setRent] = useState<{ amount: number; basis: string | null; costs: number | null }>({ amount: 0, basis: null, costs: null });

  // Another client: loading again until its answers are read
  const [prevEngagementId, setPrevEngagementId] = useState(engagementId);
  if (engagementId !== prevEngagementId) {
    setPrevEngagementId(engagementId);
    setLoading(true);
  }

  // Each answer: the saved one, else what the files suggest (a figure read is 'from the files', a judgement a guess)
  const fill = (profile: ClientProfile, status: SetupStatus) => {
    const confirmed = new Set(profile.confirmed_fields || []);
    const sug = status.suggestions || {};
    const record = status.record || {};
    const pick = <T,>(field: string, saved: T, read = false): Answer<T> =>
      confirmed.has(field) ? { value: saved, origin: "saved" }
        : sug[field] ? { value: sug[field].value as T, origin: read ? "files" : "guess", reason: sug[field].reason }
        : { value: saved, origin: null };
    setPeriodEnd(record.client?.period?.end);
    setFramework(pick("accounting_framework", profile.accounting_framework || "FRS102_1A", true));
    setIndustry(pick("industry_code", confirmed.has("industry_code") ? profile.industry_code : ""));
    setVat(pick<boolean | null>("is_vat_registered", confirmed.has("is_vat_registered") ? Boolean(profile.is_vat_registered) : null));
    setPayroll(pick<boolean | null>("has_payroll", confirmed.has("has_payroll") ? Boolean(profile.has_payroll) : null));
    setCisAsked(Boolean(record.cis?.module?.on));
    setCis(pick("cis_status", profile.cis_status || "NONE"));
    setDirectors({ value: profile.directors || [], origin: (profile.directors || []).length ? "saved" : null });
    const overall = record.materiality?.overall;
    const raw = ((profile as any).setup || {}) as Record<string, any>;
    setSetupRaw(raw);
    const said = (v: unknown) => (typeof v === "number" ? { yes: v > 0, amount: v > 0 ? v : null } : { yes: null, amount: null });
    setHome(said(raw.people?.use_of_home));
    setSalary(said(raw.people?.director_salary));
    setDividends(said(raw.people?.dividends_declared));
    setRent({ amount: Number(record.ct?.rent || 0), basis: raw.ct?.rent_basis ?? null,
              costs: typeof raw.ct?.property_costs === "number" ? raw.ct.property_costs : null });
    setMateriality(overall ? { value: Number(overall), origin: "saved" }
      : sug.materiality ? { value: Math.round(Number(sug.materiality.value?.overall)), origin: "files", reason: sug.materiality.reason }
      : { value: null, origin: null });
  };

  useEffect(() => {
    Promise.all([api.getProfile(engagementId), api.getSetupStatus(engagementId)])
      .then(([profile, status]) => fill(profile, status))
      .catch((e) => toast.error("Could not read the client", { description: e.message }))
      .finally(() => setLoading(false));
  }, [engagementId]);

  const lookUpDirectors = async () => {
    setLookingUp(true);
    setLookedUp(true);
    try {
      const res = await api.lookupCompaniesHouse(engagementId);
      if ("choices" in res) {
        toast.info(res.choices.length ? "More than one company has this name on Companies House" : "No company with this name on Companies House",
                   { description: "Type the directors here, or pick the company on the Client details tab." });
        return;
      }
      setDirectors((prev) => {
        const known = new Set(prev.value.map((d) => d.toLowerCase()));
        const added = res.people.filter((p) => p.kind === "person").map((p) => p.name).filter((n) => !known.has(n.toLowerCase()));
        return { value: [...prev.value, ...added], origin: "files", reason: `Companies House, ${res.company_name}` };
      });
    } catch (e: any) {
      toast.error("Companies House did not answer", { description: e.message });
    } finally {
      setLookingUp(false);
    }
  };
  // With no directors known, Companies House is asked once, as soon as the client's answers are read
  useEffect(() => {
    // eslint-disable-next-line react-hooks/set-state-in-effect -- asks Companies House once loading ends; the request sets its own busy flag
    if (!loading && !directors.value.length && !lookedUp) lookUpDirectors();
    // eslint-disable-next-line react-hooks/exhaustive-deps -- runs when loading ends only: the other values are read at that moment
  }, [loading]);

  const addDirector = () => {
    const name = newDirector.trim();
    if (!name) return;
    if (!directors.value.some((d) => d.toLowerCase() === name.toLowerCase())) {
      setDirectors({ value: [...directors.value, name], origin: directors.origin || "saved", reason: directors.reason });
    }
    setNewDirector("");
  };

  // What each group still needs before the checks can start
  const missing = [
    [!framework.value && "the framework", !industry.value && "the industry"],
    [vat.value === null && "VAT", payroll.value === null && "payroll"],
    [!directors.value.length && "a director", !materiality.value && "materiality"],
  ].map((m) => m.filter(Boolean) as string[]);
  const allMissing = missing.flat();

  const save = async () => {
    setSaving(true);
    try {
      const updated = await api.updateProfile(engagementId, {
        accounting_framework: framework.value,
        industry_code: industry.value,
        is_vat_registered: Boolean(vat.value),
        has_payroll: Boolean(payroll.value),
        ...(cisAsked ? { cis_status: cis.value } : {}),
        directors: directors.value,
        materiality_threshold: materiality.value ?? undefined,
        ...(home.yes !== null || salary.yes !== null || dividends.yes !== null || rent.basis ? {
          setup: {
            ...setupRaw,
            people: {
              ...(setupRaw.people || {}),
              ...(home.yes !== null ? { use_of_home: home.yes ? home.amount || 0 : 0 } : {}),
              ...(salary.yes !== null ? { director_salary: salary.yes ? salary.amount || 0 : 0 } : {}),
              ...(dividends.yes !== null ? { dividends_declared: dividends.yes ? dividends.amount || 0 : 0 } : {}),
            },
            ...(rent.basis ? {
              ct: { ...(setupRaw.ct || {}), rent_basis: rent.basis,
                    property_costs: rent.basis === "LETTING" ? rent.costs : null },
            } : {}),
          },
        } : {}),
      } as Partial<ClientProfile>);
      const status = await api.getSetupStatus(engagementId).catch(() => null);
      if (status?.gaps.length) {
        toast.warning("Saved. A few details are still needed before the checks run", {
          description: `${status.gaps.join("; ")}. Add them on the Client details tab.`,
        });
      } else {
        toast.success("Saved. The checks are running", { description: "Their progress shows in the client's left list." });
      }
      onDone(true, updated);
    } catch (e: any) {
      toast.error("Not saved", { description: e.message });
    } finally {
      setSaving(false);
    }
  };

  const source = (a: { origin: Origin; reason?: string }) =>
    a.origin === "files" ? <p className="text-[11px] text-emerald-700" title={a.reason}>Read from your files{a.reason ? `: ${a.reason}` : ""}</p>
      : a.origin === "guess" ? <p className="text-[11px] text-amber-700" title={a.reason}>Our guess from the ledger, please check{a.reason ? `: ${a.reason}` : ""}</p>
      : null;
  // One question per row: the question on the left, the answer on the right, where it came from beneath
  const row = (question: string, control: React.ReactNode, a?: { origin: Origin; reason?: string }, wide = false) => {
    const note = a ? source(a) : null;
    return (
      <div className={cn("py-2.5", wide ? "space-y-2" : "grid gap-x-6 gap-y-1 sm:grid-cols-[1fr_auto] sm:items-center")}>
        <div>
          <p className="text-[13px] text-slate-800">{question}</p>
          {WHY[question] && <p className="text-[11px] text-slate-500">{WHY[question]}</p>}
        </div>
        <div className={wide ? "" : "sm:justify-self-end"}>{control}</div>
        {note && <div className={wide ? "" : "sm:col-span-2"}>{note}</div>}
      </div>
    );
  };
  const choice = <T extends string | boolean>(options: { value: T; label: string }[], current: T | null, set: (v: T) => void) => (
    <div className="inline-flex flex-wrap gap-1 rounded-lg bg-slate-100 p-1">
      {options.map((o) => (
        <button key={String(o.value)} type="button" onClick={() => set(o.value)} aria-pressed={current === o.value}
                className={cn("rounded-md px-3 py-1 text-xs font-medium transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-teal-300",
                              current === o.value ? "bg-white text-teal-800 shadow-xs ring-1 ring-teal-600/30" : "text-slate-600 hover:text-slate-900")}>
          {o.label}
        </button>
      ))}
    </div>
  );
  const yesNo = [{ value: true, label: "Yes" }, { value: false, label: "No" }];
  const answer = <T,>(set: (a: Answer<T>) => void) => (v: T) => set({ value: v, origin: "saved" });
  // A group of questions under a light heading, ticked once it has every answer it needs
  const group = (title: string, gaps: string[], children: React.ReactNode) => (
    <section className="pt-4 first:pt-0">
      <h4 className="flex items-center gap-2 text-xs font-semibold text-slate-900">
        {gaps.length ? <Circle className="h-3.5 w-3.5 text-slate-300" /> : <Check className="h-3.5 w-3.5 text-teal-700" />} {title}
      </h4>
      <div className="divide-y divide-slate-100 pl-5.5">{children}</div>
    </section>
  );

  return (
    <div className="bg-white">
      {/* The client and what was read at the top, then the questions in three groups */}
      <div className="flex flex-col px-6 pt-5 pb-5">
        <h3 className="pr-8 text-base font-semibold text-slate-900">A few answers before we check the books</h3>
        <p className="mt-1 text-xs text-slate-600">
          <span className="font-medium text-slate-800">{clientName}</span>
          {periodEnd ? `, year ended ${longDate(periodEnd)}.` : "."}
          {read && <> Read {count(read.files)} file{read.files === 1 ? "" : "s"}: {count(read.accounts)} accounts and {count(read.lines)} ledger lines.</>}
        </p>
        <p className="mt-0.5 text-[11px] text-slate-500">Check what we filled in and fix any guess. Everything can be changed later on Client details.</p>
        <div className="mt-5 flex-1">
          {loading ? (
            <div className="flex h-60 items-center gap-2 text-xs text-slate-500">
              <Loader2 className="h-4 w-4 animate-spin" /> Reading the client&apos;s files…
            </div>
          ) : (
            <>
              {group("Company", missing[0], <>
                {row("Accounts framework", choice(FRAMEWORKS, framework.value, answer(setFramework)), framework)}
                {row("Industry",
                  <div className="w-full sm:w-64">
                    <CustomSelect fullWidth searchable searchPlaceholder="Type to search" placeholder="Pick the industry"
                                  value={industry.value} options={UK_INDUSTRIES.map((i) => ({ value: i.code, label: i.name, description: i.desc }))}
                                  onChange={(v) => setIndustry({ value: String(v ?? ""), origin: "saved" })} />
                  </div>, industry)}
              </>)}
              {group("Tax", missing[1], <>
                {row("VAT registered", choice(yesNo, vat.value, answer(setVat)), vat)}
                {row("Runs a payroll (PAYE)", choice(yesNo, payroll.value, answer(setPayroll)), payroll)}
                {cisAsked && row("In the Construction Industry Scheme",
                  <div className="sm:text-right">
                    {choice(CIS, cis.value, answer(setCis))}
                    {cis.value !== "NONE" && <p className="mt-1.5 text-[11px] text-slate-500">The UTR and scheme reference go on the Client details tab.</p>}
                  </div>, cis)}
                {rent.amount >= 1 && row("Rent received",
                  <div className="space-y-1.5 sm:text-right">
                    <p className="text-[11px] text-slate-500">£{rent.amount.toLocaleString("en-GB", { minimumFractionDigits: 2, maximumFractionDigits: 2 })} in the books</p>
                    {choice(RENT, rent.basis, (v) => setRent({ ...rent, basis: v }))}
                    {rent.basis === "LETTING" && (
                      <span className="flex items-center justify-end gap-1">
                        <span className="text-[11px] text-slate-500">Property costs, if there are other sales too £</span>
                        <input type="number" min={0} step="any" value={rent.costs ?? ""} placeholder="split by income"
                               aria-label="Property costs for the year in pounds"
                               onChange={(e) => setRent({ ...rent, costs: e.target.value === "" ? null : parseFloat(e.target.value) })}
                               className="h-8 w-28 rounded-lg border border-slate-300 px-2 text-right text-xs tabular-nums focus:outline-none focus:ring-2 focus:ring-teal-200" />
                      </span>
                    )}
                  </div>)}
              </>)}
              {group("People and size", missing[2], <>
                {row("Directors",
                  <div className="space-y-2">
                    {directors.value.length > 0 && (
                      <ul className="flex flex-wrap gap-1.5">
                        {directors.value.map((d) => (
                          <li key={d} className="inline-flex items-center gap-1 rounded-md border border-slate-200 bg-white py-0.5 pl-2 pr-0.5 text-xs text-slate-800">
                            {d}
                            <button type="button" aria-label={`Remove ${d}`} className="rounded p-0.5 text-slate-400 hover:bg-slate-100 hover:text-slate-700"
                                    onClick={() => setDirectors({ ...directors, value: directors.value.filter((x) => x !== d) })}>
                              <X className="h-3 w-3" />
                            </button>
                          </li>
                        ))}
                      </ul>
                    )}
                    {lookingUp && <p className="inline-flex items-center gap-1.5 text-[11px] text-slate-500"><Loader2 className="h-3 w-3 animate-spin" /> Asking Companies House</p>}
                    <div className="flex flex-wrap gap-2">
                      <input value={newDirector} onChange={(e) => setNewDirector(e.target.value)} placeholder="Type a director's name"
                             onKeyDown={(e) => { if (e.key === "Enter") { e.preventDefault(); addDirector(); } }}
                             className="h-8 min-w-0 flex-1 basis-full rounded-lg border border-slate-300 px-2.5 text-xs focus:outline-none focus:ring-2 focus:ring-teal-200 sm:basis-auto" />
                      <Button type="button" variant="secondary" size="sm" className="h-8 text-xs" onClick={addDirector} disabled={!newDirector.trim()}>
                        <Plus className="mr-1 h-3.5 w-3.5" /> Add
                      </Button>
                      <Button type="button" variant="secondary" size="sm" className="h-8 text-xs" onClick={lookUpDirectors} disabled={lookingUp}>
                        <Landmark className="mr-1 h-3.5 w-3.5" /> Companies House
                      </Button>
                    </div>
                  </div>, directors, true)}
                {row("Director works from home",
                  <div className="flex items-center justify-end gap-2">
                    {choice(yesNo, home.yes, (v) => setHome({ yes: v, amount: v ? home.amount ?? 312 : null }))}
                    {home.yes && (
                      <span className="flex items-center gap-1">
                        <span className="text-xs text-slate-500">£</span>
                        <input type="number" min={0} step="any" value={home.amount ?? ""} aria-label="Use of home for the year in pounds"
                               onChange={(e) => setHome({ yes: true, amount: parseFloat(e.target.value) || null })}
                               className="h-8 w-24 rounded-lg border border-slate-300 px-2 text-right text-xs tabular-nums focus:outline-none focus:ring-2 focus:ring-teal-200" />
                      </span>
                    )}
                  </div>)}
                {row("Director's salary outside payroll",
                  <div className="flex items-center justify-end gap-2">
                    {choice(yesNo, salary.yes, (v) => setSalary({ yes: v, amount: v ? salary.amount : null }))}
                    {salary.yes && (
                      <span className="flex items-center gap-1">
                        <span className="text-xs text-slate-500">£</span>
                        <input type="number" min={0} step="any" value={salary.amount ?? ""} placeholder="12570" aria-label="Director's salary for the year in pounds"
                               onChange={(e) => setSalary({ yes: true, amount: parseFloat(e.target.value) || null })}
                               className="h-8 w-24 rounded-lg border border-slate-300 px-2 text-right text-xs tabular-nums focus:outline-none focus:ring-2 focus:ring-teal-200" />
                      </span>
                    )}
                  </div>)}
                {row("Dividends declared, not in the books",
                  <div className="flex items-center justify-end gap-2">
                    {choice(yesNo, dividends.yes, (v) => setDividends({ yes: v, amount: v ? dividends.amount : null }))}
                    {dividends.yes && (
                      <span className="flex items-center gap-1">
                        <span className="text-xs text-slate-500">£</span>
                        <input type="number" min={0} step="any" value={dividends.amount ?? ""} aria-label="Dividends declared in the year, not in the books, in pounds"
                               onChange={(e) => setDividends({ yes: true, amount: parseFloat(e.target.value) || null })}
                               className="h-8 w-24 rounded-lg border border-slate-300 px-2 text-right text-xs tabular-nums focus:outline-none focus:ring-2 focus:ring-teal-200" />
                      </span>
                    )}
                  </div>)}
                {row("Materiality",
                  <div className="flex items-center gap-1.5">
                    <span className="text-xs text-slate-500">£</span>
                    <input type="number" min={0} step="any" value={materiality.value ?? ""} placeholder="5,000" aria-label="Materiality in pounds"
                           onChange={(e) => setMateriality({ value: parseFloat(e.target.value) || null, origin: "saved" })}
                           className="h-8 w-32 rounded-lg border border-slate-300 px-2.5 text-right text-xs tabular-nums focus:outline-none focus:ring-2 focus:ring-teal-200" />
                  </div>, materiality)}
              </>)}
            </>
          )}
        </div>

        <div className="mt-5 flex flex-wrap items-center justify-between gap-3 border-t border-slate-100 pt-4">
          <button type="button" onClick={() => onDone(false)} className="text-xs text-slate-500 hover:text-slate-800 hover:underline">
            Answer later
          </button>
          <div className="flex items-center gap-3">
            {!loading && allMissing.length > 0 && <span className="text-[11px] text-slate-500">Still needed: {allMissing.join(", ")}</span>}
            <Button type="button" variant="primary" size="sm" className="h-8 px-5 text-xs" disabled={loading || saving || allMissing.length > 0}
                    onClick={save}>
              {saving && <Loader2 className="mr-1 h-3.5 w-3.5 animate-spin" />} Start the checks
            </Button>
          </div>
        </div>
      </div>
    </div>
  );
}

/** The same questions over the client page (from its left list) */
export function ClientQuestions({ engagementId, clientName, open, onClose, onSaved }: {
  engagementId: string;
  clientName: string;
  open: boolean;
  onClose: () => void;
  onSaved: (profile: ClientProfile) => void;
}) {
  return (
    <Modal isOpen={open} onClose={onClose} className="max-w-xl overflow-hidden p-0">
      {open && (
        <ClientQuestionsForm engagementId={engagementId} clientName={clientName}
                             onDone={(saved, profile) => { if (saved && profile) onSaved(profile); onClose(); }} />
      )}
    </Modal>
  );
}
