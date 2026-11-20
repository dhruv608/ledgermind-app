"use client";

import { useState } from "react";
import { Columns3 } from "lucide-react";
import { CustomSelect } from "@/components/ui/custom-select";
import type { ColumnLayout } from "@/lib/api";
import { cn } from "@/lib/utils";

const letter = (i: number) => (i < 26 ? String.fromCharCode(65 + i) : `${String.fromCharCode(64 + Math.floor(i / 26))}${String.fromCharCode(65 + (i % 26))}`);
const shown = (v: string | number | null) => (v === null || v === "" ? "" : typeof v === "number" ? v.toLocaleString("en-GB", { maximumFractionDigits: 2 }) : String(v));

/** What still has to be chosen before the file can be read ([] when it can). */
export function columnsMissing(layout: ColumnLayout, mapping: Record<string, number>): string[] {
  const has = (f: string) => mapping[f] !== undefined;
  const need: string[] = [];
  if (layout.role === "TB") {
    if (!has("name")) need.push("Account name");
    if (!((has("debit") && has("credit")) || has("balance"))) need.push("Debit and Credit (or Balance)");
  } else {
    if (!has("account")) need.push("Account");
    if (!has("date")) need.push("Date");
    if (!((has("debit") && has("credit")) || has("amount"))) need.push("Debit and Credit (or Amount)");
  }
  return need;
}

/** A TB or ledger the usual Xero / QuickBooks readers do not know (Sage, or any Excel): which column is what. The app
 *  fills in its guess, or a layout saved earlier; the accountant checks it and changes a column if needed. */
export function ColumnPicker({ filename, layout, mapping, onChange }: {
  filename: string;
  layout: ColumnLayout;
  mapping: Record<string, number>;
  onChange: (mapping: Record<string, number>) => void;
}) {
  const [open, setOpen] = useState(!layout.known);
  const columnOf = Object.fromEntries(Object.entries(mapping).map(([f, i]) => [i, f]));
  const labelOf = Object.fromEntries(layout.fields.map((f) => [f.id, f.label]));
  const columnOptions = [
    { value: "", label: "Not in this file" },
    ...layout.headers.map((h, i) => ({ value: String(i), label: `${letter(i)} · ${h || "(no heading)"}` })),
  ];
  const pick = (field: string, value: string) => {
    const next = { ...mapping };
    delete next[field];
    if (value !== "") {
      const col = Number(value);
      for (const [f, i] of Object.entries(next)) if (i === col) delete next[f];   // one column, one meaning
      next[field] = col;
    }
    onChange(next);
  };
  const need = columnsMissing(layout, mapping);
  const what = layout.role === "TB" ? "trial balance" : "ledger";

  return (
    <div className="rounded-xl border border-teal-200 bg-white">
      <div className="flex flex-wrap items-center justify-between gap-2 border-b border-teal-100 bg-teal-50/50 px-3 py-2">
        <p className="flex min-w-0 items-center gap-1.5 text-xs font-semibold text-slate-800">
          <Columns3 className="h-3.5 w-3.5 shrink-0 text-teal-700" />
          <span className="truncate">Columns in {filename.replace(/\.xlsx$/i, "")}</span>
          {layout.software === "SAGE" && <span className="rounded bg-white px-1.5 py-0.5 text-[10px] font-semibold text-teal-800">Sage</span>}
        </p>
        {layout.known && (
          <button type="button" onClick={() => setOpen(!open)} className="text-[11px] font-medium text-teal-700 hover:underline">
            {open ? "Hide" : "Change"}
          </button>
        )}
      </div>
      {!open ? (
        <p className="px-3 py-2 text-[11px] text-slate-600">Read with the layout you confirmed before for this {what}.</p>
      ) : (
        <div className="space-y-3 p-3">
          <p className="text-[11px] text-slate-500">
            The app has filled these in from the headings. Check them and change one if it is wrong: this layout is then
            remembered, and the next file like it is read without asking.
          </p>
          <div className="grid gap-x-4 gap-y-2 sm:grid-cols-2">
            {layout.fields.map((f) => (
              <label key={f.id} className="flex items-center justify-between gap-2 text-xs">
                <span className={cn("shrink-0 font-medium", f.required ? "text-slate-800" : "text-slate-600")}>
                  {f.label}{f.required && <span className="text-amber-600"> *</span>}
                </span>
                <CustomSelect
                  size="sm"
                  align="right"
                  className="min-w-0 max-w-[60%] flex-1"
                  fullWidth
                  value={mapping[f.id] !== undefined ? String(mapping[f.id]) : ""}
                  onChange={(v) => pick(f.id, String(v))}
                  options={columnOptions}
                />
              </label>
            ))}
          </div>
          {need.length > 0 && <p className="text-[11px] font-medium text-amber-800">Still to choose: {need.join(", ")}.</p>}
          {/* The first lines of the file, with the chosen columns marked */}
          <div className="overflow-x-auto rounded-lg border border-slate-200">
            <table className="w-full min-w-max text-left text-[11px]">
              <thead>
                <tr className="bg-slate-50">
                  {layout.headers.map((h, i) => (
                    <th key={i} className={cn("whitespace-nowrap px-2 py-1.5 font-semibold", columnOf[i] ? "bg-teal-50 text-teal-800" : "text-slate-400")}>
                      <span className="block text-[10px] uppercase tracking-wide">{columnOf[i] ? labelOf[columnOf[i]] : "—"}</span>
                      <span className="font-normal">{letter(i)} · {h || "(no heading)"}</span>
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {layout.preview.map((r, n) => (
                  <tr key={n} className="border-t border-slate-100">
                    {layout.headers.map((_, i) => (
                      <td key={i} className={cn("max-w-[14rem] truncate whitespace-nowrap px-2 py-1", columnOf[i] ? "text-slate-800" : "text-slate-400")}>
                        {shown(r[i] ?? null)}
                      </td>
                    ))}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}
    </div>
  );
}
