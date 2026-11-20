// The chart code shape and the category groups the change-code picker filters by.
export interface MasterCOAItem {
  std_code: number;
  std_name: string;
  category?: string;
  is_extended?: boolean;
}

export const CATEGORY_GROUPS = [
  { id: "ALL", label: "All codes", matcher: () => true },
  {
    id: "BANK",
    label: "Bank & cash",
    matcher: (cat: string) => cat.toLowerCase().includes("bank") || cat.toLowerCase().includes("cash"),
  },
  {
    id: "SALES",
    label: "Sales & Income",
    matcher: (cat: string) =>
      cat.toLowerCase().includes("sales") ||
      cat.toLowerCase().includes("operating income") ||
      cat.toLowerCase().includes("income"),
  },
  {
    id: "COS",
    label: "Cost of Sales",
    matcher: (cat: string) => cat.toLowerCase().includes("cost of sales") || cat.toLowerCase().includes("stock"),
  },
  {
    id: "STAFF",
    label: "Payroll & Staff",
    matcher: (cat: string) => cat.toLowerCase().includes("employee") || cat.toLowerCase().includes("payroll"),
  },
  {
    id: "ADMIN",
    label: "Admin & Overhead",
    matcher: (cat: string) =>
      cat.toLowerCase().includes("admin") ||
      cat.toLowerCase().includes("premises") ||
      cat.toLowerCase().includes("distribution") ||
      cat.toLowerCase().includes("depreciation"),
  },
  {
    id: "ASSETS",
    label: "Fixed Assets",
    matcher: (cat: string) =>
      cat.toLowerCase().includes("tangible") ||
      cat.toLowerCase().includes("intangible") ||
      cat.toLowerCase().includes("asset") ||
      cat.toLowerCase().includes("investment"),
  },
  {
    id: "DEBTORS",
    label: "Debtors",
    matcher: (cat: string) =>
      cat.toLowerCase().includes("debtor") || cat.toLowerCase().includes("prepayment"),
  },
  {
    id: "CREDITORS",
    label: "Creditors & Loans",
    matcher: (cat: string) =>
      cat.toLowerCase().includes("creditor") ||
      cat.toLowerCase().includes("liabilit") ||
      cat.toLowerCase().includes("hire purchase") ||
      cat.toLowerCase().includes("interest payable"),
  },
  {
    id: "EQUITY",
    label: "Equity & Capital",
    matcher: (cat: string) =>
      cat.toLowerCase().includes("capital") ||
      cat.toLowerCase().includes("profit and loss") ||
      cat.toLowerCase().includes("reserve"),
  },
];
