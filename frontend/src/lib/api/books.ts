// Clients with no accounting software: the Books tab.
import { API_BASE, fetch } from "./client";

/** The server could not tell which file is which (or two look like the same report): the accountant says. */
// Books tab: a client with no accounting software (bank statement and Dext), books prepared in the app
export interface BooksBankRow {
  key: string;
  row: number;
  account: string;
  date: string;
  description: string;
  money_in: number;
  money_out: number;
  head: string;
  code: number | null;
  why: string;
  check: boolean;
  chosen: boolean;
  probable: boolean;
  customer: string;
  payee: string;            // the payee's name in the line ("" = none): one head can be chosen for all its lines
  by_payee: boolean;        // the head comes from such a choice
  payee_this_year: boolean; // ...made this year (else carried from last year)
  picked: string;           // the choice in the dropdown: "head:Insurance", "code:3290" or ""
  ai?: { code: number; sure: "high" | "medium" | "low"; reason: string } | null;   // the AI's suggestion, not applied
}

export interface BooksPayment { date: string; amount: number; rule: string }
export interface BooksInvoice {
  number: string;
  date: string;
  customer: string;
  amount: number;
  paid: number;
  outstanding: number;
  status: string;
  last_year: boolean;
  paid_by: BooksPayment[];
}

export interface BooksBill {
  key: string;
  row: number;
  number: string;
  date: string;
  supplier: string;
  amount: number;
  vat: number;
  paid: number;
  outstanding: number;
  status: string;
  last_year: boolean;
  head: string;
  code: number;
  check: boolean;
  chosen: boolean;
  paid_by: BooksPayment[];
  picked: string;
}

export interface BooksCustomer {
  customer: string;
  brought_forward: number;
  invoiced: number;
  credit_notes: number;
  received: number;
  position: number;
  status: string;
}

export interface BooksQuestion { key: string; group: "explain" | "confirm" | "documents"; text: string; answer: string; answered: boolean }
/** A line of last year's TB that had only a name: the code it was given. */
export interface BooksOpeningLine {
  key: string;
  name: string;
  amount: number;     // debit +
  code: number;
  why: string;
  sure: boolean;
  chosen: boolean;
  picked: string;
}

export interface BooksData {
  client: string;
  opening: BooksOpeningLine[];
  year_end: string | null;
  summary: { bank_lines: number; to_check: number; debtors: number; creditors: number; questions: number };
  file_problems: { where: string; severity: string; text: string }[];
  chart: { code: number; name: string; section: string; pl: boolean; extended: boolean }[];
  bank: BooksBankRow[];
  customers: BooksCustomer[];
  invoices: BooksInvoice[];
  bills: BooksBill[];
  questions: BooksQuestion[];
  checks: {
    bank_books: number;
    bank_statement: number | null;
    banks: { account: string; code: number; books: number; statement: number | null }[];
    transfers: number;
    debtors: number;
    debtors_books: number;
    creditors: number;
    creditors_books: number;
    suspense: number;
    out_of_balance: number;
    questions_open: number;
  };
  choices: string[];
  directors_known: boolean;
  /** No exact Companies House match at upload: the closest company, to confirm on Setup (People) */
  company_to_confirm?: string | null;
}

export const booksApi = {
  async getBooks(engagementId: string): Promise<BooksData> {
    const res = await fetch(`${API_BASE}/books/${engagementId}`);
    if (!res.ok) {
      const err = await res.json().catch(() => ({}));
      throw new Error(typeof err.detail === "string" ? err.detail : "The books could not be loaded");
    }
    return res.json();
  },

  /** value null puts the line back to what the app worked out. */
  async suggestBankHeads(engagementId: string): Promise<{ asked: number; suggested: number; payees: number }> {
    const res = await fetch(`${API_BASE}/books/${engagementId}/ai-suggest`, { method: "POST" });
    if (!res.ok) {
      const err = await res.json().catch(() => ({}));
      throw new Error(typeof err.detail === "string" ? err.detail : "The AI could not be asked");
    }
    return res.json();
  },

  async saveBooksChoice(engagementId: string, key: string, value: Record<string, unknown> | null): Promise<void> {
    const res = await fetch(`${API_BASE}/books/${engagementId}/choice`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ key, value }),
    });
    if (!res.ok) {
      const err = await res.json().catch(() => ({}));
      throw new Error(typeof err.detail === "string" ? err.detail : "The choice was not saved");
    }
  },

  async makeBooksTrialBalance(engagementId: string): Promise<{ accounts: number; entries: number }> {
    const res = await fetch(`${API_BASE}/books/${engagementId}/trial-balance`, { method: "POST" });
    if (!res.ok) {
      const err = await res.json().catch(() => ({}));
      throw new Error(typeof err.detail === "string" ? err.detail : "The trial balance could not be made");
    }
    return res.json();
  },
};
