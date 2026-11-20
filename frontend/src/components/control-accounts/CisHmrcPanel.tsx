"use client";

import { useEffect, useMemo, useState } from "react";
import { HardHat, Save } from "lucide-react";
import { toast } from "@/lib/notify";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { CustomSelect } from "@/components/ui/custom-select";
import { SectionHeader } from "@/components/ui/section-header";
import { SkeletonRows } from "@/components/common/SkeletonRows";
import { CisChecksList } from "@/components/control-accounts/CisChecksList";
import { api, CisHmrcScreen } from "@/lib/api";
import { formatCurrency } from "@/lib/formatters";
import { cn } from "@/lib/utils";

type Draft = Record<string, Record<string, string>>;   // tax month -> field -> typed text
type Column = { key: string; label: string; hint: string; books?: "deducted" | "suffered" };

const CONTRACTOR: Column[] = [
  { key: "gross", label: "Paid to subcontractors", hint: "CIS300 gross, no VAT" },
  { key: "materials", label: "Materials", hint: "CIS300" },
  { key: "deducted", label: "CIS deducted", hint: "CIS300", books: "deducted" },
];
const SUBCONTRACTOR: Column[] = [
  { key: "suffered_statements", label: "CIS suffered", hint: "Contractors' statements", books: "suffered" },
  { key: "claimed_eps", label: "Claimed on EPS", hint: "EPS / payroll" },
];
const PAYE: Column[] = [
  { key: "paye_tax", label: "PAYE tax", hint: "FPS" },
  { key: "employer_nic", label: "Employer NI", hint: "FPS" },
  { key: "employee_nic", label: "Employee NI", hint: "FPS" },
  { key: "student_loan", label: "Student loan", hint: "FPS" },
  { key: "allowance", label: "Employment allowance", hint: "EPS" },
  { key: "paid_to_hmrc", label: "Paid to HMRC", hint: "HMRC account" },
  { key: "interest", label: "Interest / penalties", hint: "HMRC account" },
];
const YEAR = [
  { key: "balance_bf", label: "HMRC balance at the year start £", type: "money" },
  { key: "balance_cf", label: "HMRC balance at the year end £", type: "money" },
  { key: "repayment_amount", label: "Repayment claimed £", type: "money" },
  { key: "repayment_date", label: "Repayment claimed on", type: "date" },
];

const text = (v: unknown) => (v === null || v === undefined ? "" : String(v));
const amount = (s: string) => {
  const t = s.replace(/[£,\s]/g, "");
  return t === "" ? null : Number(t);
};

/** What was filed with HMRC, per tax month (6th to 5th), beside the books on a cash basis. Shown for a
 * client whose books have the CIS tax accounts (4421 / 5321); the CIS tests compare the two. */
export function CisHmrcPanel({ engagementId, onSaved }: { engagementId: string; onSaved?: () => void }) {
  const [data, setData] = useState<CisHmrcScreen | null>(null);
  const [draft, setDraft] = useState<Draft>({});
  const [year, setYear] = useState<Record<string, string>>({});
  const [mode, setMode] = useState("MANUAL");
  const [dirty, setDirty] = useState(false);
  const [saving, setSaving] = useState(false);
  const [loading, setLoading] = useState(true);
  const [checksKey, setChecksKey] = useState(0);

  const fill = (d: CisHmrcScreen) => {
    setData(d);
    setMode(d.mode || "MANUAL");
    setDraft(Object.fromEntries((d.months || []).map((m) => [m.tax_month, Object.fromEntries(Object.entries(m.hmrc).map(([k, v]) => [k, text(v)]))])));
    setYear(Object.fromEntries(Object.entries(d.year || {}).map(([k, v]) => [k, text(v)])));
    setDirty(false);
  };

  useEffect(() => {
    api.getCisHmrc(engagementId).then(fill).catch(() => setData(null)).finally(() => setLoading(false));
  }, [engagementId]);

  const sides = data?.sides;
  const columns = useMemo(
    () => [...(sides?.includes("deducted") ? CONTRACTOR : []), ...(sides?.includes("suffered") ? SUBCONTRACTOR : []), ...PAYE],
    [sides],
  );
  const problems = Object.entries(draft).flatMap(([m, f]) =>
    Object.entries(f).filter(([k, v]) => k !== "filed" && k !== "filed_on" && k !== "note" && v.trim() && Number.isNaN(amount(v) ?? 0)).map(() => m));

  if (loading) return <Card><SkeletonRows rows={4} columns={5} label="Loading the HMRC CIS figures" /></Card>;
  if (!data?.on) return null;

  const set = (month: string, key: string, value: string) => {
    setDraft((d) => ({ ...d, [month]: { ...(d[month] || {}), [key]: value } }));
    setDirty(true);
  };

  const save = async () => {
    setSaving(true);
    try {
      const months = Object.fromEntries(Object.entries(draft).map(([m, f]) => [m, Object.fromEntries(
        Object.entries(f).map(([k, v]) => [k, ["filed", "filed_on", "note"].includes(k) ? v || null : amount(v)]))]));
      const y = Object.fromEntries(Object.entries(year).map(([k, v]) => [k, k === "repayment_date" ? v || null : amount(v)]));
      fill(await api.saveCisHmrc(engagementId, { mode, months, year: y }));
      toast.success("HMRC CIS figures saved");
      setChecksKey((k) => k + 1);
      onSaved?.();
    } catch (e) {
      toast.error(e instanceof Error ? e.message : "Could not save the HMRC CIS figures");
    } finally {
      setSaving(false);
    }
  };

  const inputClass = "w-full min-w-[84px] rounded-md border border-slate-200 bg-amber-50/40 px-2 py-1 text-right font-mono text-xs focus:outline-none focus:ring-2 focus:ring-teal-200";

  return (
    <Card className="overflow-hidden">
      <SectionHeader
        icon={HardHat}
        title="CIS: what was filed with HMRC"
        description={
          <>
            One row per tax month (6th to 5th). Type the figures from the CIS300 returns, the contractors&apos; statements
            and the EPS, and the HMRC PAYE / CIS account. The books on a cash basis are shown under each CIS figure.
          </>
        }
        className="border-b border-slate-100 p-5"
        actions={
          <>
            <div className="w-48">
              <CustomSelect size="sm" fullWidth value={mode} onChange={(v) => { setMode(v); setDirty(true); }}
                options={[{ value: "MANUAL", label: "Typed from HMRC papers" }, { value: "NOT_AVAILABLE", label: "Not available yet" }]} />
            </div>
            <Button variant="primary" size="sm" onClick={save} disabled={saving || !dirty || problems.length > 0}>
              <Save className="mr-1 h-3.5 w-3.5" /> {saving ? "Saving…" : "Save"}
            </Button>
          </>
        }
      />

      {mode === "NOT_AVAILABLE" ? (
        <p className="px-5 py-6 text-xs text-slate-600">
          Every month is &ldquo;HMRC unverified&rdquo;: the CIS working runs on the books only, and the client is asked for
          the CIS300 returns, EPS reports and the HMRC PAYE / CIS account statement. The accounts cannot be signed off
          like this.
        </p>
      ) : (
        <>
          <div className="overflow-x-auto">
            <table className="w-full text-xs">
              <thead className="bg-slate-50 text-[11px] text-slate-500">
                <tr>
                  <th className="sticky left-0 z-10 bg-slate-50 px-4 py-2 text-left font-semibold">Tax month</th>
                  {sides?.includes("deducted") && <th className="px-2 py-2 text-left font-semibold">CIS300 filed</th>}
                  {columns.map((c) => (
                    <th key={c.key} className="px-2 py-2 text-right font-semibold">
                      <span className="block whitespace-nowrap">{c.label}</span>
                      <span className="block font-normal text-slate-400">{c.hint}</span>
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-100">
                {(data.months || []).map((m) => {
                  const f = draft[m.tax_month] || {};
                  return (
                    <tr key={m.tax_month}>
                      <td className="sticky left-0 z-10 whitespace-nowrap bg-white px-4 py-2 text-slate-700">
                        <span className="block font-medium">{m.label}</span>
                        <span className="text-[11px] text-slate-400">Month {m.month_no}, {m.tax_year}</span>
                      </td>
                      {sides?.includes("deducted") && (
                        <td className="px-2 py-2">
                          <div className="w-24">
                            <CustomSelect size="sm" fullWidth value={f.filed || ""} placeholder="Choose" onChange={(v) => set(m.tax_month, "filed", v)}
                              options={[{ value: "YES", label: "Yes" }, { value: "NIL", label: "Nil return" }, { value: "NO", label: "Not filed" }]} />
                          </div>
                        </td>
                      )}
                      {columns.map((c) => {
                        const books = c.books ? m.books[c.books] : undefined;
                        const typed = amount(f[c.key] || "");
                        const diff = books != null && typed != null ? Math.round((books - typed) * 100) / 100 : null;
                        return (
                          <td key={c.key} className="px-2 py-2 align-top">
                            <input inputMode="decimal" value={f[c.key] || ""} placeholder="0.00" onChange={(e) => set(m.tax_month, c.key, e.target.value)}
                              className={cn(inputClass, Number.isNaN(typed ?? 0) && "border-rose-400 bg-rose-50")} />
                            {books !== undefined && (
                              <span className={cn("mt-0.5 block text-right text-[10px]", diff && Math.abs(diff) >= 1 ? "text-rose-600" : "text-slate-400")}>
                                Books {books == null ? "-" : formatCurrency(books)}{diff && Math.abs(diff) >= 1 ? ` · diff ${formatCurrency(diff)}` : ""}
                              </span>
                            )}
                          </td>
                        );
                      })}
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
          <div className="grid gap-3 border-t border-slate-100 p-4 sm:grid-cols-4">
            {YEAR.map((y) => (
              <label key={y.key} className="block text-[11px] text-slate-600">
                {y.label}
                <input type={y.type === "date" ? "date" : "text"} inputMode={y.type === "date" ? undefined : "decimal"} value={year[y.key] || ""}
                  onChange={(e) => { setYear((v) => ({ ...v, [y.key]: e.target.value })); setDirty(true); }}
                  className={cn(inputClass, "mt-1", y.type === "date" && "text-left")} />
              </label>
            ))}
          </div>
          {problems.length > 0 && <p className="px-5 pb-4 text-[11px] text-rose-700">Some figures are not amounts (the boxes in red): correct them to save.</p>}
        </>
      )}
      <CisChecksList engagementId={engagementId} refreshKey={checksKey} />
    </Card>
  );
}
