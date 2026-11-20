"use client";

import React from "react";
import { Check, ChevronDown, Loader2, Plus, Sparkles, X } from "lucide-react";
import { CustomSelect } from "@/components/ui/custom-select";
import { cn } from "@/lib/utils";

/** The Engagement Setup record part this screen edits (profile.setup): {client: {...}, vat: {...}, ...}. */
export type SetupData = Record<string, Record<string, any>>;
export type SetSetup = (part: string, key: string, value: any) => void;

export const inputClass =
  "w-full rounded-lg border border-slate-300 bg-white px-3 py-1.5 text-xs text-slate-800 focus:outline-none focus:ring-2 focus:ring-teal-200";

export function Field({ label, hint, children, className }: { label: string; hint?: React.ReactNode; children: React.ReactNode; className?: string }) {
  return (
    <label className={cn("block", className)}>
      <span className="mb-1 block text-[11px] font-bold text-slate-700">{label}</span>
      {children}
      {hint && <span className="mt-0.5 block text-[11px] text-slate-400">{hint}</span>}
    </label>
  );
}

/** Yes / No with a third state: not answered yet (a blank never switches a check off). */
export function YesNo({ value, onChange }: { value: boolean | null | undefined; onChange: (v: boolean | null) => void }) {
  const opt = (v: boolean, text: string) => (
    <button
      type="button"
      onClick={() => onChange(value === v ? null : v)}
      className={cn(
        "rounded-md px-3 py-1 text-[11px] font-semibold transition",
        value === v ? (v ? "bg-emerald-600 text-white" : "bg-slate-700 text-white") : "text-slate-600 hover:bg-slate-100"
      )}
    >
      {text}
    </button>
  );
  return (
    <span className="inline-flex rounded-lg border border-slate-200 bg-white p-0.5">
      {opt(true, "Yes")}
      {opt(false, "No")}
    </span>
  );
}

/** Tick-box chips for a multi-select. */
export function Chips({ options, value, onChange }: { options: string[]; value: string[]; onChange: (v: string[]) => void }) {
  return (
    <div className="flex flex-wrap gap-1.5">
      {options.map((o) => {
        const on = value.includes(o);
        return (
          <button
            key={o}
            type="button"
            onClick={() => onChange(on ? value.filter((x) => x !== o) : [...value, o])}
            className={cn(
              "inline-flex items-center gap-1 rounded-full border px-2.5 py-1 text-[11px] font-medium transition",
              on ? "border-teal-300 bg-teal-50 text-teal-800" : "border-slate-200 bg-white text-slate-600 hover:border-slate-300"
            )}
          >
            {on && <Check className="h-3 w-3" />}
            {o}
          </button>
        );
      })}
    </div>
  );
}

/** What the data suggests for an open answer, with a button to use it. Once used it says so until the part is saved. */
export function Suggestion({ text, reason, onUse, used }: { text: string; reason: string; onUse?: () => void; used?: boolean }) {
  if (used) {
    return (
      <div className="mt-1.5 flex flex-wrap items-center gap-1.5 rounded-md bg-emerald-50 px-2 py-1 text-[11px] text-emerald-800">
        <Check className="h-3 w-3 shrink-0" />
        <span>Using the suggestion: <strong>{text}</strong>. Save this part to confirm it.</span>
      </div>
    );
  }
  return (
    <div className="mt-1.5 flex flex-wrap items-center gap-1.5 rounded-md bg-teal-50 px-2 py-1 text-[11px] text-teal-900">
      <Sparkles className="h-3 w-3 shrink-0 text-teal-600" />
      <span>
        Suggested: <strong>{text}</strong> <span className="text-teal-800/80">({reason})</span>
      </span>
      {onUse && (
        <button type="button" onClick={onUse} className="ml-auto rounded bg-white px-2 py-0.5 font-semibold text-teal-800 hover:bg-teal-100">
          Use
        </button>
      )}
    </div>
  );
}

// An input's value: blank instead of null / undefined
const orBlank = (v: any) => (v === null || v === undefined || v === "" ? "" : v);
const toNum = (s: string) => (s === "" ? null : Number(s));

// ---------------------------------------------------------------------------------------------------------------
// Step 1 Client: period, size test, accounts type, last year's data
// ---------------------------------------------------------------------------------------------------------------
export function ClientStep({ setup, set, record }: { setup: SetupData; set: SetSetup; record: Record<string, any> | null }) {
  const c = setup.client || {};
  const r = record?.client || {};
  const period = c.period || r.period || {};
  return (
    <div className="space-y-4">
      <div className="grid gap-3 sm:grid-cols-3">
        <Field label="Company number" hint="From Companies House once looked up (People step)">
          <input value={c.company_number ?? ""} placeholder={r.company_number || "8 characters"} maxLength={8}
                 onChange={(e) => set("client", "company_number", e.target.value.toUpperCase() || null)} className={inputClass} />
        </Field>
        <Field label="Period start" hint="Defaults to the year end minus 12 months plus 1 day">
          <input type="date" value={period.start || ""} onChange={(e) => set("client", "period", { ...period, start: e.target.value })} className={inputClass} />
        </Field>
        <Field label="Period end">
          <input type="date" value={period.end || ""} onChange={(e) => set("client", "period", { ...period, end: e.target.value })} className={inputClass} />
        </Field>
      </div>

      <div>
        <p className="mb-1 text-[11px] font-bold text-slate-700">Size test (turnover, balance sheet total, average employees)</p>
        <div className="grid gap-3 sm:grid-cols-3">
          <input type="number" value={orBlank(c.turnover)} placeholder={r.turnover != null ? `${Math.round(r.turnover)} (from the TB)` : "Turnover £"}
                 onChange={(e) => set("client", "turnover", toNum(e.target.value))} className={inputClass} />
          <input type="number" value={orBlank(c.balance_sheet_total)} placeholder={r.balance_sheet_total != null ? `${Math.round(r.balance_sheet_total)} (from the TB)` : "Balance sheet total £"}
                 onChange={(e) => set("client", "balance_sheet_total", toNum(e.target.value))} className={inputClass} />
          <input type="number" value={orBlank(c.employees)} placeholder={r.employees != null ? `${r.employees} (payroll report)` : "Average employees"}
                 onChange={(e) => set("client", "employees", toNum(e.target.value))} className={inputClass} />
        </div>
        <p className="mt-1 text-[11px] text-slate-500">
          Size indication: <strong className="text-slate-800">{r.size || "not enough figures yet"}</strong>
          {r.size && " (one year only; the legal test needs two consecutive years)"}. Blank boxes use the figures from the books.
        </p>
      </div>

      <div className="grid gap-3 sm:grid-cols-3">
        <Field label="Accounts type">
          <CustomSelect fullWidth value={c.accounts_type || ""} placeholder="Choose" onChange={(v) => set("client", "accounts_type", v)}
                        options={[{ value: "STATUTORY", label: "Statutory" }, { value: "MANAGEMENT", label: "Management" }, { value: "TAX_ONLY", label: "Tax only" }]} />
        </Field>
        <Field label="Last year's accounts available">
          <YesNo value={c.prior_year_accounts} onChange={(v) => set("client", "prior_year_accounts", v)} />
        </Field>
        <Field label="Last year's TB / ledger available">
          <YesNo value={c.prior_year_tb_gl} onChange={(v) => set("client", "prior_year_tb_gl", v)} />
        </Field>
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------------------------------------------
// Step 3 Tax: VAT, PAYE and CIS details, 75% group, R&D
// ---------------------------------------------------------------------------------------------------------------
export const VAT_FEATURES = ["Exempt income", "Option to tax", "VAT group", "Construction reverse charge", "Imports",
  "Overseas customers or suppliers", "Property or asset over the CGS limit"];
export const PAYROLL_FEATURES = ["Pension", "Directors on payroll", "Benefits", "Employment Allowance", "Off-payroll contractors"];

export function TaxDetails({ setup, set, vat, payroll, cis }: { setup: SetupData; set: SetSetup; vat: boolean; payroll: boolean; cis: string }) {
  const v = setup.vat || {}, p = setup.payroll || {}, c = setup.cis || {}, ct = setup.ct || {};
  return (
    <div className="space-y-4">
      {vat && (
        <div className="space-y-3 rounded-xl border border-slate-200 p-3">
          <p className="text-xs font-bold text-slate-800">VAT details</p>
          <div className="grid gap-3 sm:grid-cols-4">
            <Field label="VAT number"><input value={v.number ?? ""} onChange={(e) => set("vat", "number", e.target.value || null)} className={inputClass} /></Field>
            <Field label="Registered on"><input type="date" value={v.registration_date ?? ""} onChange={(e) => set("vat", "registration_date", e.target.value || null)} className={inputClass} /></Field>
            <Field label="Returns">
              <CustomSelect fullWidth value={v.frequency || ""} placeholder="Choose" onChange={(x) => set("vat", "frequency", x)}
                            options={[{ value: "QUARTERLY", label: "Quarterly" }, { value: "MONTHLY", label: "Monthly" }, { value: "ANNUAL", label: "Annual" }]} />
            </Field>
            <Field label="Quarters end">
              <CustomSelect fullWidth value={v.quarter_pattern || ""} placeholder="Choose" onChange={(x) => set("vat", "quarter_pattern", x)}
                            options={[{ value: "MAR", label: "Mar / Jun / Sep / Dec" }, { value: "APR", label: "Apr / Jul / Oct / Jan" }, { value: "MAY", label: "May / Aug / Nov / Feb" }]} />
            </Field>
          </div>
          <Field label="Special features"><Chips options={VAT_FEATURES} value={v.features || []} onChange={(x) => set("vat", "features", x)} /></Field>
        </div>
      )}
      {payroll && (
        <div className="space-y-3 rounded-xl border border-slate-200 p-3">
          <p className="text-xs font-bold text-slate-800">PAYE details</p>
          <div className="grid gap-3 sm:grid-cols-3">
            <Field label="PAYE reference"><input value={p.reference ?? ""} onChange={(e) => set("payroll", "reference", e.target.value || null)} className={inputClass} /></Field>
            <Field label="Pay frequency">
              <CustomSelect fullWidth value={p.frequency || ""} placeholder="Choose" onChange={(x) => set("payroll", "frequency", x)}
                            options={[{ value: "MONTHLY", label: "Monthly" }, { value: "WEEKLY", label: "Weekly" }, { value: "FORTNIGHTLY", label: "Fortnightly" }, { value: "FOUR_WEEKLY", label: "Four-weekly" }]} />
            </Field>
            <Field label="Employment allowance claimed?" hint="Through the payroll this year. No: flagged for the client to claim">
              <CustomSelect fullWidth value={p.allowance_claimed || ""} placeholder="Not sure" onChange={(x) => set("payroll", "allowance_claimed", x || null)}
                            options={[{ value: "YES", label: "Yes" }, { value: "NO", label: "No" }, { value: "", label: "Not sure" }]} />
            </Field>
          </div>
          <Field label="Payroll features"><Chips options={PAYROLL_FEATURES} value={p.features || []} onChange={(x) => set("payroll", "features", x)} /></Field>
        </div>
      )}
      {cis !== "NONE" && (
        <div className="space-y-3 rounded-xl border border-slate-200 p-3">
          <p className="text-xs font-bold text-slate-800">CIS details <span className="font-normal text-slate-500">(needed for the CIS working)</span></p>
          <div className="grid gap-3 sm:grid-cols-3">
            <Field label="UTR"><input value={c.utr ?? ""} onChange={(e) => set("cis", "utr", e.target.value || null)} className={inputClass} placeholder="10 digits" /></Field>
            <Field label="Registered for CIS"><YesNo value={c.registered} onChange={(x) => set("cis", "registered", x)} /></Field>
            <Field label="PAYE / CIS scheme reference" hint="The company's PAYE scheme: CIS is paid and reclaimed through it">
              <input value={c.scheme_reference ?? ""} onChange={(e) => set("cis", "scheme_reference", e.target.value || null)} className={inputClass} placeholder="123/AB45678" />
            </Field>
            <Field label="Gross payment status"><YesNo value={c.gross_payment_status} onChange={(x) => set("cis", "gross_payment_status", x)} /></Field>
            {c.gross_payment_status === true && (
              <Field label="Gross payment status from"><input type="date" value={c.gross_payment_from ?? ""} onChange={(e) => set("cis", "gross_payment_from", e.target.value || null)} className={inputClass} /></Field>
            )}
            {(cis === "CONTRACTOR" || cis === "BOTH") && (
              <Field label="Active subcontractors">
                <input type="number" value={orBlank(c.subcontractors)} onChange={(e) => set("cis", "subcontractors", toNum(e.target.value))} className={inputClass} />
              </Field>
            )}
          </div>
          <div className="grid gap-3 sm:grid-cols-2">
            {(cis === "SUBCONTRACTOR" || cis === "BOTH") && (
              <Field label="CIS on sales invoices unpaid at the year start £" hint="From last year's CIS working: received this year, so it counts this year">
                <input type="number" value={orBlank(c.opening_unpaid_suffered)} onChange={(e) => set("cis", "opening_unpaid_suffered", toNum(e.target.value))} className={inputClass} />
              </Field>
            )}
            {(cis === "CONTRACTOR" || cis === "BOTH") && (
              <Field label="CIS on bills unpaid at the year start £" hint="From last year's CIS working: paid this year, so it counts this year">
                <input type="number" value={orBlank(c.opening_unpaid_deducted)} onChange={(e) => set("cis", "opening_unpaid_deducted", toNum(e.target.value))} className={inputClass} />
              </Field>
            )}
          </div>
        </div>
      )}
      <div className="grid gap-3 sm:grid-cols-2">
        <Field label="Part of a 75% group"><YesNo value={ct.group_75} onChange={(x) => set("ct", "group_75", x)} /></Field>
        <Field label="R&D claim expected"><YesNo value={ct.rd_expected} onChange={(x) => set("ct", "rd_expected", x)} /></Field>
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------------------------------------------
// Step 4 Policies: thresholds, stock and revenue policy, depreciation per asset class
// ---------------------------------------------------------------------------------------------------------------
export const ASSET_CLASSES = ["Freehold property", "Leasehold property", "Plant and machinery", "Motor vehicles", "Fixtures and fittings", "Computers"];

export function PoliciesStep({ setup, set, capitalisation, onCapitalisation }: { setup: SetupData; set: SetSetup; capitalisation: number; onCapitalisation: (v: number) => void }) {
  const p = setup.policies || {};
  const dep: Record<string, { method?: string; rate?: number | null }> = p.depreciation || {};
  // The firm's default per class (used when the client's is blank), shown in the empty fields
  const firm: Record<string, { method?: string; rate?: number | null }> = p.depreciation_default || {};
  const METHOD_NAME: Record<string, string> = { STRAIGHT_LINE: "Straight line", REDUCING_BALANCE: "Reducing balance", NONE: "Not depreciated" };
  const setDep = (cls: string, changes: Record<string, any>) => {
    const next = { ...dep, [cls]: { ...(dep[cls] || {}), ...changes } };
    if (!next[cls].method && (next[cls].rate === null || next[cls].rate === undefined)) delete next[cls];
    set("policies", "depreciation", next);
  };
  return (
    <div className="space-y-4">
      <div className="grid gap-3 sm:grid-cols-3">
        <Field label="Capitalisation limit (£)" hint="Firm policy (default £500)">
          <input type="number" value={capitalisation} onChange={(e) => onCapitalisation(parseFloat(e.target.value) || 0)} className={inputClass} />
        </Field>
        <Field label="Prepayment threshold (£)" hint="Blank: firm default">
          <input type="number" value={orBlank(p.prepayment_threshold)} onChange={(e) => set("policies", "prepayment_threshold", toNum(e.target.value))} className={inputClass} />
        </Field>
        <Field label="Accrual threshold (£)" hint="Blank: firm default">
          <input type="number" value={orBlank(p.accrual_threshold)} onChange={(e) => set("policies", "accrual_threshold", toNum(e.target.value))} className={inputClass} />
        </Field>
      </div>
      <div className="grid gap-3 sm:grid-cols-3">
        <Field label="Closing stock at the year end (£)" hint="From the stock count; 0 if none">
          <input type="number" value={orBlank(p.closing_stock)} onChange={(e) => set("policies", "closing_stock", toNum(e.target.value))} className={inputClass} />
        </Field>
        <Field label="Stock valuation">
          <CustomSelect fullWidth value={p.stock_method || ""} placeholder="Choose" onChange={(x) => set("policies", "stock_method", x)}
                        options={[{ value: "FIFO", label: "First in, first out" }, { value: "AVERAGE", label: "Weighted average" }, { value: "STANDARD", label: "Standard cost" }, { value: "NONE", label: "No stock" }]} />
        </Field>
        <Field label="Revenue recognition">
          <CustomSelect fullWidth value={p.revenue_policy || ""} placeholder="Choose" onChange={(x) => set("policies", "revenue_policy", x)}
                        options={[{ value: "POINT_OF_SALE", label: "At the point of sale" }, { value: "ON_DELIVERY", label: "On delivery / completion" },
                                  { value: "OVER_TIME", label: "Over time (stage of completion)" }, { value: "SUBSCRIPTION", label: "Over the subscription period" }]} />
        </Field>
      </div>
      <div className="grid gap-3 sm:grid-cols-2">
        <Field label="Depreciation on this year's additions" hint="Used with the fixed asset register">
          <CustomSelect fullWidth value={p.additions_from || "FULL_YEAR"} onChange={(x) => set("policies", "additions_from", x)}
                        options={[{ value: "FULL_YEAR", label: "A full year's charge (firm default)" }, { value: "PURCHASE_MONTH", label: "From the month of purchase" },
                                  { value: "NEXT_MONTH", label: "From the month after purchase" }]} />
        </Field>
      </div>
      <div>
        <p className="mb-1 text-[11px] font-bold text-slate-700">Depreciation per asset class (blank: firm default)</p>
        <div className="space-y-1.5">
          {ASSET_CLASSES.map((cls) => (
            <div key={cls} className="grid grid-cols-12 items-center gap-2">
              <span className="col-span-5 text-xs text-slate-700">{cls}</span>
              <div className="col-span-4">
                <CustomSelect fullWidth size="sm" value={dep[cls]?.method || ""} placeholder={firm[cls]?.method ? `Firm: ${METHOD_NAME[firm[cls].method!] || firm[cls].method}` : "Method"} onChange={(x) => setDep(cls, { method: x })}
                              options={[{ value: "STRAIGHT_LINE", label: "Straight line" }, { value: "REDUCING_BALANCE", label: "Reducing balance" }, { value: "NONE", label: "Not depreciated" }]} />
              </div>
              <input type="number" value={orBlank(dep[cls]?.rate)} placeholder={firm[cls]?.rate ? `Firm: ${firm[cls].rate}%` : "Rate %"} onChange={(e) => setDep(cls, { rate: toNum(e.target.value) })}
                     className={cn(inputClass, "col-span-3")} />
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------------------------------------------
// Step 5 People: each director's details, other shareholders, related companies
// ---------------------------------------------------------------------------------------------------------------
export function PeopleDetails({ setup, set, directors, roleOf }: { setup: SetupData; set: SetSetup; directors: string[]; roleOf: (n: string) => string | undefined }) {
  const people = setup.people || {};
  const details: Record<string, any> = people.director_details || {};
  const setDetail = (name: string, key: string, value: any) =>
    set("people", "director_details", { ...details, [name]: { ...(details[name] || {}), [key]: value } });
  const holders: { name?: string; shares?: number | null; class?: string; connected_to?: string }[] = people.shareholders || [];
  const setHolders = (next: typeof holders) => set("people", "shareholders", next);
  return (
    <div className="space-y-4">
      {directors.length > 0 && (
        <div className="overflow-x-auto rounded-xl border border-slate-200">
          <table className="w-full min-w-[520px] text-xs">
            <thead className="bg-slate-50 text-[11px] uppercase tracking-wide text-slate-500">
              <tr>
                <th className="px-3 py-2 text-left font-semibold">Director / shareholder</th>
                <th className="px-2 py-2 text-left font-semibold">Shares %</th>
                <th className="px-2 py-2 text-left font-semibold">Loan account</th>
                <th className="px-2 py-2 text-left font-semibold">On payroll</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-100">
              {directors.map((n) => (
                <tr key={n}>
                  <td className="px-3 py-2">
                    <span className="font-medium text-slate-800">{n}</span>
                    {roleOf(n) && <span className="block text-[11px] text-slate-400">{roleOf(n)}</span>}
                  </td>
                  <td className="px-2 py-2">
                    <input type="number" value={orBlank(details[n]?.shares)} onChange={(e) => setDetail(n, "shares", toNum(e.target.value))} className={cn(inputClass, "w-20")} />
                  </td>
                  <td className="px-2 py-2"><YesNo value={details[n]?.dla} onChange={(v) => setDetail(n, "dla", v)} /></td>
                  <td className="px-2 py-2"><YesNo value={details[n]?.on_payroll} onChange={(v) => setDetail(n, "on_payroll", v)} /></td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      <div>
        <div className="mb-1 flex items-center justify-between">
          <span className="text-[11px] font-bold text-slate-700">Other shareholders (not directors)</span>
          <button type="button" onClick={() => setHolders([...holders, {}])} className="inline-flex items-center gap-1 text-[11px] font-medium text-teal-800 hover:underline">
            <Plus className="h-3 w-3" /> Add
          </button>
        </div>
        {holders.length === 0 ? (
          <p className="text-[11px] italic text-slate-400">None added.</p>
        ) : (
          <div className="space-y-1.5">
            {holders.map((h, i) => (
              <div key={i} className="grid grid-cols-12 gap-1.5">
                <input value={h.name ?? ""} placeholder="Name" onChange={(e) => setHolders(holders.map((x, j) => (j === i ? { ...x, name: e.target.value } : x)))} className={cn(inputClass, "col-span-4")} />
                <input type="number" value={orBlank(h.shares)} placeholder="Shares %" onChange={(e) => setHolders(holders.map((x, j) => (j === i ? { ...x, shares: toNum(e.target.value) } : x)))} className={cn(inputClass, "col-span-2")} />
                <input value={h.class ?? ""} placeholder="Share class" onChange={(e) => setHolders(holders.map((x, j) => (j === i ? { ...x, class: e.target.value } : x)))} className={cn(inputClass, "col-span-2")} />
                <input value={h.connected_to ?? ""} placeholder="Connected to (e.g. director's spouse)" onChange={(e) => setHolders(holders.map((x, j) => (j === i ? { ...x, connected_to: e.target.value } : x)))} className={cn(inputClass, "col-span-3")} />
                <button type="button" onClick={() => setHolders(holders.filter((_, j) => j !== i))} className="col-span-1 justify-self-center text-slate-400 hover:text-rose-600" title="Remove">
                  <X className="h-3.5 w-3.5" />
                </button>
              </div>
            ))}
          </div>
        )}
      </div>

      <Field label="Related or connected companies (one per line)" hint="Searched in the ledger by the related party check">
        <textarea rows={3} value={(people.related_companies || []).join("\n")}
                  onChange={(e) => set("people", "related_companies", e.target.value.split("\n").map((x) => x.trim()).filter(Boolean))}
                  className={inputClass} />
      </Field>
    </div>
  );
}

// ---------------------------------------------------------------------------------------------------------------
// Step 6 Materiality: benchmark x % = overall; performance 75% and trivial 5% of it (both can be overwritten)
// ---------------------------------------------------------------------------------------------------------------
export function MaterialityStep({ setup, set, record, suggestion, onOverall }:
  { setup: SetupData; set: SetSetup; record: Record<string, any> | null; suggestion?: { value: any; reason: string }; onOverall: (v: number) => void }) {
  const m = setup.materiality || {};
  const c = record?.client || {};
  const base: Record<string, number | undefined> = { TURNOVER: c.turnover, GROSS_ASSETS: c.balance_sheet_total };
  const recompute = (benchmark: string, pct: number | null) => {
    const b = base[benchmark];
    if (b && pct) {
      const overall = Math.round(b * pct) / 100;
      set("materiality", "overall", overall);
      set("materiality", "performance", Math.round(overall * 75) / 100);
      set("materiality", "trivial", Math.round(overall * 5) / 100);
      onOverall(overall);
    }
  };
  return (
    <div className="space-y-4">
      <div className="grid gap-3 sm:grid-cols-3">
        <Field label="Benchmark">
          <CustomSelect fullWidth value={m.benchmark || ""} placeholder="Choose"
                        onChange={(x) => { set("materiality", "benchmark", x); recompute(x, m.pct ?? null); }}
                        options={[{ value: "TURNOVER", label: "Turnover" }, { value: "PROFIT", label: "Profit before tax" },
                                  { value: "GROSS_ASSETS", label: "Gross assets" }, { value: "EXPENSES", label: "Total expenses" }]} />
        </Field>
        <Field label="Benchmark %">
          <input type="number" step="0.1" value={orBlank(m.pct)} onChange={(e) => { const v = toNum(e.target.value); set("materiality", "pct", v); recompute(m.benchmark, v); }} className={inputClass} />
        </Field>
        <Field label="Overall materiality (£)" hint="Required">
          <input type="number" value={orBlank(m.overall)} onChange={(e) => { const v = toNum(e.target.value); set("materiality", "overall", v);
            if (v) { set("materiality", "performance", Math.round(v * 75) / 100); set("materiality", "trivial", Math.round(v * 5) / 100); onOverall(v); } }}
                 className={inputClass} />
        </Field>
      </div>
      <div className="grid gap-3 sm:grid-cols-2">
        <Field label="Performance materiality (£)" hint="75% of overall unless changed">
          <input type="number" value={orBlank(m.performance)} onChange={(e) => set("materiality", "performance", toNum(e.target.value))} className={inputClass} />
        </Field>
        <Field label="Clearly trivial (£)" hint="5% of overall: findings below this are logged, not sent to the client">
          <input type="number" value={orBlank(m.trivial)} onChange={(e) => set("materiality", "trivial", toNum(e.target.value))} className={inputClass} />
        </Field>
      </div>
      {suggestion && !m.overall && (
        <Suggestion
          text={`£${Number(suggestion.value.overall).toLocaleString("en-GB")}`}
          reason={suggestion.reason}
          onUse={() => {
            set("materiality", "benchmark", "TURNOVER");
            set("materiality", "pct", suggestion.value.pct * 100);
            set("materiality", "overall", suggestion.value.overall);
            set("materiality", "performance", suggestion.value.performance);
            set("materiality", "trivial", suggestion.value.trivial);
            onOverall(suggestion.value.overall);
          }}
        />
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------------------------------------------
// Step 7 Prior year: issues to retest, notes
// ---------------------------------------------------------------------------------------------------------------
export function PriorYearStep({ setup, set, issues }: { setup: SetupData; set: SetSetup; issues: { label: string; rules: string }[] }) {
  const p = setup.prior_year || {};
  return (
    <div className="space-y-4">
      <Field label="Issues last year (each ticked issue is retested this year)">
        <Chips options={issues.map((i) => i.label)} value={p.issues || []} onChange={(x) => set("prior_year", "issues", x)} />
      </Field>
      <Field label="Notes">
        <textarea rows={4} value={p.notes ?? ""} onChange={(e) => set("prior_year", "notes", e.target.value)} className={inputClass} />
      </Field>
    </div>
  );
}

// ---------------------------------------------------------------------------------------------------------------
// Industry: business models and the industry's questions (data from the firm's catalogue, each naming its query)
// ---------------------------------------------------------------------------------------------------------------
export interface IndustryQuestion {
  id: string;
  label: string;
  type: "yn" | "number" | "text" | "chips";
  options?: string[];
  rules: string;
}
export interface IndustryEntry {
  name: string;
  models: string[];
  questions: IndustryQuestion[];
}

export function IndustryQuestions({ setup, set, industry, evidence }: {
  setup: SetupData; set: SetSetup; industry?: IndustryEntry;
  /** What the books suggest for open questions: {question id: {value 'Y'/'N', reason}} */
  evidence?: Record<string, { value: string; reason: string }>;
}) {
  if (!industry) return null;
  const ind = setup.industry || {};
  const answers: Record<string, any> = ind.answers || {};
  const answer = (id: string, v: any) => set("industry", "answers", { ...answers, [id]: v });
  return (
    <div className="space-y-4">
      <Field label="Business model (tick all that apply)">
        <Chips options={industry.models} value={ind.models || []} onChange={(x) => set("industry", "models", x)} />
      </Field>
      <div>
        <p className="mb-2 text-[11px] font-bold text-slate-700">{industry.name} questions</p>
        <div className="grid gap-3 sm:grid-cols-2">
          {industry.questions.map((q) => (
            <div key={q.id} className={cn("rounded-lg border border-slate-200 p-2.5", q.type === "chips" && "sm:col-span-2")}>
              <p className="mb-1.5 text-xs font-medium text-slate-800">{q.label}</p>
              {q.type === "yn" && (
                <YesNo value={answers[q.id] === "Y" ? true : answers[q.id] === "N" ? false : null}
                       onChange={(v) => answer(q.id, v === null ? null : v ? "Y" : "N")} />
              )}
              {q.type === "number" && (
                <input type="number" min={0} value={answers[q.id] ?? ""} onChange={(e) => answer(q.id, e.target.value === "" ? null : Number(e.target.value))} className={inputClass} />
              )}
              {q.type === "text" && <input value={answers[q.id] ?? ""} onChange={(e) => answer(q.id, e.target.value || null)} className={inputClass} />}
              {q.type === "chips" && <Chips options={q.options || []} value={answers[q.id] || []} onChange={(x) => answer(q.id, x)} />}
              {evidence?.[q.id] && (answers[q.id] === undefined || answers[q.id] === null) && (
                <Suggestion text={evidence[q.id].value === "Y" ? "Yes" : "No"} reason={evidence[q.id].reason}
                            onUse={() => answer(q.id, evidence[q.id].value)} />
              )}
              <p className="mt-1 font-mono text-[11px] text-emerald-700">→ {q.rules}</p>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}

/** One part of the single-page setup: a numbered heading, one line on what it decides, and its fields. */
export type SectionState = "saved" | "todo" | "unsaved" | "optional" | "carried";

const SECTION_STATE: Record<SectionState, { label: string; className: string }> = {
  saved: { label: "Saved", className: "border-emerald-200 bg-emerald-50 text-emerald-700" },
  todo: { label: "Needs an answer", className: "border-rose-200 bg-rose-50 text-rose-700" },
  unsaved: { label: "Unsaved", className: "border-amber-200 bg-amber-50 text-amber-800" },
  optional: { label: "Optional", className: "border-slate-200 bg-slate-50 text-slate-500" },
  carried: { label: "From last year · check", className: "border-sky-200 bg-sky-50 text-sky-700" },
};

/** One part of the setup: a header that opens and closes it (with its state and a one-line summary), and its own
 *  Save / Discard so each part is saved on its own. */
export function SetupSection({
  id, number, title, lead, open, onToggle, state, summary, onSave, onDiscard, saving, children,
}: {
  id: string; number: number; title: string; lead: string; open: boolean; onToggle: () => void; state: SectionState;
  summary?: string; onSave: () => void; onDiscard: () => void; saving: boolean; children: React.ReactNode;
}) {
  const s = SECTION_STATE[state];
  return (
    <section id={id} className={cn("scroll-mt-28 rounded-xl border bg-white transition", open ? "border-teal-200 shadow-sm ring-1 ring-teal-100" : "border-slate-200")}>
      <button type="button" onClick={onToggle} aria-expanded={open}
              className="flex w-full items-center gap-3 rounded-xl px-4 py-3 text-left hover:bg-slate-50/70">
        <span className={cn("flex h-6 w-6 shrink-0 items-center justify-center rounded-full text-[11px] font-semibold",
                            state === "saved" ? "bg-emerald-600 text-white" : state === "optional" ? "bg-slate-200 text-slate-600" : "bg-teal-700 text-white")}>
          {state === "saved" ? <Check className="h-3.5 w-3.5" /> : number}
        </span>
        <span className="min-w-0 flex-1">
          <span className="block text-sm font-semibold text-slate-900">{title}</span>
          {!open && summary && <span className="block truncate text-[11px] text-slate-500">{summary}</span>}
        </span>
        <span className={cn("shrink-0 rounded-full border px-2 py-0.5 text-[11px] font-medium", s.className)}>{s.label}</span>
        <ChevronDown className={cn("h-4 w-4 shrink-0 text-slate-400 transition-transform", open && "rotate-180")} />
      </button>
      {open && (
        <div className="px-4 pb-4 pt-1">
          <p className="mb-4 text-[11px] text-slate-500">{lead}</p>
          {children}
          <div className="mt-5 flex items-center justify-end gap-2">
            <button type="button" onClick={onDiscard} disabled={state !== "unsaved"}
                    className="rounded-md px-2.5 py-1.5 text-xs text-slate-600 hover:bg-slate-100 disabled:opacity-40">
              Discard
            </button>
            <button type="button" onClick={onSave} disabled={(state !== "unsaved" && state !== "carried") || saving}
                    className="inline-flex items-center gap-1.5 rounded-md bg-teal-700 px-3 py-1.5 text-xs font-semibold text-white shadow-xs hover:bg-teal-800 disabled:bg-slate-200 disabled:text-slate-500">
              {saving ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Check className="h-3.5 w-3.5" />}
              {state === "carried" ? "Confirm" : "Save"} {title.toLowerCase()}
            </button>
          </div>
        </div>
      )}
    </section>
  );
}
