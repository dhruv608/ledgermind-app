import type { Reconciliation } from "@/lib/api";
import { areaKeyOfCode } from "@/lib/areas";
import type { BalanceGroup } from "@/components/review/workpapers/BalancesWorkpaper";

/**
 * How each area's working papers are laid out: the sections its balances fall in, the summary's name, the areas
 * shown as two papers, and the Creditors and Loan summaries' groups. Data only: the screens (AreaPanel,
 * BalancesWorkpaper) read it.
 */

// Trade debtors and creditors (customers, suppliers; with their bad debt provisions and the over-a-year parts) apart
// from the area's other balances (other debtors, CIS recoverable, deposits, other creditors)
export const TRADE_CODES = new Set([4400, 4401, 4500, 5200, 5201, 5600]);
const within = (...ranges: [number, number][]) => (c: number) => ranges.some(([a, b]) => c >= a && c <= b);
// The sections an area's balances are shown in, as an accountant reads them (the first that fits all of a balance's
// codes; "rest" takes what fits none). A trade section has its listing by age under it.
type Section = { title: string; fits?: (code: number) => boolean; listing?: "AR" | "AP" };
export const SECTIONS: Record<string, Section[]> = {
  sales: [{ title: "Trade debtors", fits: (c) => TRADE_CODES.has(c), listing: "AR" }, { title: "Other debtors" }],
  purchases: [{ title: "Trade creditors", fits: (c) => TRADE_CODES.has(c), listing: "AP" }, { title: "Other creditors" }],
  bank: [{ title: "Bank accounts", fits: within([4800, 4830]) }, { title: "Credit cards", fits: within([5351, 5351]) },
         { title: "Transfers between own accounts", fits: within([9998, 9998]) }, { title: "Other" }],
  loans: [{ title: "Due within one year", fits: within([5000, 5199]) }, { title: "Due after one year", fits: within([5500, 5699]) },
          { title: "Other" }],
  dla: [{ title: "Director's loan", fits: within([5400, 5416], [5800, 5816]) },
        { title: "Share capital, reserves and dividends", fits: within([7000, 8099]) }, { title: "Other" }],
  accruals: [{ title: "Prepayments and accrued income", fits: within([4900, 4950]) },
             { title: "Accruals and deferred income", fits: within([5360, 5369], [5760, 5760]) }, { title: "Other" }],
  tax: [{ title: "Corporation tax owed", fits: within([5310, 5310], [5710, 5710]) },
        { title: "Tax recoverable and s455", fits: within([4450, 4459], [4550, 4569]) },
        { title: "Deferred tax", fits: within([4460, 4469], [6100, 6100]) },
        { title: "Charge for the year", fits: within([3800, 3899]) }, { title: "Other" }],
};
// The areas shown as balance summaries (BalancesWorkpaper): the summary's name and its line
export const PAPERS: Record<string, { title: string; intro: string }> = {
  sales: { title: "Debtors summary", intro: "Trade debtors against the aged debtors list, and other debtors. View opens each one's working paper." },
  purchases: { title: "Creditors summary", intro: "Trade creditors against the aged creditors list, and other creditors. View opens each one's working paper." },
  loans: { title: "Loan summary", intro: "Each loan and hire purchase balance, due within one year and after one year, against the lender's statement. View opens each one's working paper." },
  fixed: { title: "Fixed assets against the register", intro: "Each asset class (cost and depreciation) against the fixed asset register. View opens its year: cost, additions, disposals and depreciation." },
  stock: { title: "Stock summary", intro: "Stock and work in progress at the year end against the stock count. View opens its working paper." },
  opening: { title: "Opening balances summary", intro: "Each balance brought forward against last year's closing balance. View opens its working paper." },
  tax: { title: "Corporation tax summary", intro: "Corporation tax owed, recoverable and deferred, and this year's charge, against the tax computation. View opens each one's working paper." },
};
// Areas shown as two separate working papers, each on its own tab (prepayments and
// accruals separate screens, share capital and reserves apart from the director's loan; debtors and creditors stay one
// summary each): the tab's name, its paper, and the sections it holds
export type Split = { label: string; title: string; intro: string; sections: string[] };
export const SPLITS: Record<string, [Split, Split]> = {
  dla: [
    { label: "Director's loan", title: "Director's loan summary", sections: ["Director's loan", "Other"],
      intro: "What each director owes the company or is owed at the year end. View opens each one's working paper." },
    { label: "Share capital and reserves", title: "Share capital and reserves summary", sections: ["Share capital, reserves and dividends"],
      intro: "Share capital, reserves and the dividends of the year, against Companies House and the dividend paperwork. View opens each one's working paper." },
  ],
  accruals: [
    { label: "Prepayments", title: "Prepayments summary", sections: ["Prepayments and accrued income"],
      intro: "Prepayments and accrued income at the year end; below, last year's and this year's prepayments line by line. View opens each one's working paper." },
    { label: "Accruals", title: "Accruals summary", sections: ["Accruals and deferred income", "Other"],
      intro: "Accruals and deferred income at the year end; below, last year's and this year's accruals line by line. View opens each one's working paper." },
  ],
};
// The Creditors Summary: every creditor in one list, each with View: trade creditors, credit card, accruals,
// other creditors, bank loans and hire purchase, VAT, PAYE / wages / pension, the director's loan, corporation tax
const LIABILITIES = new Set(["Current liabilities", "Long-term liabilities"]);
const CREDITOR_KINDS: { title: string; fits: (r: Reconciliation, area: string) => boolean; listing?: "AP" }[] = [
  { title: "Trade creditors", fits: (r, a) => a === "purchases" && r.codes.every((c) => TRADE_CODES.has(c)), listing: "AP" },
  { title: "Credit card", fits: (r) => r.codes.every((c) => c === 5351) },
  { title: "Accruals and deferred income", fits: (_, a) => a === "accruals" },
  { title: "Bank loans and hire purchase", fits: (_, a) => a === "loans" },
  { title: "VAT", fits: (_, a) => a === "vat" },
  { title: "PAYE, wages and pension", fits: (_, a) => a === "payroll" },
  { title: "Director's loan", fits: (_, a) => a === "dla" },
  { title: "Corporation tax", fits: (_, a) => a === "tax" },
  { title: "Other creditors", fits: () => true },
];
const ORDER = ["Trade creditors", "Credit card", "Accruals and deferred income", "Other creditors", "Bank loans and hire purchase",
               "VAT", "PAYE, wages and pension", "Director's loan", "Corporation tax"];
// A creditor as an amount owed (credit +), however its row shows its books: a row that keeps the books' sign (credit -)
// is turned round, its last year and document with it, so the summary reads and adds up alike
export const asOwed = (r: Reconciliation): Reconciliation => {
  // A plain balance sheet code ("code:") always keeps the books' sign; other rows tell by their balance (nil: as is)
  const keepsSign = r.key.startsWith("code:")
    || (r.balance !== null && r.balance !== undefined && Math.abs(r.books - r.balance) < Math.abs(r.books + r.balance));
  if (!keepsSign) return r;
  const flip = (n: number | null) => (n === null ? null : -n);
  return { ...r, books: -r.books, last_year: flip(r.last_year ?? null), other: flip(r.other), difference: flip(r.difference) };
};

export function creditorGroups(rows: Reconciliation[]): BalanceGroup[] {
  const out = new Map<string, BalanceGroup>();
  for (const r of rows.filter((x) => LIABILITIES.has(x.section) && x.codes.length > 0).map(asOwed)) {
    const kind = CREDITOR_KINDS.find((k) => k.fits(r, areaKeyOfCode(r.codes[0])))!;
    const g = out.get(kind.title) || out.set(kind.title, { title: kind.title, listing: kind.listing, list: [] }).get(kind.title)!;
    g.list.push(r);
  }
  return ORDER.map((t) => out.get(t)).filter((g): g is BalanceGroup => Boolean(g));
}

// The Current Assets Summary: every current asset in one list, each with View: trade
// debtors, other debtors, prepayments, stock, investments, cash. Assets read as the books do (debit +)
const ASSET_KINDS: { title: string; fits: (r: Reconciliation, area: string) => boolean; listing?: "AR" }[] = [
  { title: "Trade debtors", fits: (r, a) => a === "sales" && r.codes.every((c) => TRADE_CODES.has(c)), listing: "AR" },
  { title: "Other debtors", fits: (_, a) => a === "sales" },
  { title: "Prepayments and accrued income", fits: (_, a) => a === "accruals" },
  { title: "Stock", fits: (_, a) => a === "stock" },
  { title: "Tax recoverable", fits: (_, a) => a === "tax" },
  { title: "Cash at bank and in hand", fits: (_, a) => a === "bank" },
  { title: "Director's loan (owed to the company)", fits: (_, a) => a === "dla" },
  { title: "Other current assets", fits: () => true },
];
export function currentAssetGroups(rows: Reconciliation[]): BalanceGroup[] {
  const out = new Map<string, BalanceGroup>();
  for (const r of rows.filter((x) => x.section === "Current assets" && x.codes.length > 0)) {
    const kind = ASSET_KINDS.find((k) => k.fits(r, areaKeyOfCode(r.codes[0])))!;
    const g = out.get(kind.title) || out.set(kind.title, { title: kind.title, listing: kind.listing, list: [] }).get(kind.title)!;
    g.list.push(r);
  }
  return ASSET_KINDS.map((k) => out.get(k.title)).filter((g): g is BalanceGroup => Boolean(g));
}

// The Loan Summary: each loan with its less than one year and more than one year parts. The firm chart
// keeps one code per loan kind and term (5100 bank loans < 1 year, 5500 > 1 year, 5000 / 5001 hire purchase ...)
// Each loan kind and term by its firm code: 5000-5009 hire purchase and 5010-5019 finance leases (x0 / x5 less than one
// year, x1 x2 / x6 x7 more), 5100 / 5500 bank loans, 5110 / 5510 other loans, 5120 / 5520 debentures
const loanKind = (code: number, account: string) =>
  code >= 5000 && code < 5010 ? "Hire purchase" : code >= 5010 && code < 5020 ? "Finance leases"
    : code === 5100 || code === 5500 ? "Bank loans" : code === 5120 || code === 5520 ? "Debentures"
    : /hire purchase|\bhp\b/i.test(account) ? "Hire purchase" : "Other loans";
const loanTerm = (code: number) =>
  (code >= 5000 && code < 5020 && [1, 2, 6, 7].includes(code % 10)) || (code >= 5500 && code < 5700) ? "More than 1 year" : "Less than 1 year";
// The lender in an account's name, without its code and its term ("5100 - Bank Loan UTA short term" -> "Bank Loan UTA")
const TERM_WORDS = /\s*[-–(,]*\s*(?:(?:short|long)[- ]term|[<>]\s*(?:12 months|1 year|one year)|(?:due )?(?:within|after|less than|more than|over|under) (?:one|1|12) (?:year|months?))\s*\)?/gi;
const lenderOf = (account: string) =>
  account.replace(/\s*\(\d{3,5}\)\s*$/, "").replace(/^\d{3,5}\s*-\s*(?:\d{3,5}\s+)?/, "").replace(TERM_WORDS, "").replace(/\s+/g, " ").trim() || account;

/** The Loan Summary: one group per loan (each lender, by kind), its less than 1 year and more than 1 year lines
 * under it. The row keeps the lender in its name for the paper it opens; the summary shows the term only. */
export function loanGroups(rows: Reconciliation[]): BalanceGroup[] {
  const out = new Map<string, Reconciliation[]>();
  for (const r of rows) {
    const kind = loanKind(r.codes[0] ?? 0, r.account);
    const lender = lenderOf(r.account);
    const title = new RegExp(kind.replace(/s$/, ""), "i").test(lender) ? lender : `${lender} (${kind.toLowerCase().replace(/s$/, "")})`;
    const term = loanTerm(r.codes[0] ?? 0);
    out.set(title, [...(out.get(title) || []), { ...asOwed(r), account: `${title}: ${term}` }]);
  }
  // Less than one year first within each loan
  return [...out.entries()].map(([title, list]) => ({ title, always: true, list: list.sort((a, b) => a.account.localeCompare(b.account)) }));
}

export function sectionsOf<T extends { codes: number[] }>(areaKey: string, list: T[], keepTitles = false) {
  const defs = SECTIONS[areaKey];
  if (!defs) return [{ title: "", listing: undefined, list }];
  const out = defs.map((d) => ({ title: d.title, listing: d.listing, list: [] as T[] }));
  for (const t of list) {
    const i = defs.findIndex((d) => !d.fits || (t.codes.length > 0 && t.codes.every(d.fits)));
    out[i === -1 ? out.length - 1 : i].list.push(t);
  }
  if (keepTitles) return out;     // an area of two papers: every section by its name, to put each on its tab
  // Headings only when they help: a trade section always (its listing), else when two or more sections have balances
  const shown = out.filter((g) => g.list.length > 0 || g.listing);
  return shown.length > 1 || shown.some((g) => g.listing) ? shown : [{ title: "", listing: undefined, list }];
}
