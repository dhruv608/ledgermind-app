"use client";

import React, { useEffect, useMemo, useState } from "react";
import { toast } from "@/lib/notify";
import { Check, ChevronDown, Loader2, Pencil, Plus, Trash2, X } from "lucide-react";
import { Card } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { ConfirmDialog } from "@/components/ui/confirm-dialog";
import { api } from "@/lib/api";
import { cn } from "@/lib/utils";
import { FirmRule, FirmRuleInput, FirmRuleMatch } from "@/types/engagement";
import { SkeletonRows } from "@/components/common/SkeletonRows";
import { plural } from "@/lib/formatters";
import { Tabs } from "@/components/ui/tabs";
import { FirmMemory } from "@/components/rules/FirmMemory";

type Chart = { std_code: number; std_name: string; is_extended?: boolean }[];
const words = (text?: string) => (text || "").split(",").map((w) => w.trim()).filter(Boolean);
const inputClass =
  "w-full rounded-lg border border-slate-300 bg-white px-3 py-1.5 text-xs text-slate-800 focus:outline-none focus:ring-2 focus:ring-teal-200";
const EMPTY: FirmRuleInput = { words: "", except_words: "", std_code: 0, note: "", active: true };

/** The Account rules page: the firm's own rules, and the firm memory (codes accountants confirmed, by name). */
export default function AccountRulesPage() {
  const [view, setView] = useState<"rules" | "memory">("rules");
  // The count on each tab, read again after a change on either
  const [counts, setCounts] = useState<{ rules?: number; memory?: number }>({});
  const recount = () => {
    api.getFirmRules().then((r) => setCounts((c) => ({ ...c, rules: r.length }))).catch(() => {});
    api.getFirmMemory().then((m) => setCounts((c) => ({ ...c, memory: m.length }))).catch(() => {});
  };
  useEffect(() => { recount(); }, []);
  return (
    <div className="space-y-4">
      <Tabs label="Mapping" value={view} onChange={setView}
            items={[{ id: "rules", label: "Rules", count: counts.rules }, { id: "memory", label: "Firm memory", count: counts.memory }]} />
      {view === "rules" ? <AccountRules onChanged={recount} /> : <FirmMemory onChanged={recount} />}
    </div>
  );
}

/** The firm's own account-name rules: where an account goes when its name contains these words. */
function AccountRules({ onChanged }: { onChanged: () => void }) {
  const [rules, setRules] = useState<FirmRule[]>([]);
  const [chart, setChart] = useState<Chart>([]);
  const [loading, setLoading] = useState(true);
  const [editing, setEditing] = useState<number | "new" | null>(null);
  const [open, setOpen] = useState<number | null>(null);
  const [deleting, setDeleting] = useState<FirmRule | null>(null);

  const load = async () => {
    try {
      setRules(await api.getFirmRules());
      onChanged();
    } catch (err: any) {
      toast.error(err.message);
    } finally {
      setLoading(false);
    }
  };
  useEffect(() => {
    // eslint-disable-next-line react-hooks/set-state-in-effect -- load sets state only after its await (the server's answer)
    load();
    api.getMasterCOA().then((c) => setChart(c.filter((x) => !x.is_extended))).catch(() => {});
    // eslint-disable-next-line react-hooks/exhaustive-deps -- runs once on mount: load is recreated each render
  }, []);

  const remove = async () => {
    if (!deleting) return;
    try {
      await api.deleteFirmRule(deleting.id);
      toast.success("Rule deleted");
      setDeleting(null);
      load();
    } catch (err: any) {
      toast.error(err.message);
    }
  };

  return (
    <div className="space-y-4">
      <Card className="px-4 py-3.5">
        <div className="flex flex-wrap items-start justify-between gap-3">
          <p className="max-w-3xl text-[13px] leading-relaxed text-slate-600">
            The firm&apos;s own choices for client accounts: when an account&apos;s name contains these words, it goes to this
            code. Used for every client, before the AI is asked.
          </p>
          <Button type="button" variant="primary" size="sm" className="h-8 text-xs" onClick={() => setEditing("new")} disabled={editing === "new"}>
            <Plus className="mr-1 h-3.5 w-3.5" /> Add rule
          </Button>
        </div>
        <p className="mt-3 text-[11px] text-slate-500">
          <span className="font-semibold text-slate-700">How rules work:</span> whole words, any case (&quot;client meeting&quot;
          also matches &quot;Client Meetings&quot;). If two rules match, the more specific one wins (&quot;staff entertaining&quot; beats
          &quot;entertaining&quot;). Codes an accountant set and last year&apos;s codes are never changed by a rule.
        </p>
      </Card>

      {editing !== null && (
        <RuleEditor
          key={String(editing)}
          chart={chart}
          initial={editing === "new" ? EMPTY : rules.find((r) => r.id === editing) || EMPTY}
          id={editing === "new" ? undefined : editing}
          onCancel={() => setEditing(null)}
          onSaved={() => { setEditing(null); load(); }}
        />
      )}

      {loading ? (
        <Card className="overflow-hidden p-0">
          <div className="h-10 border-b border-slate-200 bg-slate-50" />
          <SkeletonRows rows={5} columns={3} label="Loading the rules" />
        </Card>
      ) : rules.length === 0 ? (
        <Card className="p-5 text-xs text-slate-500">No rules yet. Add the firm&apos;s first one.</Card>
      ) : (
        <Card className="overflow-hidden p-0">
          <div className="overflow-x-auto">
            <table className="w-full min-w-[640px] text-left text-xs">
              <thead className="border-b border-slate-200 bg-slate-50 text-[11px] uppercase tracking-wide text-slate-500">
                <tr>
                  <th className="px-4 py-2.5 font-semibold">When the account name has</th>
                  <th className="px-3 py-2.5 font-semibold">Code</th>
                  <th className="px-3 py-2.5 font-semibold">Used in</th>
                  <th className="w-20 px-3 py-2.5" />
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-100">
                {rules.map((rule) => {
                  const isOpen = open === rule.id;
                  const all = words(rule.words);
                  return (
                    <React.Fragment key={rule.id}>
                      <tr onClick={() => setOpen(isOpen ? null : rule.id)}
                          className={cn("cursor-pointer align-top transition hover:bg-slate-50", isOpen && "bg-slate-50", !rule.active && "opacity-60")}>
                        <td className="px-4 py-3">
                          <div className="flex items-start gap-2">
                            <ChevronDown className={cn("mt-0.5 h-3.5 w-3.5 shrink-0 text-slate-400 transition-transform", isOpen && "rotate-180")} />
                            <p className={cn("text-slate-800", !isOpen && "line-clamp-1")}>
                              {all.join(", ")}
                              {!rule.active && <span className="ml-2 rounded-full bg-slate-100 px-2 py-0.5 text-[11px] text-slate-500">Switched off</span>}
                            </p>
                          </div>
                        </td>
                        <td className="px-3 py-3">
                          <span className="font-mono text-sm font-bold text-teal-800">{String(rule.std_code).padStart(4, "0")}</span>
                          <span className="ml-2 text-slate-700">{rule.std_name}</span>
                        </td>
                        <td className="whitespace-nowrap px-3 py-3 text-slate-600">{plural(rule.matches ?? 0, "account")}</td>
                        <td className="px-3 py-2.5" onClick={(e) => e.stopPropagation()}>
                          <div className="flex justify-end gap-1">
                            <button type="button" onClick={() => setEditing(rule.id)} title="Change"
                                    className="rounded-md p-1.5 text-slate-500 hover:bg-slate-100 hover:text-slate-800">
                              <Pencil className="h-3.5 w-3.5" />
                            </button>
                            <button type="button" onClick={() => setDeleting(rule)} title="Delete"
                                    className="rounded-md p-1.5 text-slate-500 hover:bg-rose-50 hover:text-rose-600">
                              <Trash2 className="h-3.5 w-3.5" />
                            </button>
                          </div>
                        </td>
                      </tr>
                      {isOpen && (
                        <tr className="bg-slate-50/60">
                          <td colSpan={4} className="p-0">
                            {(words(rule.except_words).length > 0 || rule.note) && (
                              <div className="space-y-1 px-4 pt-3 text-[11px] text-slate-600">
                                {words(rule.except_words).length > 0 && (
                                  <p><span className="font-medium text-slate-700">Not if the name also has:</span> {words(rule.except_words).join(", ")}</p>
                                )}
                                {rule.note && <p><span className="font-medium text-slate-700">Note:</span> {rule.note}</p>}
                              </div>
                            )}
                            <RuleMatches rule={rule} onApplied={load} />
                          </td>
                        </tr>
                      )}
                    </React.Fragment>
                  );
                })}
              </tbody>
            </table>
          </div>
        </Card>
      )}

      <ConfirmDialog
        isOpen={deleting !== null}
        onClose={() => setDeleting(null)}
        onConfirm={remove}
        title="Delete this rule?"
        description={`Accounts already coded stay as they are; new uploads no longer use the rule "${words(deleting?.words).slice(0, 3).join(", ")}".`}
        confirmText="Delete rule"
      />
    </div>
  );
}

/** Add or change one rule. */
function RuleEditor({ chart, initial, id, onCancel, onSaved }: {
  chart: Chart; initial: FirmRuleInput; id?: number; onCancel: () => void; onSaved: () => void;
}) {
  const [rule, setRule] = useState<FirmRuleInput>(initial);
  const [codeText, setCodeText] = useState(initial.std_code ? String(initial.std_code) : "");
  const [saving, setSaving] = useState(false);
  const names = useMemo(() => new Map(chart.map((c) => [c.std_code, c.std_name])), [chart]);
  const code = parseInt(codeText, 10);
  const codeName = names.get(code);

  const save = async () => {
    if (!words(rule.words).length) return toast.error("Give at least one word");
    if (!codeName) return toast.error("Choose a code from the firm chart");
    setSaving(true);
    try {
      await api.saveFirmRule({ ...rule, std_code: code }, id);
      toast.success(id ? "Rule changed" : "Rule added", { description: "New uploads use it. Open its accounts to apply it to clients already coded." });
      onSaved();
    } catch (err: any) {
      toast.error(err.message);
    } finally {
      setSaving(false);
    }
  };

  return (
    <Card className="border-teal-200 p-4">
      <p className="mb-3 text-sm font-semibold text-slate-900">{id ? "Change rule" : "New rule"}</p>
      <div className="grid gap-3 sm:grid-cols-2">
        <label className="block text-[11px] font-semibold text-slate-700">
          Account name contains (comma separated)
          <textarea rows={2} value={rule.words} onChange={(e) => setRule({ ...rule, words: e.target.value })}
                    placeholder="christmas party, staff party" className={cn(inputClass, "mt-1 font-normal")} />
        </label>
        <label className="block text-[11px] font-semibold text-slate-700">
          Except when it also contains (optional)
          <textarea rows={2} value={rule.except_words || ""} onChange={(e) => setRule({ ...rule, except_words: e.target.value })}
                    placeholder="income, recharge" className={cn(inputClass, "mt-1 font-normal")} />
        </label>
        <label className="block text-[11px] font-semibold text-slate-700">
          Goes to code
          <input list="firm-rule-codes" value={codeText} onChange={(e) => setCodeText(e.target.value.split(" ")[0])}
                 placeholder="Type a code or a name, e.g. 3070" className={cn(inputClass, "mt-1 font-mono font-normal")} />
          <datalist id="firm-rule-codes">
            {chart.map((c) => <option key={c.std_code} value={`${c.std_code} ${c.std_name}`} />)}
          </datalist>
          <span className={cn("mt-1 block font-normal", codeName ? "text-emerald-700" : "text-slate-400")}>
            {codeName || (codeText ? "Not a code in the firm chart" : "The firm chart's code")}
          </span>
        </label>
        <label className="block text-[11px] font-semibold text-slate-700">
          Note (why, for the team)
          <input value={rule.note || ""} onChange={(e) => setRule({ ...rule, note: e.target.value })}
                 placeholder="Staff parties: accountant's choice" className={cn(inputClass, "mt-1 font-normal")} />
          <span className="mt-2 flex items-center gap-1.5 font-normal text-slate-600">
            <input type="checkbox" checked={rule.active} onChange={(e) => setRule({ ...rule, active: e.target.checked })}
                   className="h-3.5 w-3.5 rounded border-slate-300 text-teal-700" />
            Rule switched on
          </span>
        </label>
      </div>
      <div className="mt-4 flex justify-end gap-2">
        <Button type="button" variant="ghost" size="sm" className="h-8 text-xs" onClick={onCancel}>
          <X className="mr-1 h-3.5 w-3.5" /> Cancel
        </Button>
        <Button type="button" variant="primary" size="sm" className="h-8 text-xs" onClick={save} disabled={saving}>
          {saving ? <Loader2 className="mr-1 h-3.5 w-3.5 animate-spin" /> : <Check className="mr-1 h-3.5 w-3.5" />}
          {id ? "Save rule" : "Add rule"}
        </Button>
      </div>
    </Card>
  );
}

/** The client accounts a rule decides: what they have now, and applying the rule to those the AI coded. */
function RuleMatches({ rule, onApplied }: { rule: FirmRule; onApplied: () => void }) {
  const [rows, setRows] = useState<FirmRuleMatch[] | null>(null);
  const [confirming, setConfirming] = useState(false);
  const [applying, setApplying] = useState(false);
  const load = () => api.getFirmRuleMatches(rule.id).then(setRows).catch((err) => toast.error(err.message));
  useEffect(() => { load(); }, [rule.id, rule.std_code, rule.words, rule.except_words]); // eslint-disable-line react-hooks/exhaustive-deps

  const changing = (rows || []).filter((r) => r.would_change);
  const apply = async () => {
    setApplying(true);
    try {
      const res = await api.applyFirmRule(rule.id);
      toast.success(`${plural(res.changed, "account")} moved to ${rule.std_code}`, { description: `${plural(res.clients, "client")}: their review and workbook show as out of date.` });
      setConfirming(false);
      load();
      onApplied();
    } catch (err: any) {
      toast.error(err.message);
    } finally {
      setApplying(false);
    }
  };

  if (rows === null) return <SkeletonRows rows={3} columns={4} label="Loading the accounts" className="border-t border-slate-100" />;
  return (
    <div className="border-t border-slate-100 px-4 py-3">
      {rows.length === 0 ? (
        <p className="text-[11px] text-slate-500">No client account matches this rule yet.</p>
      ) : (
        <>
          <div className="mb-2 flex flex-wrap items-center justify-between gap-2">
            <p className="text-[11px] text-slate-600">
              {changing.length
                ? <><span className="font-semibold text-amber-700">{changing.length}</span> {changing.length === 1 ? "account" : "accounts"} the AI coded differently would move to {rule.std_code}.</>
                : "Every account the rule decides already has its code, or keeps a code an accountant chose."}
            </p>
            {changing.length > 0 && rule.active && (
              <Button type="button" variant="primary" size="sm" className="h-7 text-[11px]" onClick={() => setConfirming(true)}>
                Apply to {plural(changing.length, "account")}
              </Button>
            )}
          </div>
          <div className="overflow-x-auto">
            <table className="w-full min-w-[560px] text-left text-[11px]">
              <thead className="text-slate-500">
                <tr className="border-b border-slate-100">
                  <th className="py-1.5 pr-3 font-medium">Client</th>
                  <th className="py-1.5 pr-3 font-medium">Account</th>
                  <th className="py-1.5 pr-3 font-medium">Code now</th>
                  <th className="py-1.5 font-medium">With this rule</th>
                </tr>
              </thead>
              <tbody>
                {rows.map((r) => (
                  <tr key={`${r.engagement_id}-${r.account}`} className="border-b border-slate-50">
                    <td className="py-1.5 pr-3 text-slate-700">{r.client}</td>
                    <td className="py-1.5 pr-3 text-slate-800">{r.account}</td>
                    <td className="py-1.5 pr-3 text-slate-600"><span className="font-mono">{r.current_code ?? "-"}</span> {r.current_name}</td>
                    <td className="py-1.5">
                      {r.would_change ? (
                        <span className="rounded-full bg-amber-50 px-2 py-0.5 font-medium text-amber-800">Moves to {rule.std_code}</span>
                      ) : r.current_code === rule.std_code ? (
                        <span className="rounded-full bg-emerald-50 px-2 py-0.5 text-emerald-700">Already {rule.std_code}</span>
                      ) : (
                        <span className="rounded-full bg-slate-100 px-2 py-0.5 text-slate-600">Kept: {r.kept_because}</span>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </>
      )}
      <ConfirmDialog
        isOpen={confirming}
        onClose={() => setConfirming(false)}
        onConfirm={apply}
        isLoading={applying}
        title={`Move ${plural(changing.length, "account")} to ${rule.std_code}?`}
        description={`${rule.std_name}. Only accounts the AI coded change; codes an accountant chose stay. The clients' review and workbook will need running again.`}
        confirmText="Apply rule"
      />
    </div>
  );
}
