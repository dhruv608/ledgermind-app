"use client";

import { AlertTriangle, BookOpen, Loader2, Search, Sparkles, Users } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { SectionHeader } from "@/components/ui/section-header";
import { SkeletonRows } from "@/components/common/SkeletonRows";
import { formatCurrency } from "@/lib/formatters";
import { cn } from "@/lib/utils";
import { Stat, View } from "./books-panel/common";
import { useBooks } from "./books-panel/useBooks";
import { OpeningList } from "./books-panel/OpeningList";
import { BankList } from "./books-panel/BankList";
import { SalesList } from "./books-panel/SalesList";
import { BillsList } from "./books-panel/BillsList";
import { Questions } from "./books-panel/Questions";
import { TrialBalanceChecks } from "./books-panel/TrialBalanceChecks";
import { AiSuggestions } from "./books-panel/AiSuggestions";

interface BooksPanelProps {
  engagementId: string;
  onGoToSetup: () => void;
  /** After the trial balance is made: the client page reloads its accounts. */
  onTrialBalanceMade: () => void;
}

/** The books of a client with no accounting software, prepared from the bank statement and the Dext lists. */
export function BooksPanel({ engagementId, onGoToSetup, onTrialBalanceMade }: BooksPanelProps) {
  const {
    data, error, view, setView, onlyToCheck, setOnlyToCheck, search, setSearch, saving, making, suggesting,
    choose, suggestWithAi, makeTrialBalance,
  } = useBooks(engagementId, onTrialBalanceMade);

  if (error) {
    return (
      <div className="rounded-xl border border-rose-200 bg-rose-50 p-4 text-sm text-rose-800">
        {error}
      </div>
    );
  }
  if (!data) return <SkeletonRows rows={8} columns={4} label="Preparing the books" />;

  const openQuestions = data.questions.filter((q) => !q.answered).length;
  const views: { id: View; label: string; badge?: number }[] = [
    { id: "bank", label: "Bank", badge: data.bank.filter((r) => r.check).length },
    ...(data.bank.some((r) => r.ai && !r.chosen && r.check)
      ? [{ id: "ai" as View, label: "AI suggestions", badge: new Set(data.bank.filter((r) => r.ai && !r.chosen && r.check).map((r) => r.payee || r.key)).size }]
      : []),
    { id: "sales", label: "Sales invoices" },
    { id: "bills", label: "Bills", badge: data.bills.filter((b) => b.check).length },
    ...(data.opening.length ? [{ id: "opening" as View, label: "Last year's TB", badge: data.opening.filter((o) => !o.sure && !o.chosen).length }] : []),
    { id: "questions", label: "Client questions", badge: openQuestions },
  ];

  const listed = view !== "questions" && view !== "ai";
  return (
    <div className="space-y-4">
      <Card className="space-y-4 p-5">
        <SectionHeader
          icon={BookOpen}
          title="Books" page
          description="Prepared from the bank statement and Dext. Check the highlighted lines; for the rest the app shows why it chose what it did. Then make the trial balance: the Accounts, Review and Workbook tabs follow from it."
          actions={
            <Button size="sm" variant="primary" className="whitespace-nowrap" onClick={makeTrialBalance}
                    disabled={making || Math.abs(data.checks.out_of_balance) > 0.005}
                    title={Math.abs(data.checks.out_of_balance) > 0.005 ? "The books do not balance yet" : "The Accounts, Review and Workbook tabs then use these books"}>
              {making ? <Loader2 className="mr-1.5 h-3.5 w-3.5 animate-spin" /> : null}
              Make trial balance
            </Button>
          }
        />

        {!data.directors_known && (
          <div className="flex flex-col gap-2 rounded-xl border border-amber-200 bg-amber-50 p-3 text-xs text-amber-900 sm:flex-row sm:items-center sm:justify-between">
            <span className="flex items-center gap-2">
              <Users className="h-4 w-4 shrink-0" />
              {data.company_to_confirm
                ? `Companies House has no exact match for this name. Is it ${data.company_to_confirm}? Confirm the company on the Setup tab (People), so the directors are filled in and payments to and from them are recognised.`
                : "Add the directors on the Setup tab, so payments to and from them are recognised."}
            </span>
            <Button size="sm" variant="outline" className="shrink-0 whitespace-nowrap" onClick={onGoToSetup}>Go to setup</Button>
          </div>
        )}

        {data.file_problems.length > 0 && (
          <details className="rounded-xl border border-amber-200 bg-amber-50/40 px-3 py-2.5 text-xs">
            <summary className="cursor-pointer font-semibold text-amber-900">
              <AlertTriangle className="mr-1 inline h-3.5 w-3.5" /> File check: {data.file_problems.length} thing
              {data.file_problems.length > 1 ? "s" : ""} in the client&apos;s files
            </summary>
            <ul className="mt-2 list-disc space-y-1 pl-5 text-slate-700">
              {data.file_problems.map((p, i) => <li key={i}>{p.text}</li>)}
            </ul>
          </details>
        )}

        <div className="grid grid-cols-2 gap-3 sm:grid-cols-5">
          <Stat label="Bank lines" value={String(data.summary.bank_lines)} />
          <Stat label="To check" value={String(data.summary.to_check)} warn={data.summary.to_check > 0} />
          <Stat label="Debtors" value={formatCurrency(data.summary.debtors, { showPence: false })} />
          <Stat label="Creditors" value={formatCurrency(data.summary.creditors, { showPence: false })} />
          <Stat label="Client questions" value={String(openQuestions)} warn={openQuestions > 0} />
        </div>

        <TrialBalanceChecks data={data} />
      </Card>

      <Card className="p-0">
        <div className="flex flex-col gap-3 border-b border-slate-100 px-5 py-3.5 lg:flex-row lg:items-center lg:justify-between">
          <div className="inline-flex flex-wrap gap-1 self-start rounded-lg border border-slate-200 bg-white p-1">
            {views.map((v) => (
              <button
                key={v.id}
                type="button"
                onClick={() => { setView(v.id); setSearch(""); }}
                className={cn(
                  "rounded-md px-3 py-1.5 text-xs font-medium transition",
                  view === v.id ? "bg-teal-700 text-white" : "text-slate-600 hover:bg-slate-100"
                )}
              >
                {v.label}
                {v.badge ? (
                  <span className={cn("ml-1.5 font-mono text-[11px]", view === v.id ? "text-teal-100" : "text-amber-600")}>{v.badge}</span>
                ) : null}
              </button>
            ))}
          </div>
          {listed && (
            <div className="flex flex-wrap items-center gap-2">
              {view === "bank" && data.bank.some((r) => r.head === "Unsorted" && !r.chosen) && (
                <Button size="sm" variant="outline" className="h-8 border-teal-200 text-xs text-teal-800 hover:bg-teal-50"
                        disabled={suggesting} onClick={suggestWithAi}>
                  {suggesting ? <Loader2 className="mr-1 h-3.5 w-3.5 animate-spin" /> : <Sparkles className="mr-1 h-3.5 w-3.5" />}
                  {suggesting ? "Asking the AI…" : "Suggest with AI"}
                </Button>
              )}
              <div className="relative w-full sm:w-56">
                <Search className="absolute left-2.5 top-2.5 h-3.5 w-3.5 text-slate-400" />
                <Input
                  type="text"
                  placeholder={view === "bank" ? "Search bank lines" : view === "bills" ? "Search supplier or number" : view === "opening" ? "Search account" : "Search customer or invoice"}
                  value={search}
                  onChange={(e) => setSearch(e.target.value)}
                  className="h-8 border-slate-200 bg-white pl-8 text-xs"
                />
              </div>
              <div className="inline-flex rounded-lg border border-slate-200 bg-white p-0.5 text-xs">
                {[true, false].map((only) => (
                  <button
                    key={String(only)}
                    type="button"
                    onClick={() => setOnlyToCheck(only)}
                    className={cn(
                      "rounded-md px-2.5 py-1 font-medium transition",
                      onlyToCheck === only ? "bg-teal-50 text-teal-800" : "text-slate-600 hover:text-slate-900"
                    )}
                  >
                    {only ? (view === "sales" ? "Unpaid" : "To check") : "All"}
                  </button>
                ))}
              </div>
            </div>
          )}
        </div>

        <div className={listed ? "" : "p-5"}>
          {view === "ai" && (
            <AiSuggestions rows={data.bank} chart={data.chart ?? []} saving={saving} onChoose={choose} />
          )}
          {view === "bank" && (
            <BankList rows={data.bank} choices={data.choices} chart={data.chart ?? []} onlyToCheck={onlyToCheck} search={search} saving={saving} onChoose={choose} />
          )}
          {view === "sales" && <SalesList data={data} onlyUnpaid={onlyToCheck} search={search} />}
          {view === "bills" && (
            <BillsList bills={data.bills} choices={data.choices} chart={data.chart ?? []} onlyToCheck={onlyToCheck} search={search} saving={saving} onChoose={choose} />
          )}
          {view === "opening" && (
            <OpeningList lines={data.opening} chart={data.chart ?? []} onlyToCheck={onlyToCheck} search={search} saving={saving} onChoose={choose} />
          )}
          {view === "questions" && <Questions questions={data.questions} client={data.client} yearEnd={data.year_end} saving={saving} onChoose={choose} />}
        </div>
      </Card>

    </div>
  );
}
