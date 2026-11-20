import type { AuditFinding, ProposedJournal } from "@/types/engagement";

/**
 * The areas of a year-end, as the workspace checklist shows them: each review point belongs to the area its
 * reference starts with, and each journal to the area of the point that proposed it. The first area whose pattern
 * fits wins, so the narrow ones (CT600 capital allowances, s455) come before the broad ones (corporation tax).
 * Anything unmatched is a general check.
 */
export interface Area {
  key: string;
  label: string;
  refs: RegExp;
}

export const AREAS: Area[] = [
  { key: "opening", label: "Opening balances", refs: /^(U-OB|E-004)/ },
  { key: "bank", label: "Bank and cash", refs: /^(U-BNK|BK-|U-FX|F\d)/ },
  { key: "sales", label: "Sales and debtors", refs: /^(U-REV|U-DEB|AR-|E\d|U-INS|V-F02)/ },
  { key: "purchases", label: "Purchases and creditors", refs: /^(U-CRD|AP-|FRS-F-006)/ },
  { key: "payroll", label: "Net wages and payroll", refs: /^(U-PAY|PY-\d|U-SUB|CIS|U-EA)/ },
  { key: "vat", label: "VAT", refs: /^(V-|VT-)/ },
  { key: "accruals", label: "Accruals and prepayments", refs: /^(U-ACC|U-ACI|U-DEF|U-PRE|U-ADJ-003|G2$|G3$|YE-0[12])/ },
  { key: "fixed", label: "Fixed assets", refs: /^(U-FA|CT-CA|FRS-FA|FRS-IN|C1|G1$)/ },
  { key: "stock", label: "Stock", refs: /^(U-STK|YE-03)/ },
  { key: "loans", label: "Loans and HP", refs: /^(U-LOAN|U-LSE|TB-0[12])/ },
  { key: "dla", label: "Director's loan and dividends", refs: /^(U-DLA|DL-|U-DIV|U-EQ|RP-|CT-A-)/ },
  { key: "tax", label: "Corporation tax", refs: /^(CT-|U-CT)/ },
  // "expenses", not "coding": that key opens the Coding review (re-analysis, mispostings), whose step is separate
  { key: "expenses", label: "Profit and loss review", refs: /^(G9$|U-ADJ-004|U-JNL|U-PRV|SC-|K0)/ },
];

// Points about the whole job (going concern, the industry, suspense): no page of their own, listed on Review points
export const GENERAL: Area = { key: "general", label: "Whole job", refs: /.^/ };

export function areaOfRef(ref: string | null | undefined): Area {
  return AREAS.find((a) => a.refs.test(ref || "")) || GENERAL;
}

// Kinds of point that belong to one area but whose code says nothing about it (each check goes to
// the working paper it is about, no "General checks" page)
const KIND_AREAS: [RegExp, string][] = [
  [/^G6$/, "dla"],                       // director's salary settled through the director's loan
  [/^U-ADJ-005/, "payroll"],             // director's salary as answered, not in the books
  [/^U-ADJ-00[12]/, "accruals"],         // last year's accruals reversed
  [/^U-GRT/, "sales"],                   // grant-type receipts (income)
];

/** The area a review point belongs to: the account it is about (its code, for last year v this year and balances on
 * the wrong side), the supplier or customer it is about (duplicates), its kind, else its reference. What is about the
 * whole job (going concern, the industry, suspense, a journal posted twice) stays general: the Review points tab
 * lists it as "Whole job". */
// The open job's accounts: the client's account name -> its firm code, so a point that names an account without its
// code (last year v this year: "Creditors - EUR") still finds its area. Set by the client page when its trial balance loads.
let accountCodes = new Map<string, number>();
export function setAccountCodes(accounts: { name: string; code: number | null }[]): void {
  accountCodes = new Map(accounts.filter((a) => a.code !== null).map((a) => [a.name.trim().toLowerCase(), a.code as number]));
}

export function areaOfPoint(f: Pick<AuditFinding, "procedure_ref" | "source_row_ref" | "finding_title">): Area {
  const ref = f.procedure_ref || "";
  const byKey = (key: string) => [...AREAS, GENERAL].find((a) => a.key === key) || GENERAL;
  const kind = KIND_AREAS.find(([re]) => re.test(ref));
  if (kind) return byKey(kind[1]);
  if (/^(PY-MOVE|U-BS-SIDE|U-TB-004)$/.test(ref)) {
    const lead = (s: string | null | undefined) => Number(((s || "").match(/^\s*(\d{4})\b/) || [])[1]) || 0;
    const code = lead(f.source_row_ref) || lead(f.finding_title)
      || accountCodes.get((f.source_row_ref || "").trim().toLowerCase()) || 0;
    // A profit and loss code: sales (0-999), else costs (Expense coding, its P&L analysis)
    if (code) return byKey(areaKeyOfCode(code) !== GENERAL.key ? areaKeyOfCode(code) : code < 1000 ? "sales" : code < 4000 ? "expenses" : GENERAL.key);
  }
  if (ref === "G5") {
    const src = f.source_row_ref || "";
    if (/^(supplier |Same-day bills|Suppliers with bills)/.test(src)) return byKey("purchases");
    if (/^customer |Duplicates review/.test(src)) return byKey("sales");
    if (/^Accruals also billed/.test(src)) return byKey("accruals");
  }
  return areaOfRef(ref);
}

/** A journal's area: its point's, else its stage's (the VAT and tax stages), else general. */
export function areaOfJournal(j: ProposedJournal, findingsById: Map<number, AuditFinding>): Area {
  const point = j.finding_id ? findingsById.get(j.finding_id) : undefined;
  if (point) return areaOfPoint(point);
  if (j.stage === "STAGE_3_CT600") return AREAS.find((a) => a.key === "tax")!;
  if (j.stage === "STAGE_2_VAT") return AREAS.find((a) => a.key === "vat")!;
  return GENERAL;
}

export function areaByKey(key: string | null | undefined): Area | undefined {
  return [...AREAS, GENERAL].find((a) => a.key === key);
}

/**
 * The area a firm chart code's balance belongs to, for the tie-out lines at the top of each area (the Balance sheet
 * tab's control accounts: books against what they should be). Code ranges of the firm chart; anything else is general.
 */
const CODE_AREAS: [number, number, string][] = [
  [4000, 4299, "fixed"], [4600, 4650, "fixed"],
  [4300, 4310, "stock"],
  [4400, 4449, "sales"], [4500, 4549, "sales"],
  [4450, 4469, "tax"], [4550, 4569, "tax"], [5310, 5310, "tax"], [5710, 5710, "tax"], [6100, 6100, "tax"], [3800, 3899, "tax"],
  [4800, 4830, "bank"], [9998, 9998, "bank"], [5351, 5351, "bank"],
  [4900, 4950, "accruals"], [5360, 5369, "accruals"], [5760, 5760, "accruals"],
  [5000, 5199, "loans"], [5500, 5555, "loans"], [6000, 6000, "loans"],
  [5200, 5201, "purchases"], [5350, 5350, "purchases"], [5600, 5600, "purchases"],
  [5300, 5300, "vat"], [5700, 5700, "vat"],
  [5320, 5331, "payroll"], [5352, 5353, "payroll"], [5720, 5730, "payroll"],
  [8000, 8000, "opening"], [8030, 8030, "opening"],
  [5400, 5416, "dla"], [5800, 5816, "dla"], [7000, 8099, "dla"],
  // 9999 suspense is not cost coding: it falls to General checks with its "must be nil" point (U-TB-003)
];

export function areaKeyOfCode(code: number): string {
  return CODE_AREAS.find(([from, to]) => code >= from && code <= to)?.[2] ?? GENERAL.key;
}

// Where each area's supporting document comes in (an Evidence step per balance)
export const AREA_EVIDENCE: Record<string, { what: string; where: "inputs" | "data" | "recs" }> = {
  vat: { what: "The VAT returns (or the client's VAT summary)", where: "inputs" },
  payroll: { what: "The payroll report (P32 or payroll summary) and the pension provider's statement", where: "inputs" },
  bank: { what: "The bank statements, showing each account's balance at the year end", where: "recs" },
  sales: { what: "The aged debtors report", where: "data" },
  purchases: { what: "The aged creditors report", where: "data" },
  fixed: { what: "The fixed asset register and invoices for additions", where: "data" },
  loans: { what: "The loan and hire purchase statements or agreements", where: "data" },
  stock: { what: "The year-end stock count, with how it was valued", where: "data" },
  dla: { what: "Dividend vouchers and board minutes, if a dividend was declared", where: "data" },
  accruals: { what: "Bills received after the year end, and last year's accruals and prepayments list", where: "data" },
};
