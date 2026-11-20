"use client";

// The tax calculation, in the order of TaxCalc's tax summary: income by type, allowances, the tax at each rate band,
// reductions, Class 4, tax paid, the balance and next year's payments on account.
import { useEffect, useState } from "react";
import { AlertTriangle, Pencil, RefreshCw } from "lucide-react";
import { AddPopup, NUM, PopupField, SaHead, TABLE_WRAP, THEAD } from "@/components/sa/SaChrome";
import { Input } from "@/components/ui/input";
import { api, SaCalculation } from "@/lib/api";
import { Button } from "@/components/ui/button";

const money = (v: number) => {
  const s = `£${Math.abs(v).toLocaleString("en-GB", { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
  return v < 0 ? `(${s})` : s;
};
const KIND = { non_savings: "Non-savings", savings: "Savings", dividends: "Dividends" } as Record<string, string>;
const BAND = { starting: "Starting rate", psa: "Personal savings allowance", allowance: "Dividend allowance",
               basic: "Basic", higher: "Higher", additional: "Additional" } as Record<string, string>;
const INCOME_ROWS: [string, string][] = [["employment", "Employment"], ["self_employment", "Self-employment"],
  ["property", "UK property (profit)"], ["pensions", "Pensions and benefits"], ["foreign", "Foreign"], ["other", "Other"],
  ["savings", "Savings interest"], ["dividends", "Dividends"]];

function Row({ label, value, strong, muted }: { label: string; value: string; strong?: boolean; muted?: boolean }) {
  return (
    <div className={`flex justify-between gap-4 py-1.5 text-[13px] ${strong ? "font-semibold text-slate-900 border-t border-slate-200 mt-1 pt-2" : muted ? "text-slate-500" : "text-slate-700"}`}>
      <span>{label}</span><span className={NUM}>{value}</span>
    </div>
  );
}

function Block({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div className={TABLE_WRAP}>
      <h3 className={`${THEAD} px-4 py-2 font-semibold`}>{title}</h3>
      <div className="px-4 py-2">
      {children}
      </div>
    </div>
  );
}

export function SaTaxCalc({ jobId }: { jobId: string }) {
  const [data, setData] = useState<SaCalculation | null>(null);
  const [error, setError] = useState("");
  const [editing, setEditing] = useState(false);
  const [poa, setPoa] = useState("");
  const [class2, setClass2] = useState(false);
  const [class4, setClass4] = useState("");
  const [lossClaim, setLossClaim] = useState("");
  const load = () => { setError(""); api.getSaCalculation(jobId).then(setData).catch((e) => setError(e.message)); };
  const openEdit = () => {
    setPoa(data && data.payments.poa_paid ? String(data.payments.poa_paid) : "");
    setClass2(!!data?.payments.class2_voluntary);
    setClass4(data?.payments.class4_exempt || "");
    setLossClaim(data?.payments.loss_claim || "");
    setEditing(true);
  };
  const save = () => {
    api.putSaPayments(jobId, { poa_paid: Number(poa) || 0, class2_voluntary: class2, class4_exempt: class4,
                               loss_claim: lossClaim })
      .then((d) => { setData(d); setEditing(false); }).catch((e) => setError(e.message));
  };
  // A new job clears the last error at once; its figures are set when they arrive
  const [prevJobId, setPrevJobId] = useState(jobId);
  if (jobId !== prevJobId) {
    setPrevJobId(jobId);
    setError("");
  }
  useEffect(() => {
    api.getSaCalculation(jobId).then(setData).catch((e) => setError(e.message));
  }, [jobId]);

  if (error) return <p className="text-sm text-rose-600">{error}</p>;
  if (!data) return <div className="skeleton h-64 rounded-2xl" />;
  const c = data.calculation, inc = data.income as Record<string, number>;
  const hasTrade = !!(data.trade?.businesses?.length) || !!inc.self_employment;
  const lossYear = data.trade?.loss_year || 0;
  const SELECT = "h-9 w-full rounded-md border border-slate-200 bg-white px-2 text-sm";

  return (
    <div className="space-y-4">
      <SaHead title={`Tax calculation ${c.tax_year}`}
              meta="Worked out from the figures on the income pages, in the order TaxCalc and HMRC set it out."
              actions={<Button variant="outline" size="sm" className="h-8 text-xs" onClick={load}><RefreshCw className="mr-1.5 h-3.5 w-3.5" /> Work it out again</Button>}
              figures={[
                { label: "Total income", value: money(c.total_income) },
                { label: "Tax and NIC for the year", value: money(c.liability) },
                { label: "Paid at source", value: money(-c.tax_deducted) },
                { label: c.balance < 0 ? "Refund due" : "To pay", value: money(Math.abs(c.balance)), tone: c.balance < 0 ? "text-emerald-700" : undefined },
              ]} />

      {data.notes.length > 0 && (
        <div className="rounded-xl border border-amber-200 bg-amber-50 px-4 py-3 text-xs text-amber-900 space-y-1">
          {data.notes.map((n) => <p key={n} className="flex gap-1.5"><AlertTriangle className="w-3.5 h-3.5 shrink-0 mt-px" />{n}</p>)}
        </div>
      )}

      <div className="grid grid-cols-1 xl:grid-cols-2 gap-4">
        <Block title="Income">
          {INCOME_ROWS.filter(([k]) => inc[k]).map(([k, label]) => <Row key={k} label={label} value={money(inc[k])} />)}
          <Row label="Total income" value={money(c.total_income)} strong />
          {c.net_income !== c.total_income && <Row label="Net income (after reliefs)" value={money(c.net_income)} muted />}
          {(inc.gift_aid_gross || inc.pension_ras_gross) ? <Row label="Adjusted net income" value={money(c.adjusted_net_income)} muted /> : null}
          <Row label="Personal allowance" value={money(c.personal_allowance)} />
          {Object.entries(c.taxable).filter(([, v]) => v).map(([k, v]) => <Row key={k} label={`Taxable ${KIND[k].toLowerCase()}`} value={money(v)} muted />)}
        </Block>

        <Block title="Tax at each rate">
          {c.lines.length === 0 && <p className="py-1.5 text-sm text-slate-500">No taxable income.</p>}
          {c.lines.map((l, i) => (
            <Row key={i} label={`${KIND[l.kind]}: ${BAND[l.band]} ${money(l.amount)} @ ${+(l.rate * 100).toFixed(2)}%`} value={money(l.tax)} />
          ))}
          <Row label="Income tax" value={money(c.income_tax)} strong />
          {Object.entries(c.reductions).map(([k, v]) => (
            <Row key={k} label={k === "finance_costs" ? "Less finance cost relief (20%)" : "Less Marriage Allowance"} value={money(-v)} />
          ))}
          {Object.keys(c.reductions).length > 0 && <Row label="Income tax after reductions" value={money(c.income_tax_due)} strong />}
        </Block>

        <Block title="Liability">
          <Row label="Income tax" value={money(c.income_tax_due)} />
          {c.class4 > 0 && <Row label="Class 4 National Insurance" value={money(c.class4)} />}
          {c.class2 > 0 && <Row label="Class 2 National Insurance (voluntary)" value={money(c.class2)} />}
          {c.hicbc > 0 && <Row label="High Income Child Benefit Charge" value={money(c.hicbc)} />}
          {c.student_loan > 0 && <Row label="Student loan" value={money(c.student_loan)} />}
          <Row label="Total liability" value={money(c.liability)} strong />
          <Row label="Less tax paid at source (PAYE, pensions, interest)" value={money(-c.tax_deducted)} />
          <Row label={c.balance < 0 ? "Refund due" : "Balance to pay"} value={money(c.balance)} strong />
        </Block>

        <Block title="Payments">
          <button type="button" onClick={openEdit}
                  className="mb-1 inline-flex items-center gap-1 text-[12px] font-medium text-teal-700 hover:underline">
            <Pencil className="h-3 w-3" /> Payments already made{hasTrade ? " and NI and loss choices" : ""}
          </button>
          {c.payments_on_account_made > 0 && <Row label="Less payments on account made" value={money(-c.payments_on_account_made)} />}
          <Row label="First payment on account for next year" value={money(c.poa_each)} />
          <Row label={c.due_31_january < 0 ? "Overpaid: refund due" : "Due 31 January"} value={money(Math.abs(c.due_31_january))} strong />
          <Row label="Second payment on account (31 July)" value={money(c.poa_each)} muted />
          {c.poa_each === 0 && c.balance > 0 && (
            <p className="text-[11px] text-slate-500 pt-1">No payments on account: under £1,000, or at least 80% was taxed at source.</p>
          )}
        </Block>
      </div>

      <AddPopup open={editing} onClose={() => setEditing(false)} onAdd={save} addLabel="Save"
                title="Payments already made"
                description={`What the person has already paid towards ${c.tax_year}: it comes off the 31 January payment.`}>
        <PopupField label={`Payments on account paid for ${c.tax_year} (31 Jan and 31 Jul)`} wide>
          <Input type="number" min="0" step="0.01" value={poa} onChange={(e) => setPoa(e.target.value)} placeholder="0.00"
                 className="h-9 text-sm" />
          <span className="block text-[11px] text-slate-500">From the HMRC statement (SOP R-FAM-03).</span>
        </PopupField>
        {c.class2_below_threshold && (
          <PopupField label="Class 2 National Insurance" wide>
            <span className="flex items-start gap-2 text-[13px] text-slate-700">
              <input type="checkbox" checked={class2} onChange={(e) => setClass2(e.target.checked)}
                     className="mt-0.5 h-4 w-4 accent-teal-700" />
              Pay voluntary Class 2: profits are under the small profits threshold, so the year only counts for the
              State Pension if Class 2 is paid (check the NI record first, R-NIC-01).
            </span>
          </PopupField>
        )}
        {hasTrade && (
          <PopupField label="Class 4 National Insurance" wide>
            <select value={class4} onChange={(e) => setClass4(e.target.value)} className={SELECT}>
              <option value="">Not checked</option>
              <option value="NONE">Checked: Class 4 is due</option>
              <option value="PENSION_AGE">Exempt: State Pension age reached before 6 April</option>
              <option value="UNDER_16">Exempt: under 16 at 6 April</option>
              <option value="NON_RESIDENT">Exempt: not UK resident for the year</option>
            </select>
            <span className="block text-[11px] text-slate-500">Exempt puts an X in SA103S box 37 / SA103F box 101 (SOP N4).</span>
          </PopupField>
        )}
        {lossYear > 0 && (
          <PopupField label={`Trading loss of ${money(lossYear)}`} wide>
            <select value={lossClaim} onChange={(e) => setLossClaim(e.target.value)} className={SELECT}>
              <option value="">Not chosen (carried forward)</option>
              <option value="CURRENT">Set against other income this year (box 33 / 78)</option>
              <option value="PRIOR">Carry back against last year&apos;s income (box 34 / 79)</option>
              <option value="CARRY_FORWARD">Carry forward against the same trade (box 35 / 80)</option>
            </select>
            <span className="block text-[11px] text-slate-500">A claim against income is capped at the greater of
              £50,000 or 25% of adjusted total income (ITA 2007 s24A, SOP N1).</span>
          </PopupField>
        )}
      </AddPopup>
    </div>
  );
}
