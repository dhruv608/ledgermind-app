// Small pieces of a client row: the checking chip, the step bar, the workbook download and the deadline tags.
import React, { useState } from "react";
import { ClientListItem } from "@/types/engagement";
import { plural } from "@/lib/formatters";
import { CheckCircle2, Circle, CircleDot, Download, RefreshCw } from "lucide-react";
import { stepsOf, ukDate } from "@/components/clients/client-directory/stages";

// The checks running in the background for this client, and how far they have got
export function CheckingChip({ progress }: { progress: string }) {
  return (
    <span className="inline-flex items-center gap-1 whitespace-nowrap rounded-full bg-sky-50 px-2 py-0.5 text-[11px] font-semibold text-sky-800">
      <RefreshCw className="h-3 w-3 animate-spin" /> Checking · {progress}
    </span>
  );
}

export function StepBar({ client }: { client: ClientListItem }) {
  // The four steps by name, so a final workbook with the setup still open reads clearly
  return (
    <div className="grid w-[150px] grid-cols-2 gap-x-2 gap-y-0.5">
      {stepsOf(client).map((st) => {
        const Icon = st.state === "done" ? CheckCircle2 : st.state === "part" ? CircleDot : Circle;
        return (
          <span
            key={st.label}
            title={st.hint}
            className={`inline-flex items-center gap-1 text-[11px] ${
              st.state === "done" ? "text-emerald-700" : st.state === "part" ? "font-medium text-amber-700" : "text-slate-400"
            }`}
          >
            <Icon className="h-3 w-3" />
            {st.label}
          </span>
        );
      })}
    </div>
  );
}

/** The year's latest workbook, when one is built */
export function DownloadButton({ downloadUrl }: { downloadUrl?: string }) {
  if (!downloadUrl) return <span className="w-7" />;
  return (
    <a
      href={downloadUrl}
      download
      onClick={(e) => e.stopPropagation()}
      title="Download workbook"
      className="rounded-md p-1.5 text-slate-400 transition hover:bg-slate-100 hover:text-slate-700"
    >
      <Download className="h-4 w-4" />
    </a>
  );
}

/** A deadline that needs attention, as a small tag: red when passed, amber when close */
function DueTag({ tone, title, children }: { tone: "late" | "soon"; title: string; children: React.ReactNode }) {
  return (
    <span title={title}
          className={`inline-flex items-center gap-1 whitespace-nowrap rounded-full px-2 py-0.5 text-[11px] font-semibold ring-1 ring-inset ${
            tone === "late" ? "bg-rose-50 text-rose-700 ring-rose-200" : "bg-amber-50 text-amber-800 ring-amber-200"}`}>
      <span className={`h-1.5 w-1.5 rounded-full ${tone === "late" ? "bg-rose-500" : "bg-amber-500"}`} />
      {children}
    </span>
  );
}

/** The filing deadline on a company heading: red when passed, amber within 60 days (a finished year is grey) */
export function DueDate({ client }: { client: ClientListItem }) {
  // Today, taken once when the heading shows (the days count in whole days)
  const [now] = useState(() => Date.now());
  if (!client.accounts_due) return null;
  const days = Math.round((new Date(client.accounts_due).getTime() - now) / 86400000);
  const done = client.workbook_state === "final";
  const title = `Accounts filing deadline at Companies House for the latest year: ${ukDate(client.accounts_due)}`;
  if (!done && days < 0) return <DueTag tone="late" title={title}>Accounts overdue · due {ukDate(client.accounts_due)}</DueTag>;
  if (!done && days <= 60) return <DueTag tone="soon" title={title}>Accounts due {ukDate(client.accounts_due)} · {plural(days, "day")}</DueTag>;
  return (
    <span className={`text-[11px] ${done ? "text-slate-400" : "text-slate-500"}`} title={title}>
      Accounts due {ukDate(client.accounts_due)}
    </span>
  );
}

/** The next VAT return on a company heading: its period end and due date, amber within 14 days of the deadline */
export function VatDue({ client }: { client: ClientListItem }) {
  // Today, taken once when the heading shows (the days count in whole days)
  const [now] = useState(() => Date.now());
  if (!client.vat_due || !client.vat_period_end) return null;
  const days = Math.round((new Date(client.vat_due).getTime() - now) / 86400000);
  const title = `Next VAT return, for the period to ${ukDate(client.vat_period_end)}, worked out from the latest return entered: `
    + "due 1 month and 7 days after the period (2 months for an annual return)";
  if (days < 0) return <DueTag tone="late" title={title}>VAT return overdue · due {ukDate(client.vat_due)}</DueTag>;
  if (days <= 14) return <DueTag tone="soon" title={title}>VAT due {ukDate(client.vat_due)} · {plural(days, "day")}</DueTag>;
  return (
    <span className="text-[11px] text-slate-500" title={title}>
      VAT return to {ukDate(client.vat_period_end)} due {ukDate(client.vat_due)}
    </span>
  );
}
