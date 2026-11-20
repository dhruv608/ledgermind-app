"use client";

import { Card } from "@/components/ui/card";
import { SectionHeader } from "@/components/ui/section-header";
import { StatusChip } from "@/components/ui/status-chip";
import { Button } from "@/components/ui/button";
import { CustomSelect } from "@/components/ui/custom-select";
import {
  ClientStep, Field, MaterialityStep, PoliciesStep, PriorYearStep, SetupSection,
} from "@/components/setup/SetupFields";
import { SetupStatusPanel } from "@/components/setup/SetupStatusPanel";
import { SlidersHorizontal, Sparkles, Check, RefreshCw } from "lucide-react";
import { SECTIONS } from "./client-setup/sections";
import { ClientSetupPanelProps, useClientSetup } from "./client-setup/useClientSetup";
import { IndustryStep } from "./client-setup/IndustryStep";
import { TaxStep } from "./client-setup/TaxStep";
import { PeopleStep } from "./client-setup/PeopleStep";

/** The client's facts that are not in the books: industry, VAT, payroll, tax, directors, properties. */
export function ClientSetupPanel(props: ClientSetupPanelProps) {
  const s = useClientSetup(props);
  const {
    profile, setProfile, savedSnapshot, isDirty, dirtySections, pick, status, statusLoading, catalogue, setup, setS,
    suggestionFor, isDetecting, handleAutoDetect, savingKeys, handleSave, carriedInfo, setOpenKeys, sectionProps,
    savedCount,
  } = s;

  return (
    <Card className="border-0 bg-transparent p-0 shadow-none">
      <SectionHeader
        icon={SlidersHorizontal}
        title="Client details" page
        description="Once per client per year, part by part: each answer switches checks on or off (the panel on the right updates as you type). Saved settings carry over to next year."
        className="mb-5"
        actions={
          savedSnapshot && isDirty ? <StatusChip tone="warning">Unsaved changes</StatusChip> : undefined
        }
      />
      <div className="grid gap-5 lg:grid-cols-[minmax(0,1fr)_280px]">
        <div className="min-w-0 space-y-5">
          {carriedInfo && (
            <p className="rounded-lg border border-sky-200 bg-sky-50 px-3 py-2 text-[11px] text-sky-800">
              Carried over from last year ({carriedInfo.from ? new Date(carriedInfo.from).toLocaleDateString("en-GB") : "the year before"}):
              check each part marked <strong>From last year</strong> and confirm it. Materiality and last year&apos;s issues
              start fresh each year.
            </p>
          )}

          {/* Progress, and open / close all parts */}
          <div className="flex flex-wrap items-center justify-between gap-2">
            <p className="text-[11px] text-slate-500">
              <span className="font-semibold text-slate-800">{savedCount} of {SECTIONS.length}</span> parts saved
              {isDirty && <span className="text-amber-700"> · {dirtySections.length} with unsaved changes</span>}
            </p>
            <div className="flex items-center gap-1">
              <button type="button" onClick={handleAutoDetect} disabled={isDetecting}
                      title="Reads the account names, suppliers and tax codes again to suggest the industry, VAT, payroll and CIS. Saved answers are kept."
                      className="mr-1 inline-flex items-center gap-1 rounded-md border border-teal-200 bg-teal-50 px-2 py-1 text-[11px] font-medium text-teal-800 hover:bg-teal-100 disabled:opacity-50">
                {isDetecting ? <RefreshCw className="h-3 w-3 animate-spin" /> : <Sparkles className="h-3 w-3" />}
                Suggest from the accounts
              </button>
              <button type="button" onClick={() => setOpenKeys(new Set(SECTIONS.map((x) => x.key)))}
                      className="rounded-md px-2 py-1 text-[11px] font-medium text-slate-600 hover:bg-slate-100">Expand all</button>
              <button type="button" onClick={() => setOpenKeys(new Set())}
                      className="rounded-md px-2 py-1 text-[11px] font-medium text-slate-600 hover:bg-slate-100">Collapse all</button>
              {dirtySections.length > 1 && (
                <Button type="button" variant="primary" size="sm" onClick={() => handleSave(dirtySections)} disabled={savingKeys.length > 0}
                        className="ml-1 h-7 text-[11px]">
                  {savingKeys.length > 1 ? <RefreshCw className="mr-1 h-3 w-3 animate-spin" /> : <Check className="mr-1 h-3 w-3" />}
                  Save all ({dirtySections.length})
                </Button>
              )}
            </div>
          </div>

          <div className="space-y-2">
          <SetupSection {...sectionProps("engagement", 1)}>
            <div className="space-y-5">
              <Field label="Accounting framework" hint="Required: decides which reporting rules apply">
                <CustomSelect
                  fullWidth
                  value={profile.accounting_framework || ""}
                  placeholder="Choose the framework"
                  onChange={(v) => pick("accounting_framework", v)}
                  options={[
                    { value: "FRS105", label: "FRS 105 (micro-entities)" },
                    { value: "FRS102_1A", label: "FRS 102 1A (small entities)" },
                    { value: "FULL_FRS102", label: "FRS 102 (full)" },
                    { value: "IFRS", label: "UK adopted IFRS" },
                  ]}
                />
              </Field>
              {suggestionFor("accounting_framework")}
              <ClientStep setup={setup} set={setS} record={status?.record || null} />
              {suggestionFor("prior_year_tb_gl")}
            </div>
          
          </SetupSection>

          <SetupSection {...sectionProps("industry", 2)}>
            <IndustryStep s={s} />
          </SetupSection>

          <SetupSection {...sectionProps("tax", 3)}>
            <TaxStep s={s} />
          </SetupSection>

          <SetupSection {...sectionProps("people", 4)}>
            <PeopleStep s={s} />
          </SetupSection>

          <SetupSection {...sectionProps("policies", 5)}>
            <PoliciesStep
              setup={setup}
              set={setS}
              capitalisation={profile.capitalisation_threshold || 500}
              onCapitalisation={(v) => setProfile((prev) => ({ ...prev, capitalisation_threshold: v }))}
            />
          
          </SetupSection>

          <SetupSection {...sectionProps("materiality", 6)}>
            <MaterialityStep
              setup={setup}
              set={setS}
              record={status?.record || null}
              suggestion={status?.suggestions?.materiality}
              onOverall={(v) => setProfile((prev) => ({ ...prev, materiality_threshold: v }))}
            />
          
          </SetupSection>

          <SetupSection {...sectionProps("last_year", 7)}>
          <PriorYearStep setup={setup} set={setS} issues={catalogue?.prior_year_issues || []} />
          </SetupSection>

          </div>
        </div>

        <div className="lg:sticky lg:top-28 lg:self-start">
          {isDirty && (
            <p className="mb-2 rounded-lg border border-amber-200 bg-amber-50 px-2.5 py-1.5 text-[11px] text-amber-800">
              Showing the checks for your unsaved answers: save to keep them.
            </p>
          )}
          <SetupStatusPanel status={status} loading={statusLoading} />
        </div>
      </div>
    </Card>
  );
}
