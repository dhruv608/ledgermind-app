// The picker for what a line is: a special head or any code of the chart.

import { useMemo } from "react";
import { CustomSelect } from "@/components/ui/custom-select";
import { Chart } from "./common";

export const PICKER_FILTERS = [
  { id: "pl", label: "P&L" },
  { id: "bs", label: "Balance sheet" },
];
// The heads that do more than put the line on one code; every other type is picked by its code in the chart
export const SPECIAL: Record<string, string> = {
  "Sales (no invoice)": "Takings with no sales invoice: to sales",
  "Purchases (no bill)": "Goods with no Dext bill: 1100 or 1400, as last year",
  "Transfer between own accounts": "9998, matched with the same money on the other account",
  "Ask the client": "Suspense for now, and a question for the client",
};

/** The value a pick saves: {head} for a special head, {code} for any code of the chart. */
export function choiceOf(v: string): Record<string, unknown> {
  return v.startsWith("code:") ? { code: Number(v.slice(5)) } : { head: v.slice(5) };
}

export function HeadPicker({ value, code, choices, chart, disabled, onPick }: {
  value: string;
  /** The line's code: a choice made earlier with a head that is now picked by code shows as that code */
  code: number | null;
  choices: string[];
  chart: Chart;
  disabled?: boolean;
  onPick: (choice: Record<string, unknown>) => void;
}) {
  const shownValue = value.startsWith("head:") && !(value.slice(5) in SPECIAL) && code !== null ? `code:${code}` : value;
  const options = useMemo(() => [
    ...choices.filter((c) => c in SPECIAL).map((c) => ({ value: `head:${c}`, label: c, description: SPECIAL[c], group: "Special" })),
    ...chart.map((a) => ({
      value: `code:${a.code}`,
      label: `${String(a.code).padStart(4, "0")} ${a.name}`,
      description: a.section,
      group: a.extended ? "Full chart (more codes)" : "Firm chart",
      tags: [a.pl ? "pl" : "bs"],
    })),
  ], [choices, chart]);
  return (
    <CustomSelect
      size="sm"
      fullWidth
      searchable
      searchPlaceholder="Type a code or name"
      filters={PICKER_FILTERS}
      value={shownValue}
      disabled={disabled}
      placeholder="Record as…"
      onChange={(v) => v && onPick(choiceOf(String(v)))}
      options={options}
      menuClassName="left-auto right-0 w-[20rem] max-w-[calc(100vw-2rem)]"
      align="right"
    />
  );
}
