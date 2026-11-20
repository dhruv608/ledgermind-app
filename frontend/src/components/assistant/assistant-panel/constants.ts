// Sizes, storage keys, file limits and the starter text of the assistant panel, with small storage helpers.

import { BookOpen, Mail, Mic, Paperclip, Scale } from "lucide-react";

export const MIN_W = 360;
export const DEFAULT_W = 440;
export const WIDTH_KEY = "lm_assistant_width";
export const FULL_KEY = "lm_assistant_full";
export const SIDE_KEY = "lm_assistant_sidebar";
// The page is pushed aside only when it keeps at least this much room; on a narrower screen the panel opens over it
export const PAGE_ROOM = 1100;
// Files with a question: up to 5, 10 MB each, PDFs and pictures (read when added: a PDF's text, a picture transcribed)
export const MAX_FILES = 5;
export const MAX_MB = 10;
export const FILE_TYPES = ["application/pdf", "image/png", "image/jpeg", "image/webp", "image/gif"];

// What Ledge can do, shown when a chat starts empty: with no client open, and on a client's page
export const CAN_NONE = [
  { icon: Scale, title: "UK tax and accounts rules", sub: "Answers with the HMRC guidance or law behind them" },
  { icon: Paperclip, title: "Read your files", sub: "Up to 5 PDFs or photos with a question" },
  { icon: Mic, title: "Talk instead of type", sub: "Press the mic and speak your question in English" },
  { icon: Mail, title: "Draft client emails", sub: "Questions and chasers in plain English" },
];
export const CAN_CLIENT = [
  { icon: BookOpen, title: "This client's figures", sub: "Balances, ledger, review points, tax, payroll and VAT" },
  { icon: Scale, title: "The rules behind them", sub: "HMRC guidance and law, with sources" },
  { icon: Paperclip, title: "Read your files", sub: "Up to 5 PDFs or photos with a question" },
  { icon: Mail, title: "Draft client emails", sub: "Questions and chasers in plain English" },
];

export const STARTERS_CLIENT = [
  "Summarise this client for me",
  "Which control accounts don't agree, and why?",
  "What are the critical review points?",
  "Explain the corporation tax computation",
];
export const STARTERS_NONE = [
  "When is cold takeaway food zero-rated?",
  "What is the employment allowance for 2025/26?",
  "How do I treat a director's overdrawn loan account?",
];

export function clientIdOf(pathname: string | null): string | null {
  const m = /^\/clients\/([^/?#]+)/.exec(pathname || "");
  return m && m[1] !== "new" ? m[1] : null;
}

export function readFlag(key: string, fallback: boolean): boolean {
  try {
    const v = window.localStorage.getItem(key);
    return v === null ? fallback : v === "1";
  } catch {
    return fallback;
  }
}

export function saveFlag(key: string, v: boolean) {
  try { window.localStorage.setItem(key, v ? "1" : "0"); } catch { /* not saved */ }
}

export function readWidth(): number {
  try {
    const w = Number(window.localStorage.getItem(WIDTH_KEY));
    return w >= MIN_W ? w : DEFAULT_W;
  } catch {
    return DEFAULT_W;
  }
}
