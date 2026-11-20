// The balance sheet screen: every balance sheet account against what it is agreed to.
import { API_BASE, fetch } from "./client";

/** One control account on the control accounts screen: the books against what they are agreed to */
export interface Reconciliation {
  key: string;
  account: string;
  area: "Bank" | "Tax" | "Payroll" | "Balance sheet";
  books: number;
  compared_with: string;
  other: number | null;
  difference: number | null;
  status: "MATCHED" | "DIFFERENCE" | "NEEDS_INPUT";
  tab: string;
  note: string;
  currency: string;
  entered: { balance?: number; currency_amount?: number; rate?: number; agreed?: boolean; note?: string; statement_date?: string; page?: string; rate_source?: string } | null;
  /** Where it sits on the balance sheet ("Fixed assets", ... "Must be nil", "Profit and loss checks") */
  section: string;
  last_year: number | null;
  codes: number[];
  /** Agreed to its document by the accountant's tick */
  ticked: boolean;
  /** VAT only: the line-by-line proof, in the VAT reconciliation layout (one per scheme and basis) */
  proof?: VatProof | null;
  /** Its codes' balance in the books, debit + (books can be turned round: VAT, trade creditors as amounts owed) */
  balance?: number | null;
}

export interface VatProofLine {
  key: string;
  label: string;
  /** null: not known (shown as such, left out of the total) */
  amount: number | null;
  note: string;
  /** Typed by the accountant (exception report, adjustments) */
  entered: boolean;
}

export interface VatProof {
  title: string;
  scheme: "STANDARD" | "FLAT_RATE";
  basis: "ACCRUALS" | "CASH";
  lines: VatProofLine[];
  total: number | null;
  books: number;
  difference: number | null;
  missing: string;
}

export interface Reconciliations {
  accounts: number;
  matched: number;
  differences: number;
  needs_input: number;
  sections: string[];
  /** The balance sheet by value, and how much of it is agreed */
  value_total: number;
  value_agreed: number;
  rows: Reconciliation[];
}

/** A bank statement balance typed on the screen: in £, or a foreign currency balance and the year-end rate */
export interface ReconciliationEntry {
  key: string;
  balance?: number;
  currency_amount?: number;
  rate?: number;
  /** A balance sheet account ticked as agreeing to its document, and what it was agreed to */
  agreed?: boolean;
  note?: string;
  /** Where a bank balance came from: the statement's date (ISO) and page, and a currency rate's source */
  statement_date?: string;
  page?: string;
  rate_source?: string;
  clear?: boolean;
}

/** One firm code on the extended trial balance: the TB, the approved journals and the final balance (debit +) */
export interface EtbRow {
  code: number;
  name: string;
  /** The client's accounts mapped to the code */
  accounts: string[];
  pl: boolean;
  tb: number;
  journals: number;
  final: number;
  /** Last year's final balance (null: not known) */
  last_year: number | null;
}

export interface Etb {
  rows: EtbRow[];
  /** Where last year's balances came from ("" = nothing to compare with) */
  last_year_source: string;
  /** TB balances with no code yet (not on the ETB until they are mapped) */
  unmapped: number;
  totals: { tb: number; journals: number; final: number };
}

/** One type of ledger line in an account's year (invoices, receipts, payments ...): debit + */
/** One asset class in the fixed asset schedule (Tangible / Intangible Assets) */
export interface FixedAssetClass {
  name: string;
  codes: number[];
  cost_bf: number; additions: number; disposals: number; cost_cf: number;
  dep_bf: number; charge: number; elimination: number; dep_cf: number;
  nbv: number; nbv_bf: number;
}
export type FixedAssetFigures = Omit<FixedAssetClass, "name" | "codes">;
export interface FixedAssetSchedule {
  tangible: { classes: FixedAssetClass[]; total: FixedAssetFigures };
  intangible: { classes: FixedAssetClass[]; total: FixedAssetFigures };
  opening_source: string;
}

/** The Adjustments block under the trade debtors / creditors T */
export interface TradeAdjustment {
  key: "duplicate" | "unallocated" | "direct" | "opening";
  label: string;
  amount: number | null;
  count: number;
  details: string[];
  more: number;
  note: string;
}
export interface TradeAdjustments { side: "customer" | "supplier"; lines: TradeAdjustment[] }

/** Sales per the VAT returns to sales in the P&L (the sales reconciliation) */
export interface SalesReconciliation {
  lines: { key: "box6" | "closing" | "opening" | "adjustments" | "unidentified" | "pl"; label: string; amount: number; note: string }[];
  /** Every return in the year has Box 6 and they cover the year */
  ready: boolean;
  why_not: string;
  basis: "ACCRUALS" | "CASH";
  flat_rate: boolean;
}

/** The payroll month by month from the payroll reports (the Payroll Summary) */
export interface PayrollSummaryFigures {
  gross: number; paye: number; ee_ni: number; student_loan: number; ee_pension: number; er_ni: number; net: number;
  er_pension: number; liability: number; allowance: number; total_liability: number; pension_payable: number;
}
export interface PayrollSummaryTable {
  key: "total" | "employees" | "directors";
  title: string;
  people: number;
  months: (PayrollSummaryFigures & { month: string; pay_date: string })[];
  total: PayrollSummaryFigures;
}
export interface PayrollSummary { tables: PayrollSummaryTable[]; has_reports: boolean; split: string; director_names?: string[] }

/** A bank account's statement lines against its ledger (Unrecorded, Unmatched, Matched) */
export interface StatementLine { id: string; date: string | null; description: string; amount: number; type?: string; balance?: number | null }
export interface BankStatementMatch {
  read: boolean;
  files: number[];
  from: string | null;
  to: string | null;
  matched: { statement: StatementLine; ledger: StatementLine; days: number }[];
  unmatched: StatementLine[];
  unrecorded: StatementLine[];
  statement_lines?: number;
  ledger_lines?: number;
}

/** The asset register asset by asset */
export interface AssetFigures {
  cost_bf: number; additions: number; disposals: number; cost_cf: number; dep_bf: number; charge: number;
  dep_disposal: number; dep_cf: number; nbv: number; nbv_bf: number;
}
export interface AssetLine extends AssetFigures { id: number; description: string; date: string | null; rate: number; method: string; residual_value: number | null; useful_life_years: number | null }
export interface AssetRegister { classes: { name: string; assets: AssetLine[]; total: AssetFigures }[]; total: AssetFigures }

/** The corporation tax computation line by line */
export interface TaxLine { label: string; amount: number; box: string; note: string }
export interface TaxCalculation {
  lines: TaxLine[];
  capital_allowances: TaxLine[];
  corporation_tax: number; s455_tax: number; total_tax: number; tax_in_accounts: number; difference: number;
  notes: string[];
}
/** Retained earnings this year and last */
export interface ReservesYear { bf: number; profit: number; dividends: number; cf: number }
export interface ReservesMovement { this_year: ReservesYear; last_year: ReservesYear | null; difference: number | null }

export interface RollforwardMovement {
  /** The line's name as an accountant reads it ("Sales invoices raised", "Bank receipts") */
  type: string;
  lines: number;
  debit: number;
  credit: number;
  net: number;
  /** The software's own types in it, most lines first ("Invoice", "Bill Payment (Cheque)") */
  types?: string[];
}

/** A balance sheet account's year: opening + this year's lines by type + approved journals = closing (debit +) */
export interface Rollforward {
  codes: number[];
  names: string[];
  opening: number;
  /** Where the opening came from; "" = worked out as the closing balance less this year's lines */
  opening_source: string;
  movements: RollforwardMovement[];
  lines: number;
  movement: number;
  tb_closing: number;
  journals: number;
  /** The journals approved in the app by name, depreciation for the year first (amount null: not run yet) */
  journal_lines?: { label: string; amount: number | null; note?: string; named?: boolean }[];
  closing: number;
  /** Opening + lines less the TB's closing balance (null when the opening is only worked out) */
  difference: number | null;
}

/** Debtors by age from the client's aged receivables report: five boxes per customer (not due ... 91+ days) */
export interface DebtorAgeing {
  /** The report's file name; null when no aged receivables report was uploaded */
  report: string | null;
  as_at?: string | null;
  /** "columns": the report's own age columns; "dates": aged by invoice date at the report date */
  method?: "columns" | "dates";
  boxes?: string[];
  customers?: { customer: string; total: number; boxes: number[] }[];
  totals?: number[];
  total?: number;
  report_total?: number | null;
  undated?: number;
  /** Each open invoice by customer (the trade debtors listing) */
  listing?: { customer: string; total: number; items: { date: string | null; type: string; number: string; due: string | null; amount: number }[] }[];
}

/** One month of a payroll control account (owed = credit +): owed, employment allowance, paid, balance, note */
export interface PayrollMonth {
  month: string;          // yyyy-mm-dd, the month end
  owed: number;
  allowance: number;
  paid: number;
  balance: number;
  note: string | null;
}

/** Net wages, PAYE / NI or pension month by month, as the workbook's G6 / G7 / G8 */
export interface PayrollTable {
  key: "net_wages" | "paye" | "pension";
  title: string;
  opening: number;
  flags: number;
  with_allowance: boolean;
  months: PayrollMonth[];
  /** What the months do not explain (other dates, opening lines in the ledger) */
  other: number;
  /** Journals approved in the app, as owed (credit +) */
  journals: number;
  allowance_journal: number;
  closing: number;
  tb_closing: number;
}

/** The payroll cost each month against what was owed out (G6.2) */
export interface PayrollSummaryMonth {
  month: string;
  costs: number[];
  total_cost: number;
  net_pay: number;
  paye: number;
  pension: number;
  total_owed: number;
  difference: number;
  via_dla: number;
  /** null when the client has no net wages account (cost v owed out cannot be checked month by month) */
  unexplained: number | null;
}

export interface PayrollMonths {
  tables: PayrollTable[];
  summary: { cost_names: string[]; has_net_wages: boolean; months: PayrollSummaryMonth[]; flags: number } | null;
}

export const reconciliationsApi = {
  async getDebtorAgeing(engagementId: string): Promise<DebtorAgeing> {
    const res = await fetch(`${API_BASE}/engagements/${engagementId}/debtor-ageing`);
    if (!res.ok) throw new Error((await res.json().catch(() => ({}))).detail || "Could not read the aged debtors report");
    return res.json();
  },

  async getCreditorAgeing(engagementId: string): Promise<DebtorAgeing> {
    const res = await fetch(`${API_BASE}/engagements/${engagementId}/creditor-ageing`);
    if (!res.ok) throw new Error((await res.json().catch(() => ({}))).detail || "Could not read the aged creditors report");
    return res.json();
  },

  async getPayrollMonths(engagementId: string): Promise<PayrollMonths> {
    const res = await fetch(`${API_BASE}/engagements/${engagementId}/payroll-months`);
    if (!res.ok) throw new Error((await res.json().catch(() => ({}))).detail || "Could not work out payroll by month");
    return res.json();
  },

  async getRollforward(engagementId: string, codes: number[]): Promise<Rollforward> {
    const res = await fetch(`${API_BASE}/engagements/${engagementId}/rollforward?codes=${codes.join(",")}`);
    if (!res.ok) throw new Error((await res.json().catch(() => ({}))).detail || "Could not work out the roll-forward");
    return res.json();
  },

  async getFixedAssetSchedule(engagementId: string): Promise<FixedAssetSchedule> {
    const res = await fetch(`${API_BASE}/engagements/${engagementId}/fixed-asset-schedule`);
    if (!res.ok) throw new Error((await res.json().catch(() => ({}))).detail || "Could not work out the fixed asset schedule");
    return res.json();
  },

  async getTradeAdjustments(engagementId: string, side: "customer" | "supplier"): Promise<TradeAdjustments> {
    const res = await fetch(`${API_BASE}/engagements/${engagementId}/trade-adjustments?side=${side}`);
    if (!res.ok) throw new Error((await res.json().catch(() => ({}))).detail || "Could not work out the adjustments");
    return res.json();
  },

  async getSalesReconciliation(engagementId: string): Promise<SalesReconciliation> {
    const res = await fetch(`${API_BASE}/engagements/${engagementId}/sales-reconciliation`);
    if (!res.ok) throw new Error((await res.json().catch(() => ({}))).detail || "Could not work out the sales reconciliation");
    return res.json();
  },

  async getPayrollSummary(engagementId: string): Promise<PayrollSummary> {
    const res = await fetch(`${API_BASE}/engagements/${engagementId}/payroll-summary`);
    if (!res.ok) throw new Error((await res.json().catch(() => ({}))).detail || "Could not read the payroll summary");
    return res.json();
  },

  async getBankStatement(engagementId: string, code: number): Promise<BankStatementMatch> {
    const res = await fetch(`${API_BASE}/engagements/${engagementId}/bank-statement/${code}`);
    if (!res.ok) throw new Error((await res.json().catch(() => ({}))).detail || "Could not load the statement lines");
    return res.json();
  },

  /** Read an uploaded statement into its lines for one bank account (a PDF can take a minute) */
  async readBankStatement(engagementId: string, evidenceId: number, code: number): Promise<{ lines: number; notes: string[]; read_by: string }> {
    const res = await fetch(`${API_BASE}/engagements/${engagementId}/bank-statement/read`, {
      method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ evidence_id: evidenceId, code }),
    });
    if (!res.ok) throw new Error((await res.json().catch(() => ({}))).detail || "Could not read the statement");
    return res.json();
  },

  async getAssetRegister(engagementId: string): Promise<AssetRegister> {
    const res = await fetch(`${API_BASE}/engagements/${engagementId}/asset-register`);
    if (!res.ok) throw new Error((await res.json().catch(() => ({}))).detail || "Could not read the asset register");
    return res.json();
  },

  async getTaxCalculation(engagementId: string): Promise<TaxCalculation> {
    const res = await fetch(`${API_BASE}/engagements/${engagementId}/tax-calculation`);
    if (!res.ok) throw new Error((await res.json().catch(() => ({}))).detail || "Could not work out the tax");
    return res.json();
  },

  async getReserves(engagementId: string): Promise<ReservesMovement> {
    const res = await fetch(`${API_BASE}/engagements/${engagementId}/reserves`);
    if (!res.ok) throw new Error((await res.json().catch(() => ({}))).detail || "Could not work out the reserves");
    return res.json();
  },

  async saveAssetDetails(engagementId: string, assetId: number, body: { residual_value: number | null; useful_life_years: number | null }) {
    const res = await fetch(`${API_BASE}/engagements/${engagementId}/asset-register/${assetId}`, {
      method: "PUT", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body),
    });
    if (!res.ok) throw new Error((await res.json().catch(() => ({}))).detail || "Could not save the asset");
    return res.json();
  },

  async getEtb(engagementId: string): Promise<Etb> {
    const res = await fetch(`${API_BASE}/engagements/${engagementId}/etb`);
    if (!res.ok) throw new Error((await res.json().catch(() => ({}))).detail || "Could not work out the ETB");
    return res.json();
  },


  async getReconciliations(engagementId: string): Promise<Reconciliations> {
    const res = await fetch(`${API_BASE}/engagements/${engagementId}/reconciliations`);
    if (!res.ok) throw new Error((await res.json().catch(() => ({}))).detail || "Could not work out the control accounts");
    return res.json();
  },

  async saveReconciliationEntry(engagementId: string, entry: ReconciliationEntry): Promise<Reconciliations> {
    const res = await fetch(`${API_BASE}/engagements/${engagementId}/reconciliations`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(entry),
    });
    if (!res.ok) throw new Error((await res.json().catch(() => ({}))).detail || "Could not save the figure");
    return res.json();
  },
};
