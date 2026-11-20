// The AI's suggested codes, one row per payee, each used for all of the payee's lines with one click.

import { useMemo } from "react";
import { Loader2 } from "lucide-react";
import { Button } from "@/components/ui/button";
import { BooksBankRow } from "@/lib/api";
import { formatCurrency } from "@/lib/formatters";
import { cn } from "@/lib/utils";
import { Chart, Empty } from "./common";

/** The AI's suggestions, one row per payee (not one per line): its lines, the money, the code the AI
 *  picked, how sure, its reason, and Use it, which codes every line from the payee. Lines already coded drop out. */
export function AiSuggestions({ rows, chart, saving, onChoose }: {
  rows: BooksBankRow[];
  chart: Chart;
  saving: string | null;
  onChoose: (key: string, value: Record<string, unknown> | null) => void;
}) {
  const groups = useMemo(() => {
    const by = new Map<string, { key: string; name: string; rows: BooksBankRow[] }>();
    for (const r of rows) {
      if (!r.ai || r.chosen || !r.check) continue;
      const key = r.payee ? `payee:${r.payee}` : r.key;
      const g = by.get(key) || { key, name: r.payee || r.description, rows: [] };
      g.rows.push(r);
      by.set(key, g);
    }
    return Array.from(by.values()).sort((a, b) =>
      b.rows.reduce((s, r) => s + r.money_out + r.money_in, 0) - a.rows.reduce((s, r) => s + r.money_out + r.money_in, 0));
  }, [rows]);
  if (!groups.length) return <Empty text="No AI suggestions left: every suggested line is coded." />;
  const codeName = (code: number) => (chart.find((c) => c.code === code)?.name || "").replace(/\s*\(.*\)$/, "");
  return (
    <div className="text-xs">
      <p className="border-b border-slate-100 px-5 py-2.5 text-[11px] text-slate-500">
        One row per payee. <span className="font-semibold text-slate-700">Use it</span> codes all of the payee&apos;s lines;
        if you disagree, skip it and code the lines on the Bank tab.
      </p>
      <table className="w-full">
        <thead className="border-b border-slate-200 bg-slate-50 text-[11px] uppercase tracking-wide text-slate-500">
          <tr className="text-left">
            <th className="px-5 py-2.5 font-semibold">Payee</th>
            <th className="px-3 py-2.5 text-right font-semibold">Lines</th>
            <th className="px-3 py-2.5 text-right font-semibold">Total</th>
            <th className="px-3 py-2.5 font-semibold">AI suggests</th>
            <th className="px-3 py-2.5 font-semibold">Why</th>
            <th className="w-24 px-5 py-2.5" />
          </tr>
        </thead>
        <tbody className="divide-y divide-slate-100">
          {groups.map((g) => {
            const ai = g.rows[0].ai!;
            const total = g.rows.reduce((s, r) => s + r.money_in - r.money_out, 0);
            const busy = saving === g.key || g.rows.some((r) => saving === r.key);
            return (
              <tr key={g.key} className="align-top transition-colors hover:bg-teal-50/40">
                <td className="px-5 py-2.5">
                  <p className="font-medium text-slate-800">{g.rows[0].description}</p>
                  <p className="text-[11px] text-slate-500">{g.rows[0].account}{g.rows.length > 1 ? ` · ${g.name}` : ""}</p>
                </td>
                <td className="px-3 py-2.5 text-right tabular-nums text-slate-700">{g.rows.length}</td>
                <td className={cn("whitespace-nowrap px-3 py-2.5 text-right font-medium tabular-nums", total > 0 ? "text-emerald-700" : "text-slate-800")}>
                  {formatCurrency(total)}
                </td>
                <td className="px-3 py-2.5">
                  <p className="font-semibold text-slate-900">{String(ai.code).padStart(4, "0")} {codeName(ai.code)}</p>
                  {ai.sure === "low" && <span className="mt-0.5 inline-block rounded-full bg-amber-50 px-1.5 py-px text-[10px] font-semibold text-amber-800 ring-1 ring-inset ring-amber-200">not sure</span>}
                </td>
                <td className="max-w-[22rem] px-3 py-2.5 leading-relaxed text-slate-600">{ai.reason}</td>
                <td className="px-5 py-2.5 text-right">
                  {busy ? (
                    <Loader2 className="ml-auto h-4 w-4 animate-spin text-slate-400" />
                  ) : (
                    <Button size="sm" variant="primary" className="h-7 px-3 text-xs" onClick={() => onChoose(g.key, { code: ai.code })}>
                      Use it
                    </Button>
                  )}
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}
