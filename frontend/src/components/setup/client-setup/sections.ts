// The seven parts of the client setup: which profile fields and setup parts each one owns and saves.

import { ClientProfile } from "@/types/engagement";

/** The parts of the setup, in the order the facts matter. Each part owns some profile fields and some parts of the
 *  setup record, and is saved on its own (saving a field confirms it as the accountant's answer). */
export type SectionKey = "engagement" | "industry" | "tax" | "people" | "policies" | "materiality" | "last_year";
export const SECTIONS: { key: SectionKey; title: string; lead: string; fields: (keyof ClientProfile)[]; parts: string[] }[] = [
  { key: "engagement", title: "Engagement", fields: ["accounting_framework"], parts: ["client"],
    lead: "Who, which period, which framework. The size test uses the figures from the books unless you type others." },
  { key: "industry", title: "Industry & business model", fields: ["industry_code", "properties"], parts: ["industry"],
    lead: "The industry loads its checks; the business model and the answers below narrow them." },
  { key: "tax", title: "Tax & compliance", fields: ["is_vat_registered", "vat_scheme", "has_payroll", "cis_status", "tax_inputs"],
    parts: ["vat", "payroll", "cis", "ct"],
    lead: "Registrations decide which checks run. Leave a field blank if unknown: the check stays on and becomes a client query." },
  { key: "people", title: "People & ownership", fields: ["directors", "companies_house"], parts: ["people"],
    lead: "Each name is searched in the ledger for the loan account, pay, dividends and related parties." },
  { key: "policies", title: "Accounting policies", fields: ["capitalisation_threshold"], parts: ["policies"],
    lead: "These values replace a guess: blank means the firm default." },
  { key: "materiality", title: "Materiality", fields: ["materiality_threshold"], parts: ["materiality"],
    lead: "Separates a £150 query from a £25,000 one. Performance and trivial default to 75% and 5%." },
  { key: "last_year", title: "Last year", fields: [], parts: ["prior_year"],
    lead: "Anything ticked is retested this year to confirm it was resolved." },
];
// Suggestions belong to the part that saves them
export const SUGGESTION_SECTION: Record<string, SectionKey> = {
  accounting_framework: "engagement", prior_year_tb_gl: "engagement", industry_code: "industry",
  is_vat_registered: "tax", has_payroll: "tax", cis_status: "tax",
};
export const pounds = (v: unknown) => Number(v).toLocaleString("en-GB", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
export const same = (a: unknown, b: unknown) => JSON.stringify(a ?? null) === JSON.stringify(b ?? null);
