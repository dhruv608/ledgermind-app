"use client";

// Family and loans (SA100 page TR5): Child Benefit and who pays the charge, Marriage Allowance given or received, and
// student and postgraduate loans. Each part shows what it does to the tax; what is still unknown is a Block on Queries.
import { useEffect, useState } from "react";
import { toast } from "@/lib/notify";
import { OctagonAlert, MessageSquareMore } from "lucide-react";
import { api, SaFamily as Data, SaFamilyFacts } from "@/lib/api";
import { Button } from "@/components/ui/button";
import { NUM, SaHead, TABLE_WRAP, text } from "@/components/sa/SaChrome";
import { cn } from "@/lib/utils";

const money = (v: number) => `£${v.toLocaleString("en-GB", { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
const INPUT = "h-8 w-full rounded-md border border-slate-200 bg-white px-2.5 text-xs focus:border-teal-500 focus:outline-none";
const num = (s: string) => (s.trim() === "" ? null : Number(s.replace(/[£,]/g, "")));

function Field({ label, hint, children }: { label: string; hint?: string; children: React.ReactNode }) {
  return (
    <label className="block">
      <span className="text-[11px] font-semibold text-slate-600">{label}</span>
      <div className="mt-0.5">{children}</div>
      {hint && <span className="mt-0.5 block text-[10.5px] text-slate-400">{hint}</span>}
    </label>
  );
}

function Choice<T extends string>({ value, options, onPick }: { value: T | null; options: [T, string][]; onPick: (v: T | null) => void }) {
  return (
    <span className="inline-flex flex-wrap overflow-hidden rounded-md border border-slate-200">
      {options.map(([v, label]) => (
        <button key={v} type="button" onClick={() => onPick(value === v ? null : v)}
                className={cn("px-2.5 py-1 text-[11.5px] font-semibold cursor-pointer",
                  value === v ? "bg-teal-700 text-white" : "bg-white text-slate-600 hover:bg-slate-50")}>{label}</button>
      ))}
    </span>
  );
}

function Card({ title, said, result, children }: { title: string; said?: string | null; result?: React.ReactNode; children: React.ReactNode }) {
  return (
    <section className={cn(TABLE_WRAP, "p-4")}>
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <p className={text.card}>{title}</p>
        {said && <span className="text-[11px] text-slate-500">Yearly question: <b>{said === "YES" ? "Yes" : said === "NO" ? "No" : said}</b></span>}
      </div>
      <div className="mt-3 grid gap-3 sm:grid-cols-2 lg:grid-cols-4">{children}</div>
      {result && <div className="mt-3 rounded-lg bg-slate-50 px-3 py-2 text-xs text-slate-700">{result}</div>}
    </section>
  );
}

export function SaFamily({ jobId, onOpen, onChange }: { jobId: string; onOpen: (page: string) => void; onChange?: () => void }) {
  const [data, setData] = useState<Data | null>(null);
  const [f, setF] = useState<SaFamilyFacts | null>(null);
  const [busy, setBusy] = useState(false);
  useEffect(() => { api.getSaFamily(jobId).then((d) => { setData(d); setF(d.facts); }).catch(() => {}); }, [jobId]);
  if (!data || !f) return <div className="skeleton h-48 rounded-xl" />;

  const set = (patch: Partial<SaFamilyFacts>) => setF({ ...f, ...patch });
  const dirty = JSON.stringify(f) !== JSON.stringify(data.facts);
  const save = async () => {
    setBusy(true);
    try {
      const d = await api.putSaFamily(jobId, f);
      setData(d);
      setF(d.facts);
      onChange?.();
      toast.success("Saved");
    } catch (e: any) {
      toast.error("Not saved", { description: e.message });
    } finally {
      setBusy(false);
    }
  };
  const l = data.loan;
  const blocks = data.issues.filter((i) => i.block).length;

  return (
    <div className="space-y-4">
      <SaHead title="Family and loans"
              state={blocks ? { text: `${blocks} block${blocks > 1 ? "s" : ""}`, tone: "look" } : { text: "Up to date", tone: "done" }}
              meta="Child Benefit and who pays the charge, Marriage Allowance, and student and postgraduate loans (SA100 page TR5)."
              actions={<Button size="sm" className="h-8 text-xs" disabled={!dirty || busy} onClick={save}>Save</Button>}
              figures={[
                { label: "Adjusted net income", value: money(data.adjusted_net_income) },
                { label: "Child Benefit charge", value: money(data.hicbc) },
                { label: "Marriage Allowance", value: data.marriage_reduction ? `-${money(data.marriage_reduction)}` : f.marriage === "TRANSFERRED" ? "Given" : "—" },
                { label: "Loan repayments", value: money(l.charge || 0) },
              ]} />

      {data.issues.length > 0 && (
        <div className="space-y-1 rounded-xl border border-rose-200 bg-rose-50 px-4 py-2.5 text-xs text-rose-900">
          {data.issues.map((i) => (
            <p key={i.key} className="flex gap-1.5">
              {i.kind === "CLIENT" ? <MessageSquareMore className="mt-px h-3.5 w-3.5 shrink-0" /> : <OctagonAlert className="mt-px h-3.5 w-3.5 shrink-0" />}
              <span>{i.text}{i.block && <b> Block.</b>}</span>
            </p>
          ))}
          <button type="button" onClick={() => onOpen("queries")} className="font-semibold underline cursor-pointer">Open Queries</button>
        </div>
      )}

      <Card title="Child Benefit" said={data.answers.child_benefit}
            result={data.adjusted_net_income > data.hicbc_from
              ? (f.higher_income === "PARTNER" ? "The partner has the higher income: any charge goes on their return."
                 : data.hicbc ? <>Charge <b className={NUM}>{money(data.hicbc)}</b>: 1% of the Child Benefit for every £200 of income over £{data.hicbc_from.toLocaleString("en-GB")}.</>
                 : "Enter the Child Benefit and who has the higher income to work out the charge.")
              : `Adjusted net income is under £${data.hicbc_from.toLocaleString("en-GB")}: no charge.`}>
        <Field label="Child Benefit for the year" hint="You and your partner together">
          <input className={cn(INPUT, NUM)} defaultValue={f.child_benefit ?? ""} onBlur={(e) => set({ child_benefit: num(e.target.value) })} />
        </Field>
        <Field label="Children on 5 April">
          <input className={cn(INPUT, NUM)} type="number" min={0} value={f.children ?? ""} onChange={(e) => set({ children: e.target.value === "" ? null : Number(e.target.value) })} />
        </Field>
        <Field label="All payments stopped on" hint="Only if before 6 April">
          <input className={INPUT} type="date" value={f.cb_stopped ?? ""} onChange={(e) => set({ cb_stopped: e.target.value || null })} />
        </Field>
        <Field label="Higher income" hint="Only the one with the higher income pays">
          <Choice value={f.higher_income} options={[["ME", "This person (or no partner)"], ["PARTNER", "The partner"]]} onPick={(v) => set({ higher_income: v })} />
        </Field>
      </Card>

      <Card title="Marriage Allowance" said={data.answers.married}
            result={f.marriage === "TRANSFERRED" ? <>This person gives £1,260 of allowance: personal allowance <b className={NUM}>{money(data.personal_allowance)}</b>.</>
                    : f.marriage === "RECEIVED" ? <>Tax reduced by <b className={NUM}>{money(data.marriage_reduction)}</b> (20% of £1,260).</>
                    : "Not claimed. Neither partner may be taxed above the basic rate."}>
        <Field label="This person">
          <Choice value={f.marriage} options={[["TRANSFERRED", "Gives it"], ["RECEIVED", "Receives it"]]} onPick={(v) => set({ marriage: v })} />
        </Field>
        <Field label="Spouse or civil partner's name" hint="On the return when this person gives it">
          <input className={INPUT} value={f.spouse_name ?? ""} onChange={(e) => set({ spouse_name: e.target.value || null })} />
        </Field>
      </Card>

      <Card title="Student and postgraduate loans" said={data.answers.student_loan}
            result={l.studying ? "Still studying or not yet due to repay: nothing is charged."
              : (l.plans?.length || l.postgraduate) ? <>
                  Income for the loans <b className={NUM}>{money(l.income || 0)}</b>
                  {l.unearned ? <> (unearned £{(l.unearned).toLocaleString("en-GB")} {l.unearned_counted ? "counted in full: over £2,000" : "left out: £2,000 or less"})</> : null}.
                  {l.plans?.length ? <> 9% over £{(l.threshold || 0).toLocaleString("en-GB")}: <b className={NUM}>{money(l.due || 0)}</b>.</> : null}
                  {l.postgraduate ? <> Postgraduate 6% over £21,000: <b className={NUM}>{money(l.pgl_due || 0)}</b>.</> : null}
                  {" "}Less taken by employers: due <b className={NUM}>{money(l.charge || 0)}</b>.
                  <span className="block text-slate-500">An estimate for the balance: the tax software works out the exact repayment from the plan, so the return only needs the plan and what employers took.</span>
                </>
              : "No loan in repayment."}>
        <Field label="Plan" hint="Two plans: the lower threshold">
          <span className="flex flex-wrap gap-1">
            {data.plans.map((p) => {
              const on = f.loan_plans.includes(p.plan);
              return (
                <button key={p.plan} type="button" title={`£${p.threshold.toLocaleString("en-GB")}`}
                        onClick={() => set({ loan_plans: on ? f.loan_plans.filter((x) => x !== p.plan) : [...f.loan_plans, p.plan] })}
                        className={cn("rounded-md border px-2 py-1 text-[11.5px] font-semibold cursor-pointer", on ? "border-teal-700 bg-teal-700 text-white" : "border-slate-200 bg-white text-slate-600 hover:bg-slate-50")}>
                  {p.label}
                </button>
              );
            })}
          </span>
        </Field>
        <Field label="Other">
          <span className="flex flex-col gap-1 text-xs text-slate-700">
            <label className="flex items-center gap-1.5"><input type="checkbox" checked={f.postgraduate} onChange={(e) => set({ postgraduate: e.target.checked })} /> Postgraduate loan</label>
            <label className="flex items-center gap-1.5"><input type="checkbox" checked={f.studying} onChange={(e) => set({ studying: e.target.checked })} /> Still studying / not yet due</label>
          </span>
        </Field>
        <Field label="Student loan taken by employers" hint="From the P60s and payslips">
          <input className={cn(INPUT, NUM)} defaultValue={f.sl_deducted ?? ""} onBlur={(e) => set({ sl_deducted: num(e.target.value) })} />
        </Field>
        <Field label="Postgraduate loan taken by employers">
          <input className={cn(INPUT, NUM)} defaultValue={f.pgl_deducted ?? ""} onBlur={(e) => set({ pgl_deducted: num(e.target.value) })} />
        </Field>
      </Card>
    </div>
  );
}
