export type MappingStatus = "MATCHED" | "AI_SUGGESTED" | "NEEDS_REVIEW" | "UNMAPPED";
export type FindingSeverity = "CRITICAL" | "HIGH" | "MEDIUM" | "LOW";
export type FindingStatus = "OPEN" | "CLEARED";

export interface TBRecord {
  id: number;
  raw_account_name: string;
  std_code: number | null;
  std_name: string | null;
  debit_amount: number;
  credit_amount: number;
  net_amount: number;
  mapping_status: MappingStatus;
  confidence_score: number;
  source_account_type?: string | null;
  match_source?: string | null;
  mapping_reason?: string | null;
}

export interface AuditFinding {
  id: number;
  stage?: string;
  procedure_ref: string;
  procedure_name: string;
  severity: FindingSeverity;
  source_row_ref: string;
  finding_title: string;
  finding_details: string;
  quantified_amount: number;
  suggested_journal: string;
  status: FindingStatus;
  cleared_note?: string | null;
  cleared_at?: string | null;
  /** The point's figures as a small table, written by the check that raised it */
  figures?: PointFigures | null;
}

/** A cell: a number is money (shown £1,234.56, a minus in brackets), a string is shown as it is */
export type FigureCell = number | string | null;

/** A review point's figures (backend review/point_figures.py) */
export interface PointFigures {
  /** Column headings: the first is over the labels */
  columns: string[];
  rows: { label: string; values: FigureCell[]; strong?: boolean }[];
  /** Rows of a long list left out */
  more?: number;
}

export interface ProposedJournal {
  id: number;
  engagement_id: string;
  finding_id?: number | null;
  stage: string;
  journal_ref: string;
  description: string;
  debit_code: number;
  debit_name: string;
  credit_code: number;
  credit_name: string;
  amount: number;
  status: "PROPOSED" | "APPROVED" | "REJECTED";
  source?: "REVIEW" | "MANUAL" | null;
  created_at?: string;
  posted_at?: string | null;
  lines?: JournalLine[];
}

export interface JournalLine {
  line_no: number;
  account_code: number;
  account_name?: string | null;
  narrative?: string | null;
  debit: number;
  credit: number;
}

export interface ManualJournalLineInput {
  account_code: number;
  narrative?: string;
  debit: number;
  credit: number;
}

export interface ClientProperty {
  name: string;
  model: "RENTAL" | "TRADING";
  rent_start?: string | null;   // yyyy-mm-dd; blank = taken from the first rent in the ledger
  words?: string[];             // how the property appears in the ledger, besides its name
  reason?: string;              // why the app suggested it
}

// Corporation tax facts that are not in the client's books (Tax_Comp inputs)
export interface TaxInputs {
  associated_companies?: number;      // other companies under common control, excluding this one
  losses_bf?: number;                 // trading losses brought forward from earlier years
  main_pool_bf?: number;              // capital allowances main pool written-down value brought forward
  special_pool_bf?: number;           // capital allowances special rate pool brought forward
  double_tax_relief?: number;         // foreign tax credit allowed against UK tax
  dla_repaid_within_9_months?: number; // director loan repaid within 9 months of the year end (s455 relief)
  amortisation_allowed?: number;      // intangibles' amortisation the reviewer confirmed qualifies (CTA 2009 Part 8)
  aia_claim?: number;                 // AIA claimed when less than the full allowance (CAA 2001 s51A); this year only
  main_wda_claim?: number;            // main pool WDA claimed when less than the full (CAA 2001 s56(5)); this year only
  special_wda_claim?: number;         // special pool WDA claimed when less than the full; this year only
}

export interface ClientProfile {
  engagement_id: string;
  industry_code: string;
  is_vat_registered: boolean;
  vat_scheme: string;
  has_payroll: boolean;
  cis_status: string;
  directors: string[];
  accounting_framework: string;
  materiality_threshold: number;
  capitalisation_threshold: number;
  auto_detected: boolean;
  confirmed_fields?: string[];
  properties?: ClientProperty[];
  tax_inputs?: TaxInputs;
  companies_house?: CompaniesHouseRecord | Record<string, never>;
  /** The rest of the Engagement Setup: client, industry, vat, payroll, cis, ct, policies, people, materiality, prior_year */
  setup?: Record<string, any>;
  detection_signals?: {
    detected_industry?: string;
    industry_score?: number;
    signals?: string[];
    turnover_detected?: number;
    all_scores?: Record<string, number>;
    industry_unsure?: string[] | null;
    // No exact Companies House match at upload: the closest companies, to confirm on the People step
    ch_choices?: CompaniesHouseChoice[];
  } | null;
}

// Directors and shareholders over 25% during the year, from the Companies House register
export interface CompaniesHousePerson {
  name: string;
  roles: string[];
  kind: "person" | "company";
  from: string | null;
  to: string | null;
  /** Other names the register lists for the same person (directors and shareholders are separate lists) */
  also_listed_as?: string[];
}
export interface CompaniesHouseRecord {
  company_number: string;
  company_name: string;
  status?: string;
  year?: [string, string];
  fetched_at?: string;
  people: CompaniesHousePerson[];
}
export interface CompaniesHouseChoice {
  company_number: string;
  company_name: string;
  status: string;
  address?: string;
  exact: boolean;
}

// What the Engagement Setup switches on, and what still blocks the review
export interface SetupCheck {
  id: string;
  engine: string;
  rules: string;
  reason: string;
  state: "on" | "unknown";
}
export interface SetupStatus {
  record: Record<string, any>;
  activated: SetupCheck[];
  gaps: string[];
  warnings: string[];
  suggestions: Record<string, { value: any; reason: string }>;
  catalogue?: {
    industries: Record<string, { name: string; models: string[]; questions: { id: string; label: string; type: "yn" | "number" | "text" | "chips"; options?: string[]; rules: string }[] }>;
    prior_year_issues: { label: string; rules: string }[];
  };
}

export interface EngagementData {
  engagement_id: string;
  client_name: string;
  period_end_date: string;
  source_system: string;
  total_tb_rows: number;
  total_gl_rows: number;
  tb_net_balance: number;
  tb_records: TBRecord[];
  profile?: ClientProfile | null;
  latest_workpaper?: LatestWorkpaper | null;
  status?: EngagementStatus | null;
}

// Whether the review and the workbook still reflect the client's current data
export interface EngagementStatus {
  data_changed_at: string | null;
  review_run_at: string | null;
  review_stale: boolean;
  workbook_stale: boolean;
  last_activity_at: string | null;
  mappings_to_review: number;
  has_tax_computation: boolean;
  latest_workpaper?: LatestWorkpaper | null;
  /** What must be done before the workbook can be built (empty: ready). */
  build_blockers?: string[];
}

// The last workbook built for a client
export interface LatestWorkpaper {
  id: number;
  filename: string;
  generated_at: string | null;
  is_draft: boolean;
  download_url: string;
  file_size_bytes?: number;
}

export interface ClientListItem {
  engagement_id: string;
  client_name: string;
  period_end_date: string;
  source_system: string;
  is_vat_registered?: boolean;
  total_tb_rows: number;
  mappings_to_review: number;
  open_audit_findings: number;
  created_at: string;
  latest_workpaper_id: number | null;
  workbook_state: "none" | "draft" | "final";
  setup_confirmed: boolean;
  review_stale: boolean;
  workbook_stale: boolean;
  last_activity_at: string | null;
  company_key?: string; // the same company's year-ends share it (Companies House number, else the name)
  company_number?: string;
  accounts_due?: string | null; // yyyy-mm-dd: the accounts filing deadline at Companies House
  vat_period_end?: string | null; // yyyy-mm-dd: the next VAT return's period end (from the returns entered)
  vat_due?: string | null; // yyyy-mm-dd: when that VAT return and its payment are due at HMRC
  checking?: string | null; // the checks running in the background: "6 of 13"
}

export interface SupplementaryDocument {
  id: number;
  engagement_id: string;
  doc_type: string; // VAT_100, FIXED_ASSET_REGISTER, PAYROLL_P32, OTHER
  filename: string;
  file_size_bytes: number;
  parsed_records_count: number;
  created_at?: string;
}

export interface VAT100Record {
  id: number;
  engagement_id: string;
  period_label: string;
  period_end?: string | null;
  bfwd_outstanding?: number | null;
  box1_vat_due_sales: number;
  box2_vat_due_acquisitions: number;
  box3_total_vat_due: number;
  box4_vat_reclaimed: number;
  box5_net_vat: number;
  box6_total_sales_ex_vat: number;
  box7_total_purchases_ex_vat: number;
  box8_supplies_to_eu: number;
  box9_acquisitions_from_eu: number;
}

export interface VatReturnInput {
  period_end: string; // yyyy-mm-dd
  box1: number;
  box2: number;
  box4: number;
  box6: number;
  box7: number;
  box8: number;
  box9: number;
  bfwd_outstanding?: number | null;
}

export interface FixedAssetRecord {
  id: number;
  engagement_id: string;
  asset_tag?: string | null;
  description: string;
  category: string;
  acquisition_date?: string | null;
  cost_bwd: number;
  additions: number;
  disposals: number;
  cost_fwd: number;
  depr_rate_method?: string | null;
  depr_bwd: number;
  depr_charge: number;
  depr_disposals: number;
  depr_fwd: number;
  nbv: number;
}

export interface PayrollP32Record {
  id: number;
  engagement_id: string;
  tax_month_label: string;
  period_end?: string | null;
  employee_name?: string | null;
  student_loan?: number | null;
  gross_pay: number;
  tax_deducted: number;
  employee_nic: number;
  employer_nic: number;
  statutory_pay_recovered: number;
  net_pay: number;
  pension_employee: number;
  pension_employer: number;
  total_hmrc_due: number;
}

export interface SupplementaryData {
  vat_records: VAT100Record[];
  fixed_asset_records: FixedAssetRecord[];
  payroll_records: PayrollP32Record[];
}

// Account rules page: "an account whose name contains these words goes to this code" (the firm's own choices)
export interface FirmRuleInput {
  words: string;
  except_words?: string;
  std_code: number;
  note?: string;
  active: boolean;
}
export interface FirmRule extends FirmRuleInput {
  id: number;
  std_name: string;
  position: number;
  updated_at: string | null;
  /** client accounts this rule decides */
  matches: number | null;
}
export interface FirmRuleMatch {
  engagement_id: string;
  client: string;
  account: string;
  current_code: number | null;
  current_name: string | null;
  match_source: string | null;
  balance: number;
  /** why the account keeps its code (set by an accountant, last year's code...), or null */
  kept_because: string | null;
  would_change: boolean;
}
