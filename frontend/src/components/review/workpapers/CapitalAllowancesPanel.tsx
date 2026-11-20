"use client";

import { useEffect, useMemo, useState } from "react";
import { ChevronDown, Truck } from "lucide-react";
import { toast } from "@/lib/notify";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { CustomSelect } from "@/components/ui/custom-select";
import { api, CapitalAllowances } from "@/lib/api";
import { formatCurrency, formatDate } from "@/lib/formatters";
import { cn } from "@/lib/utils";

// Short names for the "App suggests" column (the dropdown shows the full names)
const SHORT: Record<string, string> = { AIA: "AIA", FYA: "100% FYA", MAIN: "Main pool", SPECIAL: "Special pool 6%", NONE: "None" };

/** This year's additions with the app's suggested capital allowance; the accountant picks the treatment of each one
 * (the app suggests, the accountant decides). The tax computation uses the choices after the review is run again. */
export function CapitalAllowancesPanel({ engagementId, onSaved }: { engagementId: string; onSaved?: () => void }) {
  const [data, setData] = useState<CapitalAllowances | null>(null);
  const [open, setOpen] = useState(false);
  const [edits, setEdits] = useState<Record<string, string>>({});
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    api.getCapitalAllowances(engagementId).then(setData).catch(() => setData(null));
  }, [engagementId]);

  const options = useMemo(
    () => Object.entries(data?.treatments ?? {}).map(([value, label]) => ({ value, label })),
    [data],
  );
  if (!data || data.assets.length === 0) return null;

  const choiceOf = (key: string, saved: string) => edits[key] ?? saved;
  const changedFromSuggestion = data.assets.filter((a) => choiceOf(a.key, a.choice) !== a.suggested).length;
  const unsaved = Object.keys(edits).length > 0;

  const save = async () => {
    setSaving(true);
    try {
      const next = await api.saveCapitalAllowances(engagementId, edits);
      setData(next);
      setEdits({});
      toast.success("Choices saved. Run the review again to update the tax computation.");
      onSaved?.();
    } catch (e) {
      toast.error(e instanceof Error ? e.message : "Could not save the choices");
    } finally {
      setSaving(false);
    }
  };

  return (
    <Card>
      <button
        type="button"
        onClick={() => setOpen(!open)}
        className="flex w-full flex-wrap items-center justify-between gap-3 px-5 py-4 text-left hover:bg-slate-50"
      >
        <span className="flex items-center gap-3">
          <span className="flex h-8 w-8 items-center justify-center rounded-lg bg-teal-50 text-teal-700">
            <Truck className="h-4 w-4" />
          </span>
          <span>
            <span className="block text-sm font-semibold text-slate-900">
              Capital allowances: {data.assets.length} addition{data.assets.length === 1 ? "" : "s"} this year
            </span>
            <span className="block text-[11px] text-slate-500">
              The app suggests a treatment; you choose.{changedFromSuggestion ? ` ${changedFromSuggestion} changed from the suggestion.` : ""}
            </span>
          </span>
        </span>
        <span className="inline-flex items-center gap-1 text-xs font-medium text-teal-800">
          {open ? "Hide" : "Show"} the additions
          <ChevronDown className={cn("h-3.5 w-3.5 transition", open && "rotate-180")} />
        </span>
      </button>
      {open && (
        <div className="border-t border-slate-100">
          <div>
            <table className="w-full text-xs">
              <thead className="bg-slate-50 text-[11px] uppercase tracking-wide text-slate-500">
                <tr>
                  <th className="w-28 whitespace-nowrap px-5 py-2 text-left font-semibold">Date</th>
                  <th className="px-3 py-2 text-left font-semibold">Addition (from the books)</th>
                  <th className="w-28 px-3 py-2 text-right font-semibold">Cost</th>
                  <th className="w-32 whitespace-nowrap px-3 py-2 text-left font-semibold">App suggests</th>
                  <th className="w-56 whitespace-nowrap px-5 py-2 text-left font-semibold">Your choice</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-100">
                {data.assets.map((a) => {
                  const choice = choiceOf(a.key, a.choice);
                  const changed = choice !== a.suggested;
                  return (
                    <tr key={a.key} className={cn(changed && "bg-amber-50/60")}>
                      <td className="whitespace-nowrap px-5 py-2 text-slate-600">{a.when ? formatDate(a.when, "short") : "-"}</td>
                      <td className="px-3 py-2 text-slate-800">
                        <span className="block max-w-xs truncate" title={a.description}>{a.description}</span>
                        <span className="text-[11px] text-slate-400">{a.group}</span>
                      </td>
                      <td className="whitespace-nowrap px-3 py-2 text-right font-mono">{formatCurrency(a.cost)}</td>
                      <td className="whitespace-nowrap px-3 py-2 text-slate-600">{SHORT[a.suggested] ?? a.suggested}</td>
                      <td className="px-5 py-2">
                        <CustomSelect
                          fullWidth
                          size="sm"
                          value={choice}
                          options={options}
                          onChange={(v) => setEdits((e) => ({ ...e, [a.key]: v }))}
                        />
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
          <div className="flex flex-wrap items-end justify-between gap-4 border-t border-slate-100 px-5 py-4">
            <div className="space-y-2 text-xs text-slate-600">
              {data.crosses_april_2026 && (
                <p>Main pool rate: this year crosses 1 April 2026, so 18% for the days before and 14% after (HMRC CA23222).</p>
              )}
              <p className="text-[11px] text-slate-500">
                Allowances now: {data.allowances.map((x) => `${x.label} ${formatCurrency(x.amount)}`).join(" · ") || "none"}
              </p>
            </div>
            <Button size="sm" onClick={save} disabled={!unsaved || saving}>
              {saving ? "Saving…" : "Save choices"}
            </Button>
          </div>
        </div>
      )}
    </Card>
  );
}
