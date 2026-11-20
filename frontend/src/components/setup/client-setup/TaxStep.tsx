// Setup step 3: VAT, payroll and CIS, their details, and the corporation tax facts not in the books.

import { Receipt, Users, Briefcase } from "lucide-react";
import { CustomSelect } from "@/components/ui/custom-select";
import { TaxInputs } from "@/types/engagement";
import { TaxDetails } from "@/components/setup/SetupFields";
import type { ClientSetupState } from "./useClientSetup";

export function TaxStep({ s }: { s: ClientSetupState }) {
  const {
    profile, pick, setProfile, suggestionFor, setup, setS,
  } = s;
  return (
            <div className="space-y-6">
        {/* Section 2: VAT, payroll, CIS */}
        <div className="grid grid-cols-1 sm:grid-cols-3 gap-3">
          {/* VAT Registration */}
          <div className="p-3 bg-slate-50 border border-slate-200 rounded-xl space-y-2">
            <div className="flex items-center justify-between">
              <span className="flex items-center space-x-1.5 text-xs font-bold text-slate-800">
                <Receipt className="w-3.5 h-3.5 text-slate-500" />
                <span>VAT registered</span>
              </span>
              <input
                type="checkbox"
                checked={Boolean(profile.is_vat_registered)}
                onChange={(e) => pick("is_vat_registered", e.target.checked)}
                className="w-4 h-4 rounded border-slate-300 text-teal-700 focus:ring-teal-600 cursor-pointer"
              />
            </div>
            <p className="text-[11px] text-slate-500">
              Turns on the VAT return checks (each return against the ledger, the VAT account).
            </p>
            {profile.is_vat_registered && (
              <CustomSelect
                fullWidth
                size="sm"
                value={profile.vat_scheme || "STANDARD"}
                onChange={(v) => setProfile((prev) => ({ ...prev, vat_scheme: v }))}
                options={[
                  { value: "STANDARD", label: "Standard, accruals (invoice) basis" },
                  { value: "CASH", label: "Standard, cash accounting scheme" },
                  { value: "FLAT_RATE", label: "Flat rate, accruals basis" },
                  { value: "FLAT_RATE_CASH", label: "Flat rate, cash basis" },
                ]}
              />
            )}
            {suggestionFor("is_vat_registered")}
          </div>

          {/* Payroll & PAYE */}
          <div className="p-3 bg-slate-50 border border-slate-200 rounded-xl space-y-2">
            <div className="flex items-center justify-between">
              <span className="flex items-center space-x-1.5 text-xs font-bold text-slate-800">
                <Users className="w-3.5 h-3.5 text-slate-500" />
                <span>Payroll (PAYE)</span>
              </span>
              <input
                type="checkbox"
                checked={Boolean(profile.has_payroll)}
                onChange={(e) => pick("has_payroll", e.target.checked)}
                className="w-4 h-4 rounded border-slate-300 text-teal-700 focus:ring-teal-600 cursor-pointer"
              />
            </div>
            <p className="text-[11px] text-slate-500">
              The company runs a payroll: turns on the payroll checks. Upload the payroll report on the payroll area&apos;s Evidence tab.
            </p>
            {suggestionFor("has_payroll")}
          </div>

          {/* CIS Scheme */}
          <div className="p-3 bg-slate-50 border border-slate-200 rounded-xl space-y-2">
            <span className="flex items-center space-x-1.5 text-xs font-bold text-slate-800">
              <Briefcase className="w-3.5 h-3.5 text-slate-500" />
              <span>Construction (CIS)</span>
            </span>
            <p className="text-[11px] text-slate-500">
              Whether the company deducts CIS, suffers it, or both.
            </p>
            <CustomSelect
              fullWidth
              size="sm"
              value={profile.cis_status || "NONE"}
              onChange={(v) => pick("cis_status", v)}
              options={[
                { value: "NONE", label: "Not in CIS" },
                { value: "CONTRACTOR", label: "Contractor (deducts CIS)" },
                { value: "SUBCONTRACTOR", label: "Subcontractor (suffers CIS)" },
                { value: "BOTH", label: "Both" },
              ]}
            />
            {suggestionFor("cis_status")}
          </div>
        </div>

              <TaxDetails setup={setup} set={setS} vat={Boolean(profile.is_vat_registered)} payroll={Boolean(profile.has_payroll)} cis={profile.cis_status || "NONE"} />
        {/* Section 5: Corporation tax facts not in the books */}
        <div>
          <label className="block text-[11px] font-bold text-slate-700 mb-1">
            Corporation tax (from last year&apos;s tax computation and the client)
          </label>
          <div className="grid grid-cols-2 sm:grid-cols-3 gap-2 p-2 bg-slate-50 border border-slate-200 rounded-lg">
            {([
              ["associated_companies", "Associated companies (excl. this one)", "1"],
              ["losses_bf", "Trading losses brought forward £", "0.01"],
              ["main_pool_bf", "Main pool b/f (capital allowances) £", "0.01"],
              ["special_pool_bf", "Special rate pool b/f £", "0.01"],
              ["double_tax_relief", "Double tax relief (foreign tax) £", "0.01"],
              ["dla_repaid_within_9_months", "Director loan repaid within 9 months £", "0.01"],
              ["amortisation_allowed", "Amortisation confirmed allowable £", "0.01"],
              ["aia_claim", "AIA claimed, if less than the full £", "0.01"],
              ["main_wda_claim", "Main pool WDA claimed, if less £", "0.01"],
              ["special_wda_claim", "Special pool WDA claimed, if less £", "0.01"],
            ] as [keyof TaxInputs, string, string][]).map(([key, label, step]) => (
              <label key={key} className="flex flex-col text-[11px] text-slate-500">
                {label}
                <input type="number" min="0" step={step}
                       value={profile.tax_inputs?.[key] ?? ""}
                       onChange={(e) => setProfile((prev) => ({
                         ...prev,
                         tax_inputs: { ...(prev.tax_inputs || {}), [key]: e.target.value === "" ? undefined : Number(e.target.value) },
                       }))}
                       className="mt-0.5 text-xs font-mono rounded-md border border-slate-300 bg-white px-2 py-1 text-slate-800" />
              </label>
            ))}
          </div>
        </div>

            </div>
  );
}
