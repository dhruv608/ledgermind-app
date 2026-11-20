// Shapes the Self Assessment endpoints send and take.

export type SaSource =
  | "EMPLOYMENT" | "SELF_EMPLOYMENT" | "PROPERTY" | "SAVINGS" | "DIVIDENDS" | "PENSIONS" | "FOREIGN" | "CAPITAL_GAINS";

export interface SaJob {
  id: string;
  person_name: string;
  tax_year: string;              // "2025-26"
  sources: SaSource[];
  first_return: boolean;
  company: { engagement_id: string; name: string } | null;
  utr: string | null;            // masked: the last 3 characters only
  ni_number: string | null;      // masked
  created_at: string | null;
}

/** Where a return stands, for the home page (counts are null until it has documents) */
export interface SaJobStatus {
  documents: number;
  final: boolean;
  blocks: number | null;
  client: number | null;
  decisions: number | null;
  message: string | null;        // the open client queries as one message to send
  last_activity_at: string | null;
}

/** Foster, kinship or shared lives care for the year (qualifying care relief, R-SP-01) */
export interface SaFosterView {
  receipts: number | null; limit: number | null; exempt: boolean | null; profit: number;
  issues: { key: string; kind: "CLIENT" | "DECISION"; block: boolean; text: string }[];
  placements: { id: number; label: string; band: "UNDER_11" | "ELEVEN_PLUS" | "ADULT"; weeks: number }[];
  carers: number; method: "SIMPLIFIED" | "ACTUAL" | null; actual_costs: number | null;
  from_letters: number | null; typed: boolean;
}

export interface SaJobIn {
  person_name: string;
  tax_year: string;
  sources: SaSource[];
  first_return: boolean;
  company_engagement_id?: string;
  utr?: string;
  ni_number?: string;
}

export type SaDocStatus = "READ" | "CHECK" | "UNREADABLE" | "DUPLICATE" | "OTHER_YEAR" | "FILED";

export interface SaDocument {
  id: number;
  filename: string;
  kind: string;                  // P60, P45, BANK_STATEMENT...
  status: SaDocStatus;
  tax_year: string | null;
  fields: Record<string, string | number | null> | null;   // a P60: pay_this, tax_this, employer, paye_ref...
  note: string | null;
  read_by: string | null;
  size: number;
  created_at: string | null;
}

export interface SaLine {
  id: number;
  source: string;              // EMPLOYMENT, SAVINGS, DIVIDENDS, PENSIONS, RELIEFS, SELF_EMPLOYMENT, PROPERTY, FOREIGN
  kind: string;                // P60, PAY, INTEREST, ISA, DIVIDEND, STATE_PENSION, PENSION, BENEFIT, GIFT_AID...
  label: string;
  amount: number;
  tax_paid: number;
  share: number;
  extra: number | null;        // property: finance costs
  include: boolean;
  doc_id: number | null;
  auto: boolean;
  note: string | null;
  paid_on: string | null;
}

export type SaLineIn = Omit<SaLine, "id" | "doc_id" | "auto" | "include" | "extra" | "note" | "paid_on"> &
  Partial<Pick<SaLine, "extra" | "note" | "paid_on">>;

export interface SaDividend { date: string; amount: number; description: string; company: string; added: boolean }

export interface SaBandLine { kind: string; band: string; amount: number; rate: number; tax: number }

export interface SaCalculation {
  income: Record<string, number | string | boolean | null>;
  calculation: {
    tax_year: string; total_income: number; net_income: number; adjusted_net_income: number;
    personal_allowance: number; taxable: Record<string, number>; lines: SaBandLine[]; income_tax: number;
    reductions: Record<string, number>; income_tax_due: number; class4: number; class2: number; hicbc: number;
    student_loan: number; liability: number; tax_deducted: number; balance: number; poa_each: number;
    payments_on_account_made: number; due_31_january: number; class2_below_threshold: boolean;
    class4_exempt?: string;
  };
  trade?: { loss_year?: number; businesses?: unknown[] };
  notes: string[];
  // Already paid towards the year and the voluntary Class 2 choice (set: the accountant has made the choice)
  payments: { poa_paid: number; class2_voluntary: boolean; set: boolean; class4_exempt?: string; loss_claim?: string };
}

export interface SaPropertyItem { id: number; on: string | null; description: string; heading: string; amount: number; doc_id: number | null }

export interface SaPropertyRow {
  id: number; name: string; share: number; use_allowance: boolean; headings: Record<string, number>;
  rents: number; expenses: number; profit_whole: number; profit: number; finance_costs: number; capital: number;
  losses_bf: number; finance_bf: number; note: string | null; items: SaPropertyItem[];
  country: string | null; foreign_tax: number;
  owner: SaPropertyFacts["owner"]; kind: SaPropertyFacts["kind"]; let_from: string | null; let_to: string | null;
  ended: SaPropertyFacts["ended"]; own_home: SaPropertyFacts["own_home"]; rent_a_room: SaPropertyFacts["rent_a_room"];
  in_pool: boolean; rent_a_room_exempt: number; notes: string[];
  issues: { key: string; kind: "CLIENT" | "DECISION"; block: boolean; text: string }[];
}

export interface SaPropertyFacts {
  name: string; share: number; country: string | null;
  owner: "SOLE" | "SPOUSE" | "JOINT" | "COMPANY"; kind: "RESIDENTIAL" | "COMMERCIAL";
  let_from: string | null; let_to: string | null; ended: "SOLD" | "MOVED_IN" | "OTHER" | null;
  own_home: "ROOM" | "FORMER" | null; rent_a_room: "RENT_A_ROOM" | "ACTUAL" | null;
}

export interface SaPropertyView {
  properties: SaPropertyRow[];
  boxes: Record<string, number>;
  headings: Record<string, { label: string; box: number | null }>;
  before_losses: number; losses_bf: number; losses_used: number; profit: number; loss_cf: number;
  finance_costs: number; allowance: boolean; allowance_used: number;
  bank_rent?: SaBankRent[];
}

// Rent found in the person's own bank, by payer, not yet on a property (property: the one the agent lets, if known)
export interface SaBankRent {
  payer: string; total: number; why: string; property: number | null;
  lines: { key: string; account: string; on: string; description: string; amount: number }[];
}

export interface SaTradeItem { id: number; heading: string; description: string; amount: number; disallowed: number; doc_id: number | null }

export interface SaBusinessSettings {
  name: string; description: string | null; period_start: string | null; period_end: string | null; cash_basis: boolean;
  use_trading_allowance: boolean; home_hours: number | null; home_months: number | null; car_miles: number | null;
  motorcycle_miles: number | null; capital_allowances: number; balancing_charges: number; losses_bf: number;
  cis_deducted: number; note: string | null;
}

export interface SaBusinessRow {
  id: number; name: string; headings: Record<string, { amount: number; disallowed: number }>; income: number; costs: number;
  disallowed: number; accounts_profit: number; use_of_home: number; mileage: number; capital_allowances: number;
  balancing_charges: number; trading_allowance: number; adjusted_profit: number; losses_used: number; taxable_profit: number;
  loss_cf: number; cis_deducted: number; page: "SA103S" | "SA103F"; warnings: string[];
  settings: SaBusinessSettings; items: SaTradeItem[]; allowances: SaAllowanceLine[];
  balance_sheet?: SaBalanceSheet | null;
}

// A trade built from the bank: its small balance sheet (SEF 5) and the check that proves it
export interface SaBalanceSheet {
  period: { start: string; end: string };
  assets: { name: string; amount: number; movement_only?: boolean }[]; net_assets: number;
  capital: { opening: number; profit: number; introduced: number; drawings: number; transfers: number; loans_repaid: number;
             loans_received?: number; vat?: number; assets_bought?: number; unsorted: number; closing: number };
  difference: number; balances: boolean; notes: string[];
}

export interface SaAllowanceLine {
  id: number; kind: string; entered_kind: string; label: string; description: string; amount: number; private_use: number;
  allowance: number; pool_cf: number;
}

export interface SaTradeView {
  businesses: SaBusinessRow[]; taxable_profit: number; cis_deducted: number; loss_cf: number;
  headings: Record<string, { label: string; box: number; kind: "income" | "cost" }>;
}

export interface SaBankBookLine {
  key: string; account: string; on: string; description: string; in: number; out: number; doc_id: number | null; page: number;
  heading: string; rule: string; how: string; sure: boolean; chosen: boolean;
  suggestion?: { heading: string; label: string; sure: "high" | "medium" | "low"; reason: string };
}

export interface SaBankBooks {
  period: { start: string; end: string };
  accounts: { account: string; bank: string | null; checks: string[] }[];
  lines: SaBankBookLine[];
  totals: { heading: string; label: string; amount: number; lines: number; to_check: number }[];
  headings: { heading: string; label: string }[];
  mixed?: { kind: string; label: string; heading: string; amount: number; business_pct: number | null; disallowed: number }[];
}

export interface SaExpectLine {
  id: number; source: string; source_label: string; kind: string; kind_label: string; name: string; ref: string | null;
  last_amount: number | null; last_tax: number | null; ended: string | null; note: string | null;
  status: string | null; status_label: string; this_amount: number | null; question: string | null; group: string | null;
  hand: boolean; answer: string | null; auto: boolean; agreed: boolean;
}

export interface SaLastYear {
  document: { id: number; filename: string; tax_year: string | null; note: string | null } | null;
  total_income: number | null;
  answers: Record<string, boolean>;
  lines: SaExpectLine[];
  new: { source: string; source_label: string; name: string; amount: number }[];
  counts: Record<string, number>;
  statuses: { status: string; label: string }[];
  sources: Record<string, { label: string; kinds: { kind: string; label: string }[] }>;
}

export type SaExpectIn = Partial<Pick<SaExpectLine, "source" | "kind" | "name" | "ref" | "last_amount" | "last_tax" | "ended" | "note" | "answer" | "status">>;

export interface SaQuestion { key: string; question: string; answer: "YES" | "NO" | null; note: string | null; follow: string | null; last_year: string | null }

export interface SaSignal {
  key: string; kind: string; title: string; payer: string; question: string; total: number;
  lines: { on: string; description: string; amount: number }[]; state: "ASKED" | "DISMISSED" | null; note: string | null;
}

export interface SaQuestions { questions: SaQuestion[]; signals: SaSignal[]; bank_lines: number; open: number }

export interface SaQueryItem {
  no: number; key: string; kind: "CLIENT" | "DECISION"; text: string; page: string; block: boolean;
  answer: string | null; status: "OPEN" | "ANSWERED" | "DONE"; about: string;
}

export interface SaQueries { items: SaQueryItem[]; counts: { client: number; decisions: number; blocks: number }; message: string }

export type SaForeignKind = "INTEREST" | "DIVIDEND" | "PENSION" | "BENEFIT" | "OTHER";
export interface SaForeignIn {
  country: string; kind: SaForeignKind; payer: string; amount: number; foreign_tax: number; share: number; claim: boolean; note: string | null;
}
export interface SaForeignRow {
  id: number; country: string; country_name: string; kind: SaForeignKind; kind_label: string; payer: string; gross: number;
  foreign_tax: number; exempt: number; taxable: number; claim: boolean; creditable: number; credit: number; uk_tax?: number;
  treaty: string | null; doc_id: number | null; input: SaForeignIn; notes: string[];
  issues: { key: string; kind: "CLIENT" | "DECISION"; text: string; block: boolean }[];
}
export interface SaForeign {
  rows: SaForeignRow[]; credit: number; issues: SaForeignRow["issues"]; notes: string[];
  kinds: { kind: SaForeignKind; label: string }[]; countries: { code: string; name: string }[];
  treaties: { country: string; kind: string; taxed_in: string; article: string }[];
}

export type SaDisposalKind = "RESIDENTIAL" | "CRYPTO" | "OTHER" | "LISTED" | "UNLISTED";
export interface SaDisposalIn {
  kind: SaDisposalKind; name: string; acquired: string | null; contract_date: string | null; completion_date: string | null;
  proceeds: number; cost: number; costs: number; improvements: number; share: number; uk: boolean;
  main_home_months: number | null; badr: boolean; negligible: boolean; rtt_date: string | null; rtt_gain: number | null;
  rtt_tax: number | null; note: string | null;
}
export interface SaDisposalRow {
  id: number; kind: SaDisposalKind; kind_label: string; name: string; proceeds: number; allowable: number;
  before_relief: number; relief: number; gain: number; in_year: boolean; badr: boolean; negligible: boolean; sold: string | null;
  rtt_gain: number; rtt_tax: number; doc_id: number | null; input: SaDisposalIn; matched?: boolean;
  issues: { key: string; kind: "CLIENT" | "DECISION"; text: string; block: boolean }[]; notes: string[];
}
export interface SaCapitalGains {
  disposals: SaDisposalRow[]; issues: SaDisposalRow["issues"]; notes: string[];
  summary: { gains: number; losses: number; net: number; losses_bf: number; losses_bf_used: number; exempt: number;
             exempt_used: number; chargeable: number; loss_cf: number; tax: number; paid_60_day: number; badr_gains: number;
             lines: { name: string; band: string; amount: number; rate: number; tax: number }[] };
  sections: { kind: string; label: string; rows: { box: string; label: string; value: number | string }[] }[];
  kinds: { kind: SaDisposalKind; label: string }[]; losses_bf: number;
  holdings: {
    holding: string; kind: string; pool: { qty: number; cost: number }; issues: string[];
    trades: { id: number; on: string; side: "BUY" | "SELL" | "POOL"; quantity: number; amount: number; doc_id: number | null }[];
    sales: { on: string; qty: number; proceeds: number; cost: number; gain: number; parts: { rule: string; on: string | null; qty: number; cost: number }[] }[];
  }[];
  result: { cgt: number; cgt_paid: number; balance: number };
}

export interface SaFamilyFacts {
  child_benefit: number | null; children: number | null; cb_stopped: string | null;
  higher_income: "ME" | "PARTNER" | null; marriage: "TRANSFERRED" | "RECEIVED" | null; spouse_name: string | null;
  loan_plans: string[]; postgraduate: boolean; studying: boolean; sl_deducted: number | null; pgl_deducted: number | null;
}
export interface SaFamily {
  facts: SaFamilyFacts;
  answers: { child_benefit: string | null; married: string | null; student_loan: string | null };
  adjusted_net_income: number; hicbc: number; marriage_reduction: number; personal_allowance: number; hicbc_from: number;
  loan: { plans?: string[]; postgraduate?: boolean; income?: number; unearned?: number; unearned_counted?: boolean;
          threshold?: number | null; due?: number; pgl_due?: number; deducted?: number; pgl_deducted?: number;
          charge?: number; studying?: boolean };
  issues: { key: string; kind: "CLIENT" | "DECISION"; block: boolean; text: string }[];
  plans: { plan: string; label: string; threshold: number }[];
}

export interface SaPackVersion {
  id: number; version: number; kind: "FINAL" | "DRAFT"; note: string | null; blocks: number; balance: number | null;
  size: number; made_by: string | null; created_at: string | null;
}
export interface SaPacks { versions: SaPackVersion[]; counts: { client: number; decisions: number; blocks: number } }

export interface SaBoxRow { box: string; label: string; value: number | string | null; note: string; doc_id: number | null }
export interface SaBoxPage { form: string; title: string; note?: string; rows: SaBoxRow[] }
export interface SaBoxes {
  pages: SaBoxPage[]; left: string[];
  result: { income_tax_due: number; class4: number; class2: number; liability: number; tax_deducted: number;
            balance: number; poa_each: number; due_31_january: number };
}

export type SaState ="done" | "look" | "empty" | "later";

export interface SaOverview {
  result: { balance: number; liability: number; tax_deducted: number; due_31_january: number; poa_each: number; due_date: string };
  documents: { count: number; state: SaState; look: number };
  sections: { id: string; source: string; label: string; amount: number; state: SaState; from: string }[];
  steps: { id: string; label: string; state: SaState }[];
  look: { page: string; kind: string; text: string; doc_id?: number }[];
  queries?: { client: number; decisions: number; blocks: number };
  notes: string[];
}
