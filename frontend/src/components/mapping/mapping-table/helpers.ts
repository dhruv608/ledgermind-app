// Props, filters and sort types of the accounts and mappings table, and the tests that sort accounts into them.
import { TBRecord } from "@/types/engagement";

export interface MappingTableProps {
  records: TBRecord[];
  engagementId?: string;
  /** A mapping was confirmed or changed (the page refreshes its counts and warnings). */
  onChanged?: () => void;
}

// A nil account (no balance, no movement) changes no figure, so it never needs review
export const isNil = (r: TBRecord) =>
  [r.net_amount, r.debit_amount, r.credit_amount].every((v) => Math.abs(Number(v || 0)) < 0.005);
export const needsReview = (r: TBRecord) =>
  (r.mapping_status === "NEEDS_REVIEW" || r.mapping_status === "UNMAPPED") && !isNil(r);

// Below this a balance is trivial (points over £250 and under materiality are MEDIUM)
export const TRIVIAL_FLOOR = 250;

export type StatusFilter = "ALL" | "REVIEW" | "AI" | "CONFIRMED";

// Balance sheet or P&L: by the firm code (4000 and up is the balance sheet), else by the account's name
export const BS_WORDS = ["asset", "fa -", "bank", "cash", "debtor", "creditor", "vat", "loan", "share", "capital", "stock"];
export const isBalanceSheet = (r: TBRecord) => {
  const code = r.std_code === null || r.std_code === undefined || (r.std_code as unknown) === "" ? NaN : Number(r.std_code);
  if (!isNaN(code)) return code >= 4000;
  const name = r.raw_account_name.toLowerCase();
  return BS_WORDS.some((w) => name.includes(w));
};
export const matchesStatus = (r: TBRecord, status: StatusFilter) =>
  status === "REVIEW" ? needsReview(r)
    : status === "AI" ? r.mapping_status === "AI_SUGGESTED"
    : status === "CONFIRMED" ? r.mapping_status === "MATCHED"
    : true;

export type SortField =
  | "raw_account_name"
  | "debit_amount"
  | "credit_amount"
  | "net_amount"
  | "std_code";

export type SortOrder = "asc" | "desc" | "none";


// The app's 'Check' flag: the code contradicts the account's name or balance (income on a liability code, a cost
// code in credit...). Such an account is confirmed on its own, never in bulk.
export const isFlagged = (r: TBRecord) => r.mapping_status === "NEEDS_REVIEW" && (r.mapping_reason || "").startsWith("Check:");
