"use client";

// Self-employment (SA103), in the company workspace's parts: the header card with the figures, then each business with
// its income and costs under the SA103 headings (the part not allowed beside each cost) and its adjusted profit
// computation as TaxCalc sets it out: accounts profit, add back what is not allowed, simplified expenses, capital
// allowances or the trading allowance, last year's loss, taxable profit.
import { useEffect, useState } from "react";
import { toast } from "@/lib/notify";
import { AlertTriangle, Plus, Store, Trash2 } from "lucide-react";
import { api, SaBalanceSheet, SaBusinessRow, SaBusinessSettings, SaTradeView } from "@/lib/api";
import { Button } from "@/components/ui/button";
import { Modal } from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { CustomSelect } from "@/components/ui/custom-select";
import { AddButton, AddPopup, NUM, PopupField, SaHead, TABLE_WRAP, THEAD, TROW, text } from "@/components/sa/SaChrome";
import { SaTradeBank } from "@/components/sa/SaTradeBank";
import { SaFosterCare } from "@/components/sa/SaFosterCare";
import { cn } from "@/lib/utils";

const money = (v: number) => {
  const s = `£${Math.abs(v).toLocaleString("en-GB", { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
  return v < 0 ? `(${s})` : s;
};
const num = (s: string) => parseFloat(s.replace(/[£,]/g, ""));

function Setting({ label, value, onSave, suffix }: { label: string; value: number | null; onSave: (v: number) => void; suffix?: string }) {
  return (
    <label className="flex items-center justify-between gap-3 text-xs text-slate-600">
      <span>{label}</span>
      <span className="flex items-center gap-1">
        <input key={String(value)} defaultValue={value || ""} inputMode="decimal"
               onBlur={(e) => { const v = num(e.target.value || "0"); if (!isNaN(v) && v !== (value || 0)) onSave(v); }}
               className={cn("w-24 rounded-md border border-slate-300 bg-white px-2 py-1 text-right", NUM)} />
        {suffix && <span className="w-12 text-slate-400">{suffix}</span>}
      </span>
    </label>
  );
}

const CA_KINDS = [
  { value: "AIA", label: "Annual Investment Allowance (100%)" }, { value: "MAIN", label: "Main pool: value (18%)" },
  { value: "SPECIAL", label: "Special rate pool: value (6%)" }, { value: "ZEC", label: "Zero-emission car (100%)" },
  { value: "FYA", label: "Other 100% allowance" }, { value: "SBA", label: "Structures and buildings: cost (3%)" },
  { value: "BALANCING", label: "Balancing allowance" },
];

// Capital allowances line by line (AIA, the pools, cars...): the total replaces the single figure, and the return gets
// each under its own box. A pool's value is brought forward plus additions less disposals.
function Allowances({ jobId, row, onChange }: { jobId: string; row: SaBusinessRow; onChange: (v: SaTradeView) => void }) {
  const [kind, setKind] = useState("AIA");
  const [desc, setDesc] = useState("");
  const [amount, setAmount] = useState("");
  const [priv, setPriv] = useState("");
  const [open, setOpen] = useState(false);
  const add = async () => {
    const a = num(amount);
    if (isNaN(a)) return toast.error("Enter the cost or pool value");
    try {
      onChange(await api.addSaAllowance(jobId, row.id, { kind, description: desc.trim(), amount: a, private_use: (num(priv || "0") || 0) / 100 }));
      setDesc(""); setAmount(""); setPriv("");
    } catch (e: any) { toast.error("Not added", { description: e.message }); }
  };
  const remove = async (id: number) => {
    try { onChange(await api.deleteSaAllowance(jobId, row.id, id)); } catch (e: any) { toast.error("Not removed", { description: e.message }); }
  };
  return (
    <div className="border-t border-slate-200">
      <div className="flex items-center justify-between gap-3 px-4 pt-3">
        <p className={text.label}>Capital allowances</p>
        <AddButton onClick={() => setOpen(true)}>Add allowance</AddButton>
      </div>
      <table className="mt-1 w-full table-fixed text-xs">
        <thead className={THEAD}>
          <tr className="text-left">
            <th className="px-4 py-2 font-semibold">Kind</th>
            <th className="w-[18%] px-3 py-2 font-semibold">Description</th>
            <th className="w-24 px-3 py-2 text-right font-semibold">Cost / pool</th>
            <th className="w-16 px-3 py-2 text-right font-semibold">Private</th>
            <th className="w-24 px-3 py-2 text-right font-semibold">Allowance</th>
            <th className="w-24 px-3 py-2 text-right font-semibold">Pool c/f</th>
            <th className="w-10" />
          </tr>
        </thead>
        <tbody className="divide-y divide-slate-100">
          {row.allowances.length === 0 && <tr><td colSpan={7} className="px-4 py-2 text-slate-500">None by kind: the single figure below is used.</td></tr>}
          {row.allowances.map((a) => (
            <tr key={a.id} className={TROW}>
              <td className="truncate px-4 py-2 text-slate-800">{a.label}</td>
              <td className="truncate px-3 py-2 text-slate-600">{a.description || "—"}</td>
              <td className={cn("px-3 py-2 text-right", NUM)}>{money(a.amount)}</td>
              <td className={cn("px-3 py-2 text-right", NUM)}>{a.private_use ? `${Math.round(a.private_use * 100)}%` : "—"}</td>
              <td className={cn("px-3 py-2 text-right font-semibold", NUM)}>{money(a.allowance)}</td>
              <td className={cn("px-3 py-2 text-right text-slate-500", NUM)}>{a.pool_cf ? money(a.pool_cf) : "—"}</td>
              <td className="px-2 py-2 text-right">
                <button type="button" onClick={() => remove(a.id)} title="Remove" className="rounded p-1 text-slate-400 hover:bg-rose-50 hover:text-rose-600 cursor-pointer"><Trash2 className="h-3 w-3" /></button>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
      <AddPopup open={open} onClose={() => setOpen(false)} onAdd={add} title={`Add a capital allowance: ${row.name}`}
                description="A pool's value is brought forward plus additions less disposals: the allowance is worked out from it. Private use cuts the allowance, not the pool.">
        <PopupField label="Kind" wide><CustomSelect fullWidth value={kind} onChange={setKind} options={CA_KINDS} /></PopupField>
        <PopupField label="Description" wide><Input value={desc} onChange={(e) => setDesc(e.target.value)} placeholder="Van, tools, laptop..." /></PopupField>
        <PopupField label="Cost or pool value (£)"><Input value={amount} onChange={(e) => setAmount(e.target.value)} inputMode="decimal" /></PopupField>
        <PopupField label="Private use %"><Input value={priv} onChange={(e) => setPriv(e.target.value)} placeholder="0" inputMode="decimal" /></PopupField>
      </AddPopup>
    </div>
  );
}

// The trade's small balance sheet from the bank (SEF 5): what it has at the end, the capital account that explains it,
// and the check that the two agree (every bank line is in one or the other)
function BalanceSheet({ bs }: { bs: SaBalanceSheet }) {
  const c = bs.capital;
  const lines: [string, number, boolean?][] = [
    ["Capital at the start (bank balances)", c.opening], ["Add profit (from the bank)", c.profit],
    ["Add money put in", c.introduced], ["Less drawings", -c.drawings],
    ...(c.transfers ? [["Less moved to other own accounts", -c.transfers] as [string, number]] : []),
    ...(c.loans_repaid ? [["Less loans or HP repaid", -c.loans_repaid] as [string, number]] : []),
    ...(c.loans_received ? [["Add loans received", -c.loans_received] as [string, number]] : []),
    ...(c.vat ? [["Less VAT paid (net of refunds)", -c.vat] as [string, number]] : []),
    ...(c.assets_bought ? [["Less capital assets bought", -c.assets_bought] as [string, number]] : []),
    ...(c.unsorted ? [["Less lines not sorted yet", -c.unsorted] as [string, number]] : []),
    ["Capital at the end", c.closing, true],
  ];
  return (
    <div className="border-t border-slate-200 px-4 py-3">
      <div className="flex items-center justify-between gap-2">
        <p className={text.label}>Balance sheet at {bs.period.end.split("-").reverse().join("/")}</p>
        <span className={cn("rounded-full px-2 py-px text-[10.5px] font-semibold", bs.balances ? "bg-teal-50 text-teal-800" : "bg-amber-50 text-amber-800")}>
          {bs.balances ? "Agrees with the bank" : `Differs by ${money(bs.difference)}`}
        </span>
      </div>
      <div className="mt-2 grid grid-cols-1 gap-x-8 gap-y-3 text-xs md:grid-cols-2">
        <dl className="space-y-1">
          {bs.assets.map((a) => (
            <div key={a.name} className="flex justify-between gap-3 text-slate-700"><dt className={a.movement_only ? "text-slate-500" : ""}>{a.name}</dt><dd className={NUM}>{money(a.amount)}</dd></div>
          ))}
          <div className="flex justify-between gap-3 border-t border-slate-200 pt-1 font-semibold text-slate-900"><dt>Net business assets</dt><dd className={NUM}>{money(bs.net_assets)}</dd></div>
        </dl>
        <dl className="space-y-1">
          {lines.map(([k, v, strong]) => (
            <div key={k} className={cn("flex justify-between gap-3", strong ? "border-t border-slate-200 pt-1 font-semibold text-slate-900" : "text-slate-700")}>
              <dt>{k}</dt><dd className={NUM}>{money(v)}</dd>
            </div>
          ))}
        </dl>
      </div>
      {bs.notes.length > 0 && (
        <div className="mt-2 space-y-0.5 text-[11.5px] text-amber-900">
          {bs.notes.map((n) => <p key={n} className="flex gap-1.5"><AlertTriangle className="mt-px h-3.5 w-3.5 shrink-0" />{n}</p>)}
        </div>
      )}
    </div>
  );
}

function Business({ jobId, row, view, onChange }: { jobId: string; row: SaBusinessRow; view: SaTradeView; onChange: (v: SaTradeView) => void }) {
  const [heading, setHeading] = useState("TURNOVER");
  const [desc, setDesc] = useState("");
  const [amount, setAmount] = useState("");
  const [disallowed, setDisallowed] = useState("");
  const [adding, setAdding] = useState(false);
  const isIncome = view.headings[heading]?.kind === "income";

  const add = async () => {
    const a = num(amount);
    if (isNaN(a)) return toast.error("Enter an amount");
    try {
      onChange(await api.addSaTradeItem(jobId, row.id, { heading, amount: a, disallowed: isIncome ? 0 : num(disallowed || "0") || 0, description: desc.trim() }));
      setDesc(""); setAmount(""); setDisallowed("");
    } catch (e: any) { toast.error("Not added", { description: e.message }); }
  };
  const save = async (patch: Partial<SaBusinessSettings>) => {
    try { onChange(await api.editSaBusiness(jobId, row.id, patch)); } catch (e: any) { toast.error("Not saved", { description: e.message }); }
  };
  const remove = async (itemId: number) => {
    try { onChange(await api.deleteSaTradeItem(jobId, row.id, itemId)); } catch (e: any) { toast.error("Not removed", { description: e.message }); }
  };

  const ta = row.settings.use_trading_allowance;
  const comp: [string, number, boolean?][] = ta ? [
    ["Turnover and other income", row.income],
    ["Less trading allowance", -row.trading_allowance],
    ...(row.balancing_charges ? [["Add balancing charges", row.balancing_charges] as [string, number]] : []),
    ["Adjusted profit", row.adjusted_profit, true],
  ] : [
    ["Net profit per the accounts", row.accounts_profit],
    ...(row.disallowed ? [["Add costs not allowed", row.disallowed] as [string, number]] : []),
    ...(row.use_of_home ? [["Less use of home (flat rate)", -row.use_of_home] as [string, number]] : []),
    ...(row.mileage ? [["Less mileage (flat rate)", -row.mileage] as [string, number]] : []),
    ...(row.capital_allowances ? [["Less capital allowances", -row.capital_allowances] as [string, number]] : []),
    ...(row.balancing_charges ? [["Add balancing charges", row.balancing_charges] as [string, number]] : []),
    ["Adjusted profit", row.adjusted_profit, true],
  ];
  if (row.losses_used) comp.push(["Less loss brought forward", -row.losses_used]);
  comp.push(["Taxable profit", row.taxable_profit, true]);

  return (
    <section className={TABLE_WRAP}>
      <div className="flex flex-wrap items-center justify-between gap-3 border-b border-slate-200 px-4 py-3">
        <div className="flex items-center gap-2">
          <Store className="h-4 w-4 text-teal-700" />
          <h3 className={text.card}>{row.name}</h3>
          <span className="rounded-full bg-slate-100 px-2 py-px text-[10.5px] font-bold text-slate-600">{row.page}</span>
        </div>
        <p className="text-xs text-slate-500">Taxable profit <span className={cn("font-semibold text-slate-900", NUM)}>{money(row.taxable_profit)}</span></p>
      </div>

      {row.warnings.length > 0 && (
        <div className="border-b border-amber-200 bg-amber-50 px-4 py-2 space-y-1">
          {row.warnings.map((w) => <p key={w} className="flex gap-1.5 text-xs text-amber-900"><AlertTriangle className="mt-px h-3.5 w-3.5 shrink-0" />{w}</p>)}
        </div>
      )}

      <div className="grid grid-cols-1 xl:grid-cols-[minmax(0,1fr)_19rem]">
        <div className="min-w-0">
          <div className="flex items-center justify-between gap-3 px-4 py-2">
            <p className={text.label}>Income and costs</p>
            <AddButton onClick={() => setAdding(true)}>Add income or cost</AddButton>
          </div>
          <table className="w-full table-fixed text-xs">
            <thead className={THEAD}>
              <tr className="text-left">
                <th className="px-4 py-2 font-semibold">Heading</th>
                <th className="w-[28%] px-3 py-2 font-semibold">Description</th>
                <th className="w-28 px-3 py-2 text-right font-semibold">Amount</th>
                <th className="w-28 px-3 py-2 text-right font-semibold">Not allowed</th>
                <th className="w-10" />
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-100">
              {row.items.length === 0 && <tr><td colSpan={5} className="px-4 py-3 text-slate-500">No income or costs yet: use Add income or cost, or the bank statements below.</td></tr>}
              {row.items.map((i) => {
                const h = view.headings[i.heading];
                return (
                  <tr key={i.id} className={TROW}>
                    <td className="truncate px-4 py-2 font-medium text-slate-800" title={`Box ${h?.box}: ${h?.label}`}>
                      <span className="mr-1.5 text-slate-400">{h?.box}</span>{h?.label}
                    </td>
                    <td className="truncate px-3 py-2 text-slate-600">{i.description || "—"}</td>
                    <td className={cn("px-3 py-2 text-right", NUM, h?.kind === "income" ? "text-slate-900 font-semibold" : "text-slate-800")}>{money(i.amount)}</td>
                    <td className={cn("px-3 py-2 text-right", NUM, i.disallowed || i.heading === "DEPRECIATION" ? "text-rose-700" : "text-slate-300")}>
                      {i.heading === "DEPRECIATION" ? money(i.amount) : i.disallowed ? money(i.disallowed) : "—"}
                    </td>
                    <td className="px-2 py-2 text-right">
                      <button type="button" onClick={() => remove(i.id)} title="Remove" className="rounded p-1 text-slate-400 hover:bg-rose-50 hover:text-rose-600 cursor-pointer">
                        <Trash2 className="h-3 w-3" />
                      </button>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
          <AddPopup open={adding} onClose={() => setAdding(false)} onAdd={add} title={`Add income or a cost: ${row.name}`}
                    description="Under its SA103 heading. For a cost, the part not allowed (private use, entertaining, fines) goes beside it.">
            <PopupField label="Heading" wide>
              <CustomSelect fullWidth value={heading} onChange={setHeading} searchable
                            options={Object.entries(view.headings).map(([k, h]) => ({ value: k, label: `${h.box} ${h.label}`, group: h.kind === "income" ? "Income" : "Costs" }))} />
            </PopupField>
            <PopupField label="Description" wide><Input value={desc} onChange={(e) => setDesc(e.target.value)} /></PopupField>
            <PopupField label="Amount (£)"><Input value={amount} onChange={(e) => setAmount(e.target.value)} inputMode="decimal" /></PopupField>
            {!isIncome && <PopupField label="Not allowed (£)"><Input value={disallowed} onChange={(e) => setDisallowed(e.target.value)} placeholder="0" inputMode="decimal" /></PopupField>}
          </AddPopup>
        </div>

        {/* The adjusted profit computation, as TaxCalc's */}
        <div className="border-t border-slate-200 bg-slate-50/60 px-4 py-3 xl:border-t-0 xl:border-l">
          <p className={cn(text.label, "mb-1")}>Adjusted profit</p>
          <dl className="space-y-1">
            {comp.map(([k, v, strong]) => (
              <div key={k} className={cn("flex justify-between gap-3 text-[13px]", strong ? "border-t border-slate-200 pt-1 font-semibold text-slate-900" : "text-slate-700")}>
                <dt>{k}</dt><dd className={NUM}>{money(v)}</dd>
              </div>
            ))}
          </dl>
          <p className={cn(text.label, "mt-4 mb-2")}>Claims and adjustments</p>
          <div className="space-y-2">
            <label className="flex items-center gap-2 text-xs text-slate-700">
              <input type="checkbox" className="accent-teal-700" checked={ta} onChange={() => save({ use_trading_allowance: !ta })} />
              £1,000 trading allowance instead of costs
            </label>
            {!ta && <>
              <Setting label="Hours a month at home" value={row.settings.home_hours} onSave={(v) => save({ home_hours: Math.round(v) })} suffix="hours" />
              <Setting label="Months worked at home" value={row.settings.home_months} onSave={(v) => save({ home_months: Math.round(v) })} suffix="months" />
              <Setting label="Business miles by car or van" value={row.settings.car_miles} onSave={(v) => save({ car_miles: Math.round(v) })} suffix="miles" />
              {row.allowances.length === 0 && <Setting label="Capital allowances" value={row.settings.capital_allowances} onSave={(v) => save({ capital_allowances: v })} suffix="£" />}
            </>}
            <Setting label="Loss brought forward" value={row.settings.losses_bf} onSave={(v) => save({ losses_bf: v })} suffix="£" />
            <Setting label="CIS deducted by contractors" value={row.settings.cis_deducted} onSave={(v) => save({ cis_deducted: v })} suffix="£" />
          </div>
          <button type="button" className="mt-4 text-xs text-rose-600 hover:underline cursor-pointer"
                  onClick={async () => { try { onChange(await api.deleteSaBusiness(jobId, row.id)); } catch (e: any) { toast.error("Not removed", { description: e.message }); } }}>
            Remove business
          </button>
        </div>
      </div>

      {!ta && <Allowances jobId={jobId} row={row} onChange={onChange} />}
      <SaTradeBank jobId={jobId} businessId={row.id} onPosted={onChange} />
      {row.balance_sheet && <BalanceSheet bs={row.balance_sheet} />}
    </section>
  );
}

export function SaTradePage({ jobId, onChange }: { jobId: string; onChange?: () => void }) {
  const [view, setViewState] = useState<SaTradeView | null>(null);
  const [name, setName] = useState("");
  const [adding, setAdding] = useState(false);
  const setView = (v: SaTradeView) => { setViewState(v); onChange?.(); };
  useEffect(() => { api.getSaTrade(jobId).then(setViewState).catch(() => {}); }, [jobId]);

  const add = async () => {
    if (!name.trim()) return toast.error("Enter the business's name");
    try { setView(await api.addSaBusiness(jobId, name.trim())); setName(""); setAdding(false); } catch (e: any) { toast.error("Not added", { description: e.message }); }
  };

  if (!view) return <div className="skeleton h-48 rounded-xl" />;
  const income = view.businesses.reduce((t, b) => t + b.income, 0);
  const allowed = view.businesses.reduce((t, b) => t + b.costs - b.disallowed, 0);

  return (
    <div className="space-y-4">
      <SaHead title="Self-employment (SA103)"
              state={view.businesses.length === 0 ? { text: "No business", tone: "empty" } : undefined}
              meta="Each business's income and costs under the SA103 headings, with the part not allowed beside each cost. Cash basis is the default. Use of home and mileage at HMRC's flat rates, or the £1,000 trading allowance instead of every cost."
              actions={<Button size="sm" className="h-8 text-xs" onClick={() => setAdding(true)}><Plus className="mr-1 h-3.5 w-3.5" /> Add business</Button>}
              figures={view.businesses.length ? [
                { label: "Turnover and other income", value: money(income) },
                { label: "Allowable costs", value: money(-allowed) },
                { label: "Taxable profit", value: money(view.taxable_profit) },
                { label: "CIS deducted", value: money(view.cis_deducted) },
              ] : undefined} />
      <Modal isOpen={adding} onClose={() => setAdding(false)} className="max-w-md" title="Add a business"
             description="Each trade the client runs as a sole trader gets its own SA103 page.">
        <div className="space-y-3 pt-4">
          <Input value={name} onChange={(e) => setName(e.target.value)} placeholder="Business name (e.g. the trade)" autoFocus
                 onKeyDown={(e) => { if (e.key === "Enter") add(); }} />
          <div className="flex justify-end gap-2 border-t border-slate-100 pt-3">
            <Button variant="ghost" size="sm" onClick={() => setAdding(false)}>Cancel</Button>
            <Button variant="primary" size="sm" onClick={add}>Add business</Button>
          </div>
        </div>
      </Modal>
      <SaFosterCare jobId={jobId} onChange={onChange} />
      {view.businesses.map((b) => <Business key={b.id} jobId={jobId} row={b} view={view} onChange={setView} />)}
    </div>
  );
}
