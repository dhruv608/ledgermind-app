"use client";

// Property (SA105, or SA106 pages F4-F5 abroad), read top to bottom:
//   1  the header: what the page is for, the totals, Add property (its details in a pop-up)
//   2  how it adds up: every property together is one letting business (PIM4210), so the profit, last year's loss,
//      the £1,000 allowance and the mortgage interest credit are worked out on the whole, not property by property
//   3  each property: its facts (who owns it, residential or commercial, when it was let), any point to look at, then
//      its rents and costs (a pop-up to add them; the working paper's month grid on request)
import { useEffect, useState } from "react";
import { toast } from "@/lib/notify";
import { CalendarRange, Home, Info, OctagonAlert, Pencil, Plus, Trash2 } from "lucide-react";
import { api, SaBankRent, SaPropertyFacts, SaPropertyRow, SaPropertyView } from "@/lib/api";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { CustomSelect } from "@/components/ui/custom-select";
import { Modal } from "@/components/ui/dialog";
import { ConfirmDialog } from "@/components/ui/confirm-dialog";
import { NUM, SaHead, TABLE_WRAP, THEAD, TROW, text } from "@/components/sa/SaChrome";
import { cn } from "@/lib/utils";

const money = (v: number) => {
  const s = `£${Math.abs(v).toLocaleString("en-GB", { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
  return v < 0 ? `(${s})` : s;
};
const day = (iso: string | null) => (iso ? iso.split("-").reverse().join("/") : "");
const HEADING_ORDER = ["RENT", "RATES_INSURANCE", "REPAIRS", "NONRES_FINANCE", "PROFESSIONAL", "SERVICES", "OTHER",
                       "DOMESTIC_ITEMS", "RES_FINANCE", "CAPITAL"];
const SHORT: Record<string, string> = { RENT: "Rent", RATES_INSURANCE: "Rates / ins.", REPAIRS: "Repairs", NONRES_FINANCE: "Loan int.",
  PROFESSIONAL: "Prof. fees", SERVICES: "Services", OTHER: "Other", DOMESTIC_ITEMS: "Domestic", RES_FINANCE: "Mortgage int.", CAPITAL: "Capital" };
const OWNERS = [{ value: "SOLE", label: "The client alone" }, { value: "SPOUSE", label: "Jointly with a spouse or civil partner" },
                { value: "JOINT", label: "Jointly with someone else" }, { value: "COMPANY", label: "A company (not on this return)" }];
const OWNER_SHORT: Record<string, string> = { SOLE: "Owned alone", SPOUSE: "Joint with spouse", JOINT: "Joint", COMPANY: "Company owned" };
const FIELD = "block space-y-1";
const LABEL = "text-xs font-semibold text-slate-700";
const HINT = "block text-[11px] text-slate-400";

const BLANK: SaPropertyFacts = { name: "", share: 1, country: null, owner: "SOLE", kind: "RESIDENTIAL", let_from: null, let_to: null,
                                 ended: null, own_home: null, rent_a_room: null };

// The property's details: asked when it is added, changed from its card
function DetailsModal({ open, start, overseas, onSave, onClose }: {
  open: boolean; start: SaPropertyFacts; overseas: boolean; onSave: (f: SaPropertyFacts) => void; onClose: () => void;
}) {
  const [f, setF] = useState<SaPropertyFacts>(start);
  // Start again from the given details each time the box opens
  const [wasOpen, setWasOpen] = useState(open);
  if (open !== wasOpen) {
    setWasOpen(open);
    if (open) setF(start);
  }
  const set = (p: Partial<SaPropertyFacts>) => setF({ ...f, ...p });
  const pct = Math.round(f.share * 1000) / 10;
  const save = () => {
    if (!f.name.trim()) return toast.error("Enter the property's address");
    if (overseas && !/^[A-Z]{3}$/.test(f.country || "")) return toast.error("Enter the country's 3-letter code (ESP, FRA, IND...)");
    if (!(f.share > 0 && f.share <= 1)) return toast.error("The share is between 1% and 100%");
    onSave({ ...f, name: f.name.trim() });
  };
  return (
    <Modal isOpen={open} onClose={onClose} className="max-w-xl" title={start.name ? `Details: ${start.name}` : "Add a let property"}
           description="These decide how the rent is taxed. Only the address is needed to start; the rest can be filled in later.">
      <div className="space-y-4 pt-4">
        <div className="grid grid-cols-3 gap-3">
          <label className={cn(FIELD, overseas ? "col-span-2" : "col-span-3")}><span className={LABEL}>Address</span>
            <Input value={f.name} onChange={(e) => set({ name: e.target.value })} placeholder="12 Any Street, Town" autoFocus /></label>
          {overseas && <label className={FIELD}><span className={LABEL}>Country</span>
            <Input value={f.country || ""} onChange={(e) => set({ country: e.target.value.toUpperCase().slice(0, 3) || null })} placeholder="ESP" className="uppercase" /></label>}
        </div>

        <div className="grid grid-cols-3 gap-3">
          <label className={cn(FIELD, "col-span-2")}><span className={LABEL}>Who owns it</span>
            <CustomSelect value={f.owner} fullWidth options={OWNERS}
                          onChange={(v) => set({ owner: v as SaPropertyFacts["owner"], share: v === "SPOUSE" ? 0.5 : v === "SOLE" ? 1 : f.share })} /></label>
          <label className={FIELD}><span className={LABEL}>Client&apos;s share %</span>
            <Input value={String(pct)} disabled={f.owner === "SOLE" || f.owner === "COMPANY"} inputMode="decimal"
                   onChange={(e) => set({ share: (parseFloat(e.target.value) || 0) / 100 })} />
            {f.owner === "SPOUSE" && <span className={HINT}>50% unless a Form 17 was sent</span>}</label>
        </div>

        <label className={FIELD}><span className={LABEL}>Kind of let</span>
          <CustomSelect value={f.kind} fullWidth onChange={(v) => set({ kind: v as SaPropertyFacts["kind"] })}
                        options={[{ value: "RESIDENTIAL", label: "Residential: mortgage interest gets the 20% credit" },
                                  { value: "COMMERCIAL", label: "Commercial (shop, office): loan interest is an expense" }]} /></label>

        <div className="grid grid-cols-3 gap-3">
          <label className={FIELD}><span className={LABEL}>Let from</span>
            <Input type="date" value={f.let_from || ""} onChange={(e) => set({ let_from: e.target.value || null })} />
            <span className={HINT}>Only if it started this year</span></label>
          <label className={FIELD}><span className={LABEL}>Let until</span>
            <Input type="date" value={f.let_to || ""} onChange={(e) => set({ let_to: e.target.value || null, ended: e.target.value ? f.ended : null })} />
            <span className={HINT}>Only if it stopped</span></label>
          <label className={FIELD}><span className={LABEL}>Why it stopped</span>
            <CustomSelect value={f.ended || ""} fullWidth onChange={(v) => set({ ended: (v || null) as SaPropertyFacts["ended"] })}
                          options={[{ value: "", label: "—" }, { value: "SOLD", label: "Sold" }, { value: "MOVED_IN", label: "Client moved in" }, { value: "OTHER", label: "Other" }]} /></label>
        </div>

        {!overseas && (
          <label className={FIELD}><span className={LABEL}>The client&apos;s own home?</span>
            <CustomSelect value={f.own_home || ""} fullWidth onChange={(v) => set({ own_home: (v || null) as SaPropertyFacts["own_home"], rent_a_room: v === "ROOM" ? f.rent_a_room : null })}
                          options={[{ value: "", label: "No" }, { value: "ROOM", label: "Rooms let in the home they live in (Rent-a-Room)" },
                                    { value: "FORMER", label: "It used to be their home" }]} /></label>
        )}
        {f.own_home === "ROOM" && (
          <label className={FIELD}><span className={LABEL}>Rent-a-Room or actual figures</span>
            <CustomSelect value={f.rent_a_room || ""} fullWidth onChange={(v) => set({ rent_a_room: (v || null) as SaPropertyFacts["rent_a_room"] })}
                          options={[{ value: "", label: "Not chosen yet (rents within the limit are exempt)" },
                                    { value: "RENT_A_ROOM", label: "Rent-a-Room: rents less £7,500, no expenses" },
                                    { value: "ACTUAL", label: "Actual: rents less expenses" }]} /></label>
        )}

        <div className="flex justify-end gap-2 border-t border-slate-100 pt-3">
          <Button variant="ghost" size="sm" onClick={onClose}>Cancel</Button>
          <Button variant="primary" size="sm" onClick={save}>{start.name ? "Save" : "Add property"}</Button>
        </div>
      </div>
    </Modal>
  );
}

// A rent or a cost of one property: once, or the same each month
function ItemModal({ open, view, name, onAdd, onClose }: {
  open: boolean; view: SaPropertyView; name: string; onAdd: (b: { heading: string; amount: number; description: string; on?: string; months: number }) => void; onClose: () => void;
}) {
  const [heading, setHeading] = useState("RENT");
  const [desc, setDesc] = useState("");
  const [amount, setAmount] = useState("");
  const [on, setOn] = useState("");
  const [months, setMonths] = useState("1");
  const add = () => {
    const a = parseFloat(amount.replace(/[£,]/g, ""));
    if (isNaN(a)) return toast.error("Enter an amount");
    const n = parseInt(months) || 1;
    if (n > 1 && !on) return toast.error("Give the first month's date");
    onAdd({ heading, amount: a, description: desc.trim(), on: on || undefined, months: n });
    setDesc(""); setAmount("");
  };
  return (
    <Modal isOpen={open} onClose={onClose} className="max-w-lg" title={`Add rent or a cost: ${name}`}
           description="Amounts for the whole property; the client's share is taken once, on the totals. Mortgage interest has its own heading (the 20% credit); an improvement goes under Capital and stays out of the figures.">
      <div className="space-y-3 pt-4">
        <label className={FIELD}><span className={LABEL}>Heading</span>
          <CustomSelect value={heading} onChange={setHeading} fullWidth
                        options={HEADING_ORDER.map((h) => ({ value: h, label: `${view.headings[h].label}${view.headings[h].box ? ` (box ${view.headings[h].box})` : ""}` }))} /></label>
        <label className={FIELD}><span className={LABEL}>Description</span>
          <Input value={desc} onChange={(e) => setDesc(e.target.value)} placeholder="Rent from tenant, boiler repair..." /></label>
        <div className="grid grid-cols-3 gap-3">
          <label className={FIELD}><span className={LABEL}>Amount</span>
            <Input value={amount} onChange={(e) => setAmount(e.target.value)} placeholder="0.00" inputMode="decimal" /></label>
          <label className={FIELD}><span className={LABEL}>Date</span>
            <Input type="date" value={on} onChange={(e) => setOn(e.target.value)} /></label>
          <label className={FIELD}><span className={LABEL}>Repeat</span>
            <CustomSelect value={months} onChange={setMonths} fullWidth
                          options={[{ value: "1", label: "Once" }, ...[3, 6, 12].map((n) => ({ value: String(n), label: `Monthly × ${n}` }))]} /></label>
        </div>
        <div className="flex justify-end gap-2 border-t border-slate-100 pt-3">
          <Button variant="ghost" size="sm" onClick={onClose}>Done</Button>
          <Button variant="primary" size="sm" onClick={add}>Add</Button>
        </div>
      </div>
    </Modal>
  );
}

// The firm's working paper layout: a row a month of the tax year (April to March), a column a heading, totals
function MonthGrid({ row, view, taxYear }: { row: SaPropertyRow; view: SaPropertyView; taxYear: string }) {
  const start = parseInt(taxYear.slice(0, 4));
  const months = Array.from({ length: 12 }, (_, i) => ({ y: start + (i + 3 >= 12 ? 1 : 0), m: (i + 3) % 12 }));
  const cols = HEADING_ORDER.filter((h) => row.items.some((i) => i.heading === h));
  const monthOf = (on: string) => `${parseInt(on.slice(0, 4))}-${parseInt(on.slice(5, 7)) - 1}`;
  const cell = (y: number, m: number, h: string) => row.items.filter((i) => i.heading === h && i.on && monthOf(i.on) === `${y}-${m}`).reduce((s, i) => s + i.amount, 0);
  const undated = (h: string) => row.items.filter((i) => i.heading === h && !i.on).reduce((s, i) => s + i.amount, 0);
  const fmt = (v: number) => (v ? v.toLocaleString("en-GB", { minimumFractionDigits: 2, maximumFractionDigits: 2 }) : "");
  return (
    <div className="overflow-x-auto">
      <table className="w-full text-xs tabular-nums">
        <thead><tr className={THEAD}>
          <th className="px-4 py-2 text-left font-semibold">Month</th>
          {cols.map((h) => <th key={h} className="px-2 py-2 text-right font-semibold whitespace-nowrap" title={view.headings[h].label}>{SHORT[h]}</th>)}
        </tr></thead>
        <tbody className="divide-y divide-slate-50">
          {months.map(({ y, m }) => (
            <tr key={`${y}-${m}`}>
              <td className="px-4 py-1 text-slate-500 whitespace-nowrap">{new Date(y, m, 1).toLocaleDateString("en-GB", { month: "short", year: "2-digit" })}</td>
              {cols.map((h) => <td key={h} className="px-2 py-1 text-right text-slate-700">{fmt(cell(y, m, h))}</td>)}
            </tr>
          ))}
          {cols.some((h) => undated(h)) && (
            <tr><td className="px-4 py-1 text-slate-400">No date</td>{cols.map((h) => <td key={h} className="px-2 py-1 text-right text-slate-600">{fmt(undated(h))}</td>)}</tr>
          )}
        </tbody>
        <tfoot><tr className="border-t border-slate-200 font-bold text-slate-900">
          <td className="px-4 py-1.5">Total</td>
          {cols.map((h) => <td key={h} className="px-2 py-1.5 text-right">{fmt(row.headings[h] || 0)}</td>)}
        </tr></tfoot>
      </table>
    </div>
  );
}

function Chip({ children, tone = "slate" }: { children: React.ReactNode; tone?: "slate" | "teal" | "amber" }) {
  const c = { slate: "bg-slate-100 text-slate-600", teal: "bg-teal-50 text-teal-800", amber: "bg-amber-50 text-amber-800" }[tone];
  return <span className={cn("rounded-full px-2 py-px text-[10.5px] font-semibold", c)}>{children}</span>;
}

function Property({ jobId, row, view, onChange, taxYear, overseas }: {
  jobId: string; row: SaPropertyRow; view: SaPropertyView; onChange: (v: SaPropertyView) => void; taxYear: string; overseas: boolean;
}) {
  const [editing, setEditing] = useState(false);
  const [adding, setAdding] = useState(false);
  const [removing, setRemoving] = useState(false);
  const [grid, setGrid] = useState(false);
  const run = async (p: Promise<SaPropertyView>) => {
    try { onChange(await p); return true; } catch (e: any) { toast.error("Not saved", { description: e.message }); return false; }
  };
  const facts: SaPropertyFacts = { name: row.name, share: row.share, country: row.country, owner: row.owner || "SOLE", kind: row.kind || "RESIDENTIAL",
                                   let_from: row.let_from, let_to: row.let_to, ended: row.ended, own_home: row.own_home, rent_a_room: row.rent_a_room };
  const expenses = HEADING_ORDER.filter((h) => h !== "RENT" && h !== "RES_FINANCE" && h !== "CAPITAL" && row.headings[h]);
  const items = [...row.items].sort((a, b) => (a.on || "").localeCompare(b.on || ""));

  return (
    <section className={TABLE_WRAP}>
      {/* Its facts */}
      <div className="flex flex-wrap items-start justify-between gap-3 border-b border-slate-200 px-4 py-3">
        <div className="min-w-0">
          <h3 className={cn(text.card, "flex items-center gap-2")}><Home className="h-4 w-4 text-teal-700" />{row.name}</h3>
          <div className="mt-1 flex flex-wrap gap-1">
            {row.country && <Chip tone="teal">{row.country}</Chip>}
            <Chip>{row.kind === "COMMERCIAL" ? "Commercial" : "Residential"}</Chip>
            <Chip>{OWNER_SHORT[row.owner || "SOLE"]}{row.owner !== "SOLE" && row.owner !== "COMPANY" ? ` · ${Math.round(row.share * 1000) / 10}%` : ""}</Chip>
            {row.let_from && <Chip>Let from {day(row.let_from)}</Chip>}
            {row.let_to && <Chip tone="amber">Let until {day(row.let_to)}{row.ended === "SOLD" ? " · sold" : row.ended === "MOVED_IN" ? " · moved in" : ""}</Chip>}
            {row.own_home === "ROOM" && <Chip tone="teal">Rent-a-Room</Chip>}
            {row.own_home === "FORMER" && <Chip>Former home</Chip>}
          </div>
        </div>
        <div className="flex items-center gap-3">
          <div className="text-right text-xs">
            <p className="text-slate-500">Client&apos;s profit</p>
            <p className={cn("text-sm font-semibold text-slate-900", NUM)}>{money(row.profit)}</p>
          </div>
          <Button size="sm" variant="outline" className="h-8 text-xs" onClick={() => setEditing(true)}><Pencil className="mr-1 h-3.5 w-3.5" /> Details</Button>
          <button type="button" title="Remove this property" onClick={() => setRemoving(true)}
                  className="rounded p-1.5 text-slate-400 hover:bg-rose-50 hover:text-rose-600 cursor-pointer"><Trash2 className="h-4 w-4" /></button>
        </div>
      </div>

      {/* What to look at */}
      {(row.issues.length > 0 || row.notes.length > 0) && (
        <div className="space-y-0.5 border-b border-slate-100 bg-amber-50/50 px-4 py-2 text-[11.5px]">
          {row.issues.map((i) => <p key={i.key} className="flex gap-1.5 text-amber-900"><OctagonAlert className="mt-px h-3.5 w-3.5 shrink-0" />{i.text}{i.block && <b> Block.</b>}</p>)}
          {row.notes.map((n) => <p key={n} className="flex gap-1.5 text-slate-600"><Info className="mt-px h-3.5 w-3.5 shrink-0" />{n}</p>)}
        </div>
      )}

      {/* Its rents and costs */}
      <div className="grid grid-cols-1 lg:grid-cols-[1fr_18rem]">
        <div className="min-w-0">
          <div className="flex items-center justify-between gap-2 px-4 pt-3">
            <p className={text.label}>Rents and costs ({row.items.length})</p>
            <div className="flex gap-2">
              {row.items.length > 0 && (
                <button type="button" onClick={() => setGrid(!grid)} className="inline-flex items-center gap-1 text-[11px] font-semibold text-teal-700 hover:underline cursor-pointer">
                  <CalendarRange className="h-3.5 w-3.5" /> {grid ? "List" : "By month"}
                </button>
              )}
              <Button size="sm" variant="outline" className="h-7 text-xs" onClick={() => setAdding(true)}><Plus className="mr-1 h-3.5 w-3.5" /> Add rent or cost</Button>
            </div>
          </div>
          {row.items.length === 0 ? (
            <p className="px-4 py-4 text-xs text-slate-500">Nothing yet. Add each rent received and each cost, from the letting agent&apos;s statements or the bank.</p>
          ) : grid ? <div className="pt-2"><MonthGrid row={row} view={view} taxYear={taxYear} /></div> : (
            <table className="mt-2 w-full table-fixed text-xs">
              <thead className={THEAD}><tr className="text-left">
                <th className="w-24 px-4 py-1.5 font-semibold">Date</th>
                <th className="px-2 py-1.5 font-semibold">Description</th>
                <th className="w-[34%] px-2 py-1.5 font-semibold">Heading</th>
                <th className="w-24 px-2 py-1.5 text-right font-semibold">Amount</th>
                <th className="w-9" />
              </tr></thead>
              <tbody className="divide-y divide-slate-100">
                {items.map((i) => (
                  <tr key={i.id} className={cn(TROW, i.heading === "CAPITAL" && "text-slate-400")}>
                    <td className="px-4 py-1.5 text-slate-500">{day(i.on) || "—"}</td>
                    <td className="truncate px-2 py-1.5">{i.description || "—"}</td>
                    <td className={cn("truncate px-2 py-1.5", i.heading === "RENT" ? "font-semibold text-teal-800" : "text-slate-600")}>{view.headings[i.heading]?.label}</td>
                    <td className={cn("px-2 py-1.5 text-right", NUM)}>{money(i.amount)}</td>
                    <td className="pr-3 text-right">
                      <button type="button" title="Remove" onClick={() => run(api.deleteSaPropertyItem(jobId, row.id, i.id))}
                              className="rounded p-1 text-slate-400 hover:bg-rose-50 hover:text-rose-600 cursor-pointer"><Trash2 className="h-3 w-3" /></button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>
        {/* The property's own sum */}
        <dl className="space-y-1 border-t border-slate-100 bg-slate-50/60 px-4 py-3 text-xs lg:border-l lg:border-t-0">
          <p className={cn(text.label, "mb-1")}>This property (whole)</p>
          <div className="flex justify-between gap-3"><dt className="text-slate-600">Rent received</dt><dd className={NUM}>{money(row.rents)}</dd></div>
          {expenses.map((h) => (
            <div key={h} className="flex justify-between gap-3"><dt className="text-slate-500">Less {view.headings[h].label.toLowerCase()}</dt><dd className={NUM}>{money(-row.headings[h])}</dd></div>
          ))}
          <div className="flex justify-between gap-3 border-t border-slate-200 pt-1 font-semibold text-slate-900"><dt>Profit</dt><dd className={NUM}>{money(row.profit_whole)}</dd></div>
          {row.share !== 1 && <div className="flex justify-between gap-3"><dt className="text-slate-600">Client&apos;s {Math.round(row.share * 1000) / 10}%</dt><dd className={cn("font-semibold", NUM)}>{money(row.profit)}</dd></div>}
          {row.headings.RES_FINANCE ? <div className="flex justify-between gap-3 pt-1"><dt className="text-slate-500">Mortgage interest (20% credit, not an expense)</dt><dd className={NUM}>{money(row.headings.RES_FINANCE)}</dd></div> : null}
          {row.headings.CAPITAL ? <div className="flex justify-between gap-3"><dt className="text-slate-400">Improvements (capital, kept out)</dt><dd className={cn("text-slate-400", NUM)}>{money(row.headings.CAPITAL)}</dd></div> : null}
          {overseas && (
            <label className="flex items-center justify-between gap-3 pt-2 text-slate-600">Foreign tax on it (£, client&apos;s share)
              <input key={row.foreign_tax} defaultValue={row.foreign_tax || ""} inputMode="decimal"
                     onBlur={(e) => { const v = parseFloat(e.target.value) || 0; if (v !== row.foreign_tax) run(api.editSaProperty(jobId, row.id, { foreign_tax: v })); }}
                     className="w-20 rounded border border-slate-200 bg-white px-1.5 py-0.5 text-right" /></label>
          )}
        </dl>
      </div>

      <DetailsModal open={editing} start={facts} overseas={overseas} onClose={() => setEditing(false)}
                    onSave={async (f) => { if (await run(api.editSaProperty(jobId, row.id, f))) setEditing(false); }} />
      <ItemModal open={adding} view={view} name={row.name} onClose={() => setAdding(false)}
                 onAdd={(b) => run(api.addSaPropertyItems(jobId, row.id, b))} />
      <ConfirmDialog isOpen={removing} onClose={() => setRemoving(false)} confirmText="Remove property"
                     title="Remove this property?" clientName={row.name}
                     description={`This takes ${row.name} off the return with its ${row.items.length} rent and cost line${row.items.length === 1 ? "" : "s"}. Use it for a property added by mistake or not let this year.`}
                     onConfirm={async () => { if (await run(api.deleteSaProperty(jobId, row.id))) setRemoving(false); }} />
    </section>
  );
}

// Rent found in the client's own bank, payer by payer: the accountant puts each on its property (or a new one)
function BankRent({ jobId, view, onChange }: { jobId: string; view: SaPropertyView; onChange: (v: SaPropertyView) => void }) {
  const [pick, setPick] = useState<Record<string, string>>({});
  const [open, setOpen] = useState<string | null>(null);
  const rows = view.bank_rent || [];
  if (rows.length === 0) return null;
  const options = [...view.properties.map((p) => ({ value: String(p.id), label: p.name })), { value: "new", label: "A new property" }];
  const add = async (g: SaBankRent) => {
    const to = pick[g.payer] || (g.property ? String(g.property) : "new");
    try {
      onChange(await api.addSaBankRent(jobId, { keys: g.lines.map((l) => l.key), property_id: to === "new" ? null : Number(to),
                                                name: to === "new" ? `Rent from ${g.payer}` : undefined }));
      toast.success(`${money(g.total)} added`);
    } catch (e: any) { toast.error("Not added", { description: e.message }); }
  };
  return (
    <section className={TABLE_WRAP}>
      <div className="border-b border-slate-200 px-4 py-3">
        <p className={text.card}>Rent found in the bank ({money(rows.reduce((t, g) => t + g.total, 0))})</p>
        <p className="mt-0.5 text-[11.5px] text-slate-500">Money in with rent on the line, or a letting agent&apos;s payment no statement covers. Not on the return until put on its property.</p>
      </div>
      <table className="w-full table-fixed text-xs">
        <thead className={THEAD}><tr className="text-left">
          <th className="px-4 py-1.5 font-semibold">Paid by</th>
          <th className="w-24 px-2 py-1.5 text-right font-semibold">Amount</th>
          <th className="w-[30%] px-2 py-1.5 font-semibold">Property</th>
          <th className="w-20" />
        </tr></thead>
        <tbody className="divide-y divide-slate-100">
          {rows.map((g) => (
            <tr key={g.payer} className={cn(TROW, "align-top")}>
              <td className="px-4 py-1.5">
                <button type="button" onClick={() => setOpen(open === g.payer ? null : g.payer)} className="text-left font-semibold text-slate-800 hover:underline cursor-pointer">{g.payer}</button>
                <span className="block text-[11px] text-slate-500">{g.lines.length} payment{g.lines.length === 1 ? "" : "s"}, {g.why}</span>
                {open === g.payer && (
                  <ul className="mt-1 space-y-0.5 text-[11px] text-slate-600">
                    {g.lines.map((l) => <li key={l.key} className="flex justify-between gap-3"><span className="truncate">{day(l.on)} {l.description}</span><span className={NUM}>{money(l.amount)}</span></li>)}
                  </ul>
                )}
              </td>
              <td className={cn("px-2 py-1.5 text-right font-semibold", NUM)}>{money(g.total)}</td>
              <td className="px-2 py-1">
                <CustomSelect value={pick[g.payer] || (g.property ? String(g.property) : "new")} options={options} fullWidth size="sm" buttonClassName="truncate"
                              onChange={(v: string) => setPick({ ...pick, [g.payer]: v })} />
              </td>
              <td className="pr-3 py-1 text-right">
                <Button size="sm" variant="outline" className="h-7 text-xs" onClick={() => add(g)}><Plus className="mr-1 h-3.5 w-3.5" /> Add</Button>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </section>
  );
}

// overseas: the overseas property business (SA106 pages F4-F5), each property with its country and the foreign tax on
// it; its own losses; the £1,000 property allowance is shared with the UK lettings.
export function SaPropertyPage({ jobId, taxYear, onChange, overseas = false }: { jobId: string; taxYear: string; onChange?: () => void; overseas?: boolean }) {
  const [view, setViewState] = useState<SaPropertyView | null>(null);
  const [adding, setAdding] = useState(false);
  const setView = (v: SaPropertyView) => { setViewState(v); onChange?.(); };
  useEffect(() => { api.getSaProperty(jobId, overseas).then(setViewState).catch(() => {}); }, [jobId, overseas]);

  if (!view) return <div className="skeleton h-48 rounded-2xl" />;
  const props = view.properties;
  const first = props[0];
  const rents = props.reduce((t, r) => t + r.rents * r.share, 0);
  const expenses = props.reduce((t, r) => t + r.expenses * r.share, 0);
  const lossBf = props.reduce((t, r) => t + (r.losses_bf || 0), 0);
  const financeBf = props.reduce((t, r) => t + (r.finance_bf || 0), 0);

  const add = async (f: SaPropertyFacts) => {
    try { setView(await api.addSaProperty(jobId, f)); setAdding(false); } catch (e: any) { toast.error("Not added", { description: e.message }); }
  };
  // Last year's figures belong to the whole letting business: kept on the first property, the others cleared
  const setBf = async (key: "losses_bf" | "finance_bf", v: number) => {
    try {
      let out: SaPropertyView | null = null;
      for (const r of props) {
        const want = r.id === first.id ? v : 0;
        if ((r[key] || 0) !== want) out = await api.editSaProperty(jobId, r.id, { [key]: want });
      }
      if (out) setView(out);
    } catch (e: any) { toast.error("Not saved", { description: e.message }); }
  };
  const setAllowance = async (on: boolean) => {
    // One choice for the whole business: on the first property, cleared from any other
    try {
      let out: SaPropertyView | null = null;
      for (const r of props) {
        const want = on && r.id === first.id;
        if (r.use_allowance !== want) out = await api.editSaProperty(jobId, r.id, { use_allowance: want });
      }
      if (out) setView(out);
    } catch (e: any) { toast.error("Not saved", { description: e.message }); }
  };
  const lines: [string, number, boolean?][] = [
    ["Rents (client's share)", rents],
    [view.allowance ? "Less the £1,000 property allowance" : "Less costs (client's share)", view.allowance ? -view.allowance_used : -expenses],
    ["Profit for the year", view.before_losses, true],
    ...(view.losses_used ? [["Less last year's loss", -view.losses_used] as [string, number]] : []),
    ["Taxable property profit", view.profit, true],
  ];

  return (
    <div className="space-y-4">
      <SaHead title={overseas ? "Property abroad (SA106)" : "UK property (SA105)"}
              state={props.length === 0 ? { text: "No properties", tone: "empty" } : undefined}
              meta={overseas
                ? "Each let property abroad, rebuilt under UK rules (no foreign depreciation) in pounds, with the foreign tax paid on it. Its losses stay with property abroad."
                : "Each let property: who owns it, its rents and its costs. All of them together are one letting business: profits and losses are added up, mortgage interest gets a 20% credit instead of being an expense."}
              actions={<Button size="sm" className="h-8 text-xs" onClick={() => setAdding(true)}><Plus className="mr-1 h-3.5 w-3.5" /> Add property</Button>}
              figures={props.length ? [
                { label: "Rents (client's share)", value: money(rents) },
                { label: view.allowance ? "Property allowance" : "Costs (client's share)", value: money(view.allowance ? -view.allowance_used : -expenses) },
                { label: "Taxable profit", value: money(view.profit) },
                { label: "Mortgage interest for the credit", value: money(view.finance_costs) },
              ] : undefined} />

      {props.length === 0 ? (
        <section className={cn(TABLE_WRAP, "px-5 py-4 text-xs text-slate-600")}>
          <p className={cn(text.card, "mb-2")}>How this page works</p>
          <ol className="list-decimal space-y-1 pl-4">
            <li><b>Add property</b> for each property the client lets out, with who owns it and when it was let.</li>
            <li>On its card, <b>add the rents and costs</b> from the letting agent&apos;s statements or the bank.</li>
            <li>The page adds every property into one letting business and works out the taxable profit.</li>
          </ol>
        </section>
      ) : (
        <section className={TABLE_WRAP}>
          <div className="border-b border-slate-200 px-4 py-3">
            <p className={text.card}>How it adds up{props.length > 1 ? `: all ${props.length} properties as one letting business` : ""}</p>
          </div>
          <div className="grid grid-cols-1 gap-x-8 px-4 py-3 text-xs md:grid-cols-2">
            <dl className="space-y-1">
              {lines.map(([k, v, strong]) => (
                <div key={k} className={cn("flex justify-between gap-4", strong ? "border-t border-slate-200 pt-1 font-semibold text-slate-900" : "text-slate-700")}>
                  <dt>{k}</dt><dd className={NUM}>{money(v)}</dd>
                </div>
              ))}
              <div className="flex justify-between gap-4 pt-2 text-slate-700"><dt>Mortgage interest for the 20% credit</dt><dd className={NUM}>{money(view.finance_costs)}</dd></div>
              {view.loss_cf > 0 && <div className="flex justify-between gap-4 text-rose-700"><dt>Loss to carry forward to next year</dt><dd className={NUM}>{money(view.loss_cf)}</dd></div>}
            </dl>
            <div className="mt-3 space-y-2 md:mt-0">
              <p className={text.label}>For the whole business</p>
              <label className="flex items-center gap-2 text-slate-700">
                <input type="checkbox" className="accent-teal-700" checked={view.allowance} onChange={() => setAllowance(!view.allowance)} />
                Use the £1,000 property allowance instead of the costs
              </label>
              <label className="flex items-center justify-between gap-3 text-slate-700">Loss brought forward from last year
                <input key={`l${lossBf}`} defaultValue={lossBf || ""} inputMode="decimal" onBlur={(e) => { const v = parseFloat(e.target.value) || 0; if (v !== lossBf) setBf("losses_bf", v); }}
                       className="w-24 rounded border border-slate-200 px-1.5 py-0.5 text-right" /></label>
              <label className="flex items-center justify-between gap-3 text-slate-700">Unused mortgage interest from last year
                <input key={`f${financeBf}`} defaultValue={financeBf || ""} inputMode="decimal" onBlur={(e) => { const v = parseFloat(e.target.value) || 0; if (v !== financeBf) setBf("finance_bf", v); }}
                       className="w-24 rounded border border-slate-200 px-1.5 py-0.5 text-right" /></label>
            </div>
          </div>
        </section>
      )}

      {!overseas && <BankRent jobId={jobId} view={view} onChange={setView} />}

      {props.map((r) => <Property key={r.id} jobId={jobId} row={r} view={view} onChange={setView} taxYear={taxYear} overseas={overseas} />)}

      <DetailsModal open={adding} start={{ ...BLANK, country: overseas ? "" : null }} overseas={overseas} onClose={() => setAdding(false)} onSave={add} />
    </div>
  );
}
