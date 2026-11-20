"use client";

// Foster, kinship and shared lives care on the Self-employment page (qualifying care relief, R-SP-01): the care
// payments for the year (from the council's letter, or typed), the people cared for with their weeks, and the result:
// under the limit not taxed; over it, the simplified method or the normal method (an accountant's choice).
import { useEffect, useState } from "react";
import { toast } from "@/lib/notify";
import { Trash2 } from "lucide-react";
import { api, SaFosterView } from "@/lib/api";
import { Input } from "@/components/ui/input";
import { CustomSelect } from "@/components/ui/custom-select";
import { AddButton, AddPopup, NUM, PopupField, TABLE_WRAP, THEAD, TROW } from "@/components/sa/SaChrome";

const money = (v: number) => `£${v.toLocaleString("en-GB", { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
const BANDS = [{ value: "UNDER_11", label: "Child under 11" }, { value: "ELEVEN_PLUS", label: "Child 11 or over" },
               { value: "ADULT", label: "Adult" }];

export function SaFosterCare({ jobId, onChange }: { jobId: string; onChange?: () => void }) {
  const [view, setViewState] = useState<SaFosterView | null>(null);
  const [adding, setAdding] = useState(false);
  const [label, setLabel] = useState("");
  const [band, setBand] = useState("ELEVEN_PLUS");
  const [weeks, setWeeks] = useState("52");
  const [receipts, setReceipts] = useState("");
  const setView = (v: SaFosterView) => { setViewState(v); onChange?.(); };
  useEffect(() => { api.getSaFoster(jobId).then(setViewState).catch(() => {}); }, [jobId]);
  if (!view) return null;
  // Shown once there are care payments (a letter read, or typed), or a placement
  if (view.receipts === null && !view.placements.length && !adding) {
    return (
      <div className="text-right">
        <button type="button" onClick={() => setAdding(true)} className="text-[12px] font-medium text-teal-700 hover:underline">
          Foster, kinship or shared lives care? Add it
        </button>
      </div>
    );
  }
  const save = (patch: Partial<{ receipts: number | null; carers: number; method: string | null; actual_costs: number | null }>) =>
    api.putSaFoster(jobId, { receipts: view.typed ? view.receipts : null, carers: view.carers, method: view.method,
                            actual_costs: view.actual_costs, ...patch }).then(setView).catch((e) => toast.error("Not saved", { description: e.message }));
  const add = () => {
    const w = parseInt(weeks, 10);
    if (!w || w < 1 || w > 53) return toast.error("Weeks from 1 to 53 (a part week is a full week)");
    api.addSaPlacement(jobId, { label: label.trim(), band, weeks: w })
      .then((v) => { setView(v); setLabel(""); setWeeks("52"); }).catch((e) => toast.error("Not added", { description: e.message }));
  };

  return (
    <div className={TABLE_WRAP}>
      <div className="flex items-start justify-between gap-3 px-4 py-3">
        <div>
          <h3 className="text-sm font-semibold text-slate-900">Foster, kinship or shared lives care</h3>
          <p className="text-[12px] text-slate-500">Qualifying care relief: payments up to the limit are not taxed (R-SP-01).</p>
        </div>
        <AddButton onClick={() => setAdding(true)}>Add person cared for</AddButton>
      </div>
      <div className="grid gap-3 border-t border-slate-100 px-4 py-3 text-[13px] sm:grid-cols-3">
        <label className="space-y-1">
          <span className="block text-xs font-semibold text-slate-700">Care payments for the year</span>
          <Input type="number" min="0" step="0.01" className="h-8 text-sm" placeholder={view.from_letters !== null ? String(view.from_letters) : "0.00"}
                 value={receipts} onChange={(e) => setReceipts(e.target.value)}
                 onBlur={() => receipts !== "" && save({ receipts: Number(receipts) })} />
          <span className="block text-[11px] text-slate-500">
            {view.typed ? "Typed" : view.from_letters !== null ? `From the council's letter: ${money(view.from_letters)}` : "Not read from a letter"}
          </span>
        </label>
        <label className="space-y-1">
          <span className="block text-xs font-semibold text-slate-700">Carers in the household</span>
          <CustomSelect value={String(view.carers)} onChange={(v) => save({ carers: Number(v) })} title="Carers"
                        options={[1, 2, 3].map((n) => ({ value: String(n), label: n === 1 ? "1 (the fixed amount in full)" : `${n} (sharing the fixed amount)` }))} />
        </label>
        <div className="space-y-1">
          <span className="block text-xs font-semibold text-slate-700">Result</span>
          <p className="text-slate-800">
            {view.limit === null ? "Add the people cared for to work out the limit"
              : view.exempt ? `Under the limit of ${money(view.limit)}: not taxed`
              : `Over the limit of ${money(view.limit)}: ${money(view.profit)} taxed`}
          </p>
        </div>
      </div>
      {view.exempt === false && (
        <div className="flex flex-wrap items-center gap-3 border-t border-slate-100 px-4 py-3 text-[13px]">
          <span className="text-xs font-semibold text-slate-700">Method</span>
          <CustomSelect value={view.method || ""} onChange={(v) => save({ method: v || null })} title="Method"
                        options={[{ value: "", label: "Choose a method" }, { value: "SIMPLIFIED", label: "Simplified (payments less the limit)" },
                                  { value: "ACTUAL", label: "Normal (payments less the actual costs)" }]} />
          {view.method === "ACTUAL" && (
            <Input type="number" min="0" step="0.01" className="h-8 w-40 text-sm" placeholder="Actual costs"
                   defaultValue={view.actual_costs ?? ""} onBlur={(e) => save({ actual_costs: Number(e.target.value) || 0 })} />
          )}
        </div>
      )}
      {view.placements.length > 0 && (
        <table className="w-full border-t border-slate-100 text-[13px]">
          <thead className={THEAD}><tr><th className="px-4 py-2 text-left">Person cared for</th><th className="px-4 py-2 text-left">Age</th>
            <th className="px-4 py-2 text-right">Weeks</th><th className="w-10" /></tr></thead>
          <tbody className="divide-y divide-slate-100">
            {view.placements.map((p) => (
              <tr key={p.id} className={TROW}>
                <td className="px-4 py-2">{p.label || "Placement"}</td>
                <td className="px-4 py-2">{BANDS.find((b) => b.value === p.band)?.label}</td>
                <td className={`px-4 py-2 text-right ${NUM}`}>{p.weeks}</td>
                <td className="px-2 py-2 text-right">
                  <button type="button" title="Remove" onClick={() => api.removeSaPlacement(jobId, p.id).then(setView)}
                          className="rounded p-1 text-slate-400 hover:bg-slate-100 hover:text-rose-600"><Trash2 className="h-3.5 w-3.5" /></button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
      <AddPopup open={adding} onClose={() => setAdding(false)} onAdd={add} title="Add a person cared for"
                description="From the placement dates: count a part week as a full week.">
        <PopupField label="Name or reference (optional)" wide>
          <Input value={label} onChange={(e) => setLabel(e.target.value)} placeholder="e.g. Child A" className="h-9 text-sm" />
        </PopupField>
        <PopupField label="Age">
          <CustomSelect value={band} onChange={setBand} title="Age" options={BANDS} />
        </PopupField>
        <PopupField label="Weeks in the tax year">
          <Input type="number" min="1" max="53" value={weeks} onChange={(e) => setWeeks(e.target.value)} className="h-9 text-sm" />
        </PopupField>
      </AddPopup>
    </div>
  );
}
