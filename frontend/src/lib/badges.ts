import type { LucideIcon } from "lucide-react";
import { Briefcase, Building, Building2, Factory, Hammer, HardHat, HeartHandshake, Landmark, Laptop, Scissors, ShoppingCart, Stethoscope, Store, Truck, UserCheck, Users, UtensilsCrossed } from "lucide-react";

/**
 * Badge styles for accounting software systems, mapping statuses and industries.
 */

export interface BadgeStyle {
  label: string;
  color: string;
  bg: string;
  border: string;
  className: string;
  isRequired?: boolean;
}

/**
 * Visual styling for accounting software source systems (Xero, QuickBooks, Sage, etc.)
 */
export function getAccountingSystemBadge(system?: string): BadgeStyle {
  const s = (system || "").toLowerCase();

  // A client with no accounting software: books prepared in the app from the bank statement and Dext
  if (s === "bank_dext") {
    return {
      label: "Bank + Dext",
      color: "text-violet-800",
      bg: "bg-violet-50",
      border: "border-violet-200",
      className: "bg-violet-50 text-violet-700 border-violet-200",
    };
  }

  if (s.includes("xero")) {
    return {
      label: "Xero",
      color: "text-sky-800",
      bg: "bg-sky-50",
      border: "border-sky-200",
      className: "bg-sky-50 text-sky-700 border-sky-200",
    };
  }

  if (s.includes("quickbooks") || s.includes("qbo")) {
    return {
      label: "QuickBooks",
      color: "text-emerald-800",
      bg: "bg-emerald-50",
      border: "border-emerald-200",
      className: "bg-emerald-50 text-emerald-700 border-emerald-200",
    };
  }

  if (s.includes("sage")) {
    return {
      label: "Sage",
      color: "text-green-800",
      bg: "bg-green-50",
      border: "border-green-200",
      className: "bg-green-50 text-green-700 border-green-200",
    };
  }

  return {
    // Read by the columns the accountant chose (software the app has no reader for)
    label: s === "other" ? "Other software" : system || "General Ledger",
    color: "text-slate-700",
    bg: "bg-slate-50",
    border: "border-slate-200",
    className: "bg-slate-50 text-slate-700 border-slate-200",
  };
}

/**
 * Returns the badge for how a trial balance account was mapped to the firm chart.
 */
export function getMappingStatusBadge(status?: string): BadgeStyle {
  switch (status) {
    case "MATCHED":
      return { label: "Matched", color: "text-emerald-800", bg: "bg-emerald-50", border: "border-emerald-200", className: "bg-emerald-50 text-emerald-700 border-emerald-200" };
    case "AI_SUGGESTED":
      return { label: "AI", color: "text-sky-800", bg: "bg-sky-50", border: "border-sky-200", className: "bg-sky-50 text-sky-700 border-sky-200" };
    case "NEEDS_REVIEW":
      return { label: "Needs review", color: "text-amber-800", bg: "bg-amber-50", border: "border-amber-200", className: "bg-amber-50 text-amber-700 border-amber-200" };
    default:
      return { label: "Unmapped", color: "text-rose-800", bg: "bg-rose-50", border: "border-rose-200", className: "bg-rose-50 text-rose-700 border-rose-200" };
  }
}

export const UK_INDUSTRIES = [
  { code: "CON", name: "Construction & Contracting", icon: HardHat, desc: "CIS deductions, DRC invoices, WIP & retentions" },
  { code: "RES", name: "Restaurant & Hospitality", icon: UtensilsCrossed, desc: "Platform payouts (Deliveroo), tips/tronc, hot/cold VAT" },
  { code: "MFG", name: "Manufacturing & Engineering", icon: Factory, desc: "Raw materials, WIP absorption, scrap/wastage" },
  { code: "PRP", name: "Property & Real Estate", icon: Building2, desc: "Rent, letting agents, Option to Tax, Capital Goods Scheme" },
  { code: "ECM", name: "E-Commerce & Digital", icon: ShoppingCart, desc: "Shopify/Amazon/eBay fees, overseas VAT, payment gateways" },
  { code: "PRO", name: "Professional Services", icon: Briefcase, desc: "Unbilled time/WIP, partner drawings, PI insurance" },
  { code: "SAAS", name: "Technology & SaaS", icon: Laptop, desc: "Deferred subscription revenue, AWS hosting, R&D tax relief" },
  { code: "RTL", name: "Retail & Wholesale", icon: Store, desc: "Stock shrinkage, EPOS till variance, supplier rebates" },
  { code: "REC", name: "Recruitment & Staffing", icon: Users, desc: "Temp worker payroll, umbrella companies, IR35" },
  { code: "TRN", name: "Transport & Logistics", icon: Truck, desc: "Fuel cards, fleet HP, tachograph, commercial vehicle leases" },
  { code: "PRD", name: "Property Trading & Development", icon: Hammer, desc: "Development stock (WIP), sale completions, finance costs" },
  { code: "HBB", name: "Hair, Beauty & Barbers", icon: Scissors, desc: "Chair rental, cash takings, product sales, tips" },
  { code: "CNS", name: "Contractors & Consultants", icon: UserCheck, desc: "One-person companies, IR35, few customers, expenses" },
  { code: "HLT", name: "Healthcare & Care", icon: Stethoscope, desc: "NHS / CCG income, VAT exemption, care home fees" },
  { code: "CHR", name: "Charities & Churches", icon: HeartHandshake, desc: "Donations, Gift Aid, restricted funds" },
  { code: "HLD", name: "Holding & Investment", icon: Landmark, desc: "Dividends from subsidiaries, intercompany loans, investments" },
  { code: "UNIV", name: "Universal Commercial", icon: Building, desc: "Standard statutory commercial entity (Universal rules)" },
];

export function getIndustryBadge(code?: string): { label: string; short: string; icon: LucideIcon; className: string } {
  const c = (code || "UNIV").toUpperCase();
  switch (c) {
    case "CON":
      return { label: "Construction", short: "CON", icon: HardHat, className: "bg-amber-50 text-amber-800 border-amber-200" };
    case "RES":
      return { label: "Restaurant", short: "RES", icon: UtensilsCrossed, className: "bg-rose-50 text-rose-800 border-rose-200" };
    case "MFG":
      return { label: "Manufacturing", short: "MFG", icon: Factory, className: "bg-indigo-50 text-indigo-800 border-indigo-200" };
    case "PRP":
      return { label: "Property", short: "PRP", icon: Building2, className: "bg-emerald-50 text-emerald-800 border-emerald-200" };
    case "ECM":
      return { label: "E-Commerce", short: "ECM", icon: ShoppingCart, className: "bg-purple-50 text-purple-800 border-purple-200" };
    case "PRO":
      return { label: "Professional", short: "PRO", icon: Briefcase, className: "bg-blue-50 text-blue-800 border-blue-200" };
    case "SAAS":
      return { label: "Tech / SaaS", short: "SAAS", icon: Laptop, className: "bg-cyan-50 text-cyan-800 border-cyan-200" };
    case "RTL":
      return { label: "Retail", short: "RTL", icon: Store, className: "bg-teal-50 text-teal-800 border-teal-200" };
    case "REC":
      return { label: "Recruitment", short: "REC", icon: Users, className: "bg-pink-50 text-pink-800 border-pink-200" };
    case "TRN":
      return { label: "Transport", short: "TRN", icon: Truck, className: "bg-teal-50 text-teal-800 border-teal-200" };
    case "PRD":
      return { label: "Property trading", short: "PRD", icon: Hammer, className: "bg-emerald-50 text-emerald-800 border-emerald-200" };
    case "HBB":
      return { label: "Hair & beauty", short: "HBB", icon: Scissors, className: "bg-rose-50 text-rose-800 border-rose-200" };
    case "CNS":
      return { label: "Contractor", short: "CNS", icon: UserCheck, className: "bg-blue-50 text-blue-800 border-blue-200" };
    case "HLT":
      return { label: "Healthcare", short: "HLT", icon: Stethoscope, className: "bg-sky-50 text-sky-800 border-sky-200" };
    case "CHR":
      return { label: "Charity", short: "CHR", icon: HeartHandshake, className: "bg-amber-50 text-amber-800 border-amber-200" };
    case "HLD":
      return { label: "Holding company", short: "HLD", icon: Landmark, className: "bg-slate-100 text-slate-700 border-slate-200" };
    default:
      return { label: "General", short: "UNIV", icon: Building, className: "bg-slate-100 text-slate-700 border-slate-200" };
  }
}
