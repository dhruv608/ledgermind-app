// Last year's trial balance lines with no code: the code each was given, to check or change.

import { BooksOpeningLine } from "@/lib/api";
import { formatCurrency } from "@/lib/formatters";
import { cn } from "@/lib/utils";
import { Chart, Empty, matches } from "./common";
import { HeadPicker } from "./HeadPicker";

/** Last year's TB lines that had a name and no code: the code each was given (the mapping a trial balance gets), to
 *  check or change. They open the books, so a change moves the opening balance to the code picked. */
export function OpeningList({ lines, chart, onlyToCheck, search, saving, onChoose }: {
  lines: BooksOpeningLine[];
  chart: Chart;
  onlyToCheck: boolean;
  search: string;
  saving: string | null;
  onChoose: (key: string, value: Record<string, unknown> | null) => void;
}) {
  const shown = lines.filter((l) => (!onlyToCheck || (!l.sure && !l.chosen)) && (!search || matches(l.name, search)));
  if (!shown.length) return <Empty text={onlyToCheck ? "Every line of last year's TB has its code." : "No lines match."} />;
  return (
    <div className="overflow-x-auto">
      <table className="w-full min-w-[640px] text-xs">
        <thead>
          <tr className="border-b border-slate-100 text-left text-[11px] uppercase tracking-wide text-slate-500">
            <th className="px-5 py-2 font-medium">Account in last year&apos;s TB</th>
            <th className="px-3 py-2 text-right font-medium">Debit</th>
            <th className="px-3 py-2 text-right font-medium">Credit</th>
            <th className="w-[18rem] px-3 py-2 font-medium">Code</th>
            <th className="px-5 py-2 font-medium">Why</th>
          </tr>
        </thead>
        <tbody>
          {shown.map((l) => (
            <tr key={l.key} className={cn("border-b border-slate-50 align-top", !l.sure && !l.chosen && "bg-amber-50/50")}>
              <td className="px-5 py-2.5 font-medium text-slate-800">{l.name}</td>
              <td className="px-3 py-2.5 text-right tabular-nums">{l.amount > 0 ? formatCurrency(l.amount, { currencySymbol: "" }) : ""}</td>
              <td className="px-3 py-2.5 text-right tabular-nums">{l.amount < 0 ? formatCurrency(-l.amount, { currencySymbol: "" }) : ""}</td>
              <td className="px-3 py-2">
                <HeadPicker value={l.picked} code={l.code} choices={[]} chart={chart} disabled={saving === l.key} onPick={(choice) => onChoose(l.key, choice)} />
              </td>
              <td className="px-5 py-2.5 text-slate-600">
                {l.chosen ? "Chosen by the accountant" : l.why}
                {l.chosen && (
                  <button type="button" className="ml-2 text-teal-700 hover:underline" onClick={() => onChoose(l.key, null)}>Undo</button>
                )}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
