/**
 * Centralized formatting utilities for currency, dates, percentages, and files.
 */

interface CurrencyOptions {
  showPence?: boolean;
  accountingStyle?: boolean; // Formats negative numbers as (£X.XX) instead of -£X.XX
  currencySymbol?: string;
}

/**
 * Format a number as GBP currency (£)
 * e.g. 14500 -> "£14,500.00", -500 (accountingStyle) -> "(£500.00)"
 */
export function formatCurrency(
  amount: number | null | undefined,
  options: CurrencyOptions = {}
): string {
  if (amount === null || amount === undefined || isNaN(amount)) {
    return "£0.00";
  }

  const {
    showPence = true,
    // Accountants' style on every screen: a minus in brackets, (£500.00), as the working papers and the Excel show it
    accountingStyle = true,
    currencySymbol = "£",
  } = options;

  const isNegative = amount < 0;
  const absAmount = Math.abs(amount);

  const formattedNumber = new Intl.NumberFormat("en-GB", {
    minimumFractionDigits: showPence ? 2 : 0,
    maximumFractionDigits: showPence ? 2 : 0,
  }).format(absAmount);

  if (isNegative) {
    if (accountingStyle) {
      return `(${currencySymbol}${formattedNumber})`;
    }
    return `-${currencySymbol}${formattedNumber}`;
  }

  return `${currencySymbol}${formattedNumber}`;
}

/**
 * Format an ISO date or timestamp into a readable UK date string
 * e.g. "2024-03-31T00:00:00" -> "31 Mar 2024"
 */
export function formatDate(
  dateInput: string | Date | null | undefined,
  style: "short" | "medium" | "long" = "medium"
): string {
  if (!dateInput) return "-";

  try {
    const d = typeof dateInput === "string" ? new Date(dateInput) : dateInput;
    if (isNaN(d.getTime())) return String(dateInput);

    if (style === "short") {
      // 31/03/2024
      return new Intl.DateTimeFormat("en-GB", {
        day: "2-digit",
        month: "2-digit",
        year: "numeric",
      }).format(d);
    }

    if (style === "long") {
      // 31 March 2024
      return new Intl.DateTimeFormat("en-GB", {
        day: "numeric",
        month: "long",
        year: "numeric",
      }).format(d);
    }

    // Default medium: 31 Mar 2024
    return new Intl.DateTimeFormat("en-GB", {
      day: "2-digit",
      month: "short",
      year: "numeric",
    }).format(d);
  } catch {
    return String(dateInput);
  }
}

/**
 * Format byte size into readable KB or MB
 * e.g. 1048576 -> "1.0 MB"
 */
export function formatFileSize(bytes: number | null | undefined): string {
  if (!bytes || bytes <= 0 || isNaN(bytes)) return "0 B";
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

/**
 * Safely parse a date string (ISO, UK DD/MM/YYYY, or "DD Mon YYYY, HH:MM") into a Date object
 */
export function parseDateSafe(dateStr: string | null | undefined): Date | null {
  if (!dateStr || dateStr === "-" || dateStr.trim() === "") return null;

  // Try direct Date constructor (works for ISO and "30 Sep 2026, 14:02")
  const directDate = new Date(dateStr);
  if (!isNaN(directDate.getTime())) return directDate;

  // Try UK DD/MM/YYYY
  const ukMatch = dateStr.match(/^(\d{1,2})\/(\d{1,2})\/(\d{4})/);
  if (ukMatch) {
    const day = parseInt(ukMatch[1], 10);
    const month = parseInt(ukMatch[2], 10) - 1;
    const year = parseInt(ukMatch[3], 10);
    const parsed = new Date(year, month, day);
    if (!isNaN(parsed.getTime())) return parsed;
  }

  return null;
}

/** "1 client", "2 clients": a count with its word in the right form. */
export function plural(n: number, word: string, many: string = `${word}s`): string {
  return `${n} ${n === 1 ? word : many}`;
}

/** "just now", "5 min ago", "3 h ago", "2 days ago", or the date for anything older than a month. */
export function timeAgo(iso?: string | null): string {
  if (!iso) return "";
  const then = new Date(iso);
  const mins = Math.round((Date.now() - then.getTime()) / 60000);
  if (mins < 1) return "just now";
  if (mins < 60) return `${mins} min ago`;
  const hours = Math.round(mins / 60);
  if (hours < 24) return `${hours} h ago`;
  const days = Math.round(hours / 24);
  if (days < 31) return `${days} day${days === 1 ? "" : "s"} ago`;
  return then.toLocaleDateString("en-GB", { day: "2-digit", month: "short", year: "numeric" });
}

/** A server time as a Date. The server sends UTC times without a zone ('2026-11-01T08:55:12'), which a browser would
 *  read as local time; a date alone ('2026-11-01') or a time with its zone is read as it is. */
export function serverDate(iso: string): Date {
  return new Date(iso.length > 10 && !/(Z|[+-]\d\d:?\d\d)$/i.test(iso) ? `${iso}Z` : iso);
}

/** An account name without its code said twice: '4800 - HSBC Current (4800)' -> '4800 HSBC Current',
 * '5400 - 5400 Directors loan account' -> '5400 Directors loan account'. Other names are left as they are. */
export function accountLabel(name: string): string {
  const m = (name || "").match(/^(\d{3,5}) - (?:\1 )?(.+?)(?: \(\1\))?$/);
  return m ? `${m[1]} ${m[2]}` : name;
}
