"use client";

import React, { useEffect, useState } from "react";
import { toast } from "@/lib/notify";
import { Check, Loader2, Settings2 } from "lucide-react";
import { Card } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { CustomSelect } from "@/components/ui/custom-select";
import { SkeletonRows } from "@/components/common/SkeletonRows";
import { api } from "@/lib/api";
import type { ClassRate, FirmDepreciation, FirmIntangibles } from "@/lib/api/firmSettings";
import { cn } from "@/lib/utils";

const inputClass =
  "w-full rounded-md border border-slate-300 bg-white px-2.5 py-1 text-xs text-slate-800 focus:outline-none focus:ring-2 focus:ring-teal-200";
const METHODS = [
  { value: "REDUCING_BALANCE", label: "Reducing balance" },
  { value: "STRAIGHT_LINE", label: "Straight line" },
  { value: "NONE", label: "Not depreciated" },
];
const ADDITIONS = [
  { value: "FULL_YEAR", label: "A full year's charge" },
  { value: "PURCHASE_MONTH", label: "From the month of purchase" },
  { value: "NEXT_MONTH", label: "From the month after purchase" },
];
const saved = (at: string | null | undefined) => (at ? `Saved ${new Date(at + "Z").toLocaleDateString("en-GB")}` : "");

/** The firm's own defaults, used for every client that has none of its own. */
export default function FirmSettingsPage() {
  return (
    <div className="space-y-4">
      <div className="flex items-center gap-2.5">
        <span className="flex h-8 w-8 items-center justify-center rounded-lg bg-teal-50 text-teal-700">
          <Settings2 className="h-4 w-4" />
        </span>
        <div>
          <h1 className="text-base font-bold text-slate-900">Firm settings</h1>
          <p className="text-xs text-slate-500">The firm&apos;s own defaults, used for every client that has none of its own.</p>
        </div>
      </div>

      <div className="grid items-start gap-4 lg:grid-cols-[minmax(0,1fr)_minmax(0,26rem)]">
        <DepreciationCard />
        <Card className="divide-y divide-slate-100 p-0">
          <p className="px-4 py-3 text-xs font-bold text-slate-900">Amounts</p>
          <AmountRow
            title="Accountancy fee accrual"
            help="The fee accrued for a year's accounts when last year's accrual is not known, net of VAT (20% VAT is added for a client not VAT registered). Empty: the fees charged in the year."
            placeholder="Not set"
            load={() => api.getFirmAccountancyFee()}
            save={(v) => api.saveFirmAccountancyFee(v)}
          />
          <AmountRow
            title="Prepayments for a client with none last year"
            help="Bills running past the year end for a client that had no prepayments last year. A bill whose own wording gives its period (dates, the rates year, the month) is always posted. For one whose period is assumed from words like annual: empty asks about each, 0 posts every one, an amount posts those of at least it and asks about smaller ones."
            placeholder="Ask"
            load={() => api.getFirmNewClientPrepayments()}
            save={(v) => api.saveFirmNewClientPrepayments(v)}
          />
          <AmountRow
            title="Year-on-year question limit"
            help="A balance that changed on last year by more than 50% and more than this amount (or is new or gone) becomes a client question. Empty: £1,000."
            placeholder="1000"
            load={() => api.getFirmChangeQuestionLimit()}
            save={(v) => api.saveFirmChangeQuestionLimit(v)}
          />
          <AmountRow
            title="Suspense limit on bank jobs"
            help="Above this in suspense or one-sided transfers, the tax and any dividend are not proposed: the profit is not final. Empty: £1,000."
            placeholder="1000"
            load={() => api.getFirmTaxHoldLimit()}
            save={(v) => api.saveFirmTaxHoldLimit(v)}
          />
          <AmountRow
            title="Fixed asset limit"
            help="Purchases booked as costs from this amount are checked as possible fixed assets. A client's own limit (Client details) wins. Empty: £500."
            placeholder="500"
            load={() => api.getFirmCapitalLimits().then((l) => ({ amount: l.saved ? l.general : null, updated_at: l.updated_at }))}
            save={(v) => api.saveFirmCapitalLimit("general", v).then((l) => ({ amount: l.general, updated_at: l.updated_at }))}
          />
          <AmountRow
            title="Fixed asset limit for equipment"
            help="Computers, phones, furniture and machines are checked from this lower amount: the AI decides whether each is equipment. Empty: the same as the limit above."
            placeholder="Same"
            load={() => api.getFirmCapitalLimits().then((l) => ({ amount: l.saved && l.equipment !== l.general ? l.equipment : null, updated_at: l.updated_at }))}
            save={(v) => api.saveFirmCapitalLimit("equipment", v).then((l) => ({ amount: l.equipment !== l.general ? l.equipment : null, updated_at: l.updated_at }))}
          />
        </Card>
        <Card className="divide-y divide-slate-100 p-0 lg:col-start-2">
          <p className="px-4 py-3 text-xs font-bold text-slate-900">Tax computation</p>
          <IntangiblesRow />
        </Card>
      </div>
    </div>
  );
}

/** The depreciation method and rate for each asset type, and how this year's additions are charged. */
function DepreciationCard() {
  const [data, setData] = useState<FirmDepreciation | null>(null);
  const [classes, setClasses] = useState<Record<string, ClassRate>>({});
  const [additions, setAdditions] = useState<FirmDepreciation["additions_from"]>("FULL_YEAR");
  const [saving, setSaving] = useState(false);
  const [dirty, setDirty] = useState(false);

  const show = (d: FirmDepreciation) => {
    setData(d);
    setClasses(d.classes);
    setAdditions(d.additions_from);
    setDirty(false);
  };
  useEffect(() => {
    api.getFirmDepreciation().then(show).catch((e) => toast.error(e.message));
  }, []);

  const setClass = (cls: string, change: Partial<ClassRate>) => {
    setClasses((c) => ({ ...c, [cls]: { ...(c[cls] || { method: "NONE" }), ...change } }));
    setDirty(true);
  };

  const save = async () => {
    setSaving(true);
    try {
      show(await api.saveFirmDepreciation({ classes, additions_from: additions }));
      toast.success("Firm depreciation saved", { description: "Used the next time a client's review runs." });
    } catch (e: any) {
      toast.error(e.message);
    } finally {
      setSaving(false);
    }
  };

  return (
    <Card className="p-0">
      <div className="flex items-start justify-between gap-3 border-b border-slate-100 px-4 py-3">
        <div>
          <p className="text-xs font-bold text-slate-900">Depreciation</p>
          <p className="mt-0.5 text-[11px] leading-snug text-slate-500">
            Used when there is no fixed asset register: a client&apos;s own setup first, then last year&apos;s rate, then these.
          </p>
        </div>
        <Button type="button" variant="primary" size="sm" className="h-7 shrink-0 px-3 text-xs" onClick={save} disabled={!dirty || saving}>
          {saving && <Loader2 className="mr-1 h-3.5 w-3.5 animate-spin" />} Save
        </Button>
      </div>
      {!data ? (
        <div className="p-4"><SkeletonRows rows={6} /></div>
      ) : (
        <>
          <table className="w-full text-xs">
            <thead className="bg-slate-50 text-[10.5px] uppercase tracking-wide text-slate-500">
              <tr className="text-left">
                <th className="px-4 py-1.5 font-semibold">Asset type</th>
                <th className="w-44 px-2 py-1.5 font-semibold">Method</th>
                <th className="w-24 px-4 py-1.5 font-semibold">Rate %</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-100">
              {data.asset_classes.map((cls) => {
                const c = classes[cls] || { method: "NONE" };
                const none = c.method === "NONE";
                return (
                  <tr key={cls}>
                    <td className="px-4 py-1 text-slate-700">{cls}</td>
                    <td className="px-2 py-1">
                      <CustomSelect fullWidth size="sm" value={c.method} options={METHODS}
                                    onChange={(x) => setClass(cls, { method: x as ClassRate["method"], rate: x === "NONE" ? null : c.rate ?? 20 })} />
                    </td>
                    <td className="px-4 py-1">
                      <input type="number" min={0} max={100} step="any" disabled={none}
                             value={none ? "" : c.rate ?? ""} placeholder={none ? "-" : "Rate"}
                             onChange={(e) => setClass(cls, { rate: e.target.value === "" ? null : parseFloat(e.target.value) })}
                             className={cn(inputClass, "text-right", none && "bg-slate-50 text-slate-400")} />
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
          <div className="flex flex-wrap items-center gap-x-3 gap-y-1.5 border-t border-slate-100 px-4 py-2.5">
            <span className="text-xs text-slate-700">This year&apos;s additions:</span>
            <div className="w-56">
              <CustomSelect fullWidth size="sm" value={additions} options={ADDITIONS}
                            onChange={(x) => { setAdditions(x as FirmDepreciation["additions_from"]); setDirty(true); }} />
            </div>
            <span className="ml-auto text-[11px] text-slate-400">
              {data.saved && data.updated_at ? saved(data.updated_at) : "Starting values: 20% reducing balance, property not depreciated"}
            </span>
          </div>
        </>
      )}
    </Card>
  );
}

const INTANGIBLES = [
  { value: "ADD_BACK", label: "Add back until confirmed" },
  { value: "ALLOW", label: "Allow with the accounts" },
];

/** Amortisation of software, patents and trade marks in the tax computation; goodwill is always added back. */
function IntangiblesRow() {
  const [data, setData] = useState<FirmIntangibles | null>(null);
  const [saving, setSaving] = useState(false);
  useEffect(() => {
    api.getFirmIntangibles().then(setData).catch((e) => toast.error(e.message));
  }, []);
  const choose = async (policy: FirmIntangibles["policy"]) => {
    setSaving(true);
    try {
      setData(await api.saveFirmIntangibles(policy));
      toast.success("Amortisation of intangibles saved", { description: "Used the next time a client's review runs." });
    } catch (e: any) {
      toast.error(e.message);
    } finally {
      setSaving(false);
    }
  };
  return (
    <div className="px-4 py-3">
      <div className="flex items-center gap-2">
        <p className="min-w-0 flex-1 text-xs font-semibold text-slate-800">Amortisation of intangibles</p>
        <div className="w-52 shrink-0">
          {data ? (
            <CustomSelect fullWidth size="sm" value={data.policy} options={INTANGIBLES} disabled={saving}
                          onChange={(x) => choose(x as FirmIntangibles["policy"])} />
          ) : <SkeletonRows rows={1} />}
        </div>
      </div>
      <p className="mt-1 text-[11px] leading-snug text-slate-500">
        Software, patents and trade marks. Goodwill is always added back with a query (relief is restricted). A
        client&apos;s confirmed amount (Client details, tax) is allowed either way.
        {data?.saved && data.updated_at ? <span className="text-slate-400"> {saved(data.updated_at)}.</span> : null}
      </p>
    </div>
  );
}

/** One amount the firm sets (empty: not used), saved on its own. */
function AmountRow({ title, help, placeholder, load, save }: {
  title: string;
  help: string;
  placeholder: string;
  load: () => Promise<{ amount: number | null; updated_at: string | null }>;
  save: (amount: number | null) => Promise<{ amount: number | null; updated_at: string | null }>;
}) {
  const [data, setData] = useState<{ amount: number | null; updated_at: string | null } | null>(null);
  const [amount, setAmount] = useState("");
  const [saving, setSaving] = useState(false);

  const show = (d: { amount: number | null; updated_at: string | null }) => {
    setData(d);
    setAmount(d.amount == null ? "" : String(d.amount));
  };
  useEffect(() => {
    load().then(show).catch((e) => toast.error(e.message));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const dirty = data != null && amount !== (data.amount == null ? "" : String(data.amount));
  const submit = async () => {
    setSaving(true);
    try {
      show(await save(amount === "" ? null : parseFloat(amount)));
      toast.success(`${title} saved`, { description: "Used the next time a client's review runs." });
    } catch (e: any) {
      toast.error(e.message);
    } finally {
      setSaving(false);
    }
  };

  return (
    <div className="px-4 py-3">
      <div className="flex items-center gap-2">
        <p className="min-w-0 flex-1 text-xs font-semibold text-slate-800">{title}</p>
        <div className="relative w-32 shrink-0">
          <span className="pointer-events-none absolute left-2.5 top-1/2 -translate-y-1/2 text-xs text-slate-400">£</span>
          <input type="number" min={0} step="any" value={amount} placeholder={placeholder} disabled={!data}
                 onChange={(e) => setAmount(e.target.value)} className={cn(inputClass, "pl-5 text-right")} />
        </div>
        <Button type="button" variant={dirty ? "primary" : "outline"} size="sm" className="h-7 w-14 shrink-0 px-0 text-xs"
                onClick={submit} disabled={!dirty || saving}>
          {saving ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : dirty ? "Save" : <Check className="h-3.5 w-3.5" />}
        </Button>
      </div>
      <p className="mt-1 text-[11px] leading-snug text-slate-500">
        {help}
        {data?.amount != null && data.updated_at ? <span className="text-slate-400"> {saved(data.updated_at)}.</span> : null}
      </p>
    </div>
  );
}
