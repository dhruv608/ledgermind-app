// Setup step 2: the industry, its questions, and the properties the company owns or lets.

import { Building2, Sparkles, RefreshCw, Plus, X } from "lucide-react";
import { Button } from "@/components/ui/button";
import { CustomSelect } from "@/components/ui/custom-select";
import { UK_INDUSTRIES, getIndustryBadge } from "@/lib/badges";
import { IndustryQuestions } from "@/components/setup/SetupFields";
import type { ClientSetupState } from "./useClientSetup";

export function IndustryStep({ s }: { s: ClientSetupState }) {
  const {
    currentBadge, profile, pick, suggestionFor, setup, setS, catalogue, status, properties, showProperties,
    setShowProperties, handleSuggestProperties, isSuggesting, setProperties, updateProperty,
  } = s;
  return (
            <div className="space-y-6">
        {/* Section 1: Industry Sector */}
        <div className="space-y-2">
          <label className="flex items-center justify-between text-xs font-bold text-slate-800">
            <span className="flex items-center space-x-1.5">
              <Building2 className="w-3.5 h-3.5 text-slate-500" />
              <span>Industry (turns on the industry checks)</span>
            </span>
            <span className={`inline-flex items-center gap-1 px-2 py-0.5 rounded-md text-[11px] font-semibold border ${currentBadge.className}`}>
              <currentBadge.icon className="w-3 h-3" /> {currentBadge.label}
            </span>
          </label>

          <CustomSelect
            fullWidth
            size="lg"
            value={profile.industry_code || "UNIV"}
            onChange={(v) => pick("industry_code", v)}
            options={UK_INDUSTRIES.map((ind) => {
              const IndIcon = getIndustryBadge(ind.code).icon;
              return {
                value: ind.code,
                label: ind.name,
                description: ind.desc,
                icon: <IndIcon className="h-3.5 w-3.5 text-slate-500" />,
              };
            })}
          />
        </div>

              {suggestionFor("industry_code")}
              <IndustryQuestions setup={setup} set={setS} industry={catalogue?.industries?.[profile.industry_code || ""]}
                                 evidence={status?.suggestions?.industry_answers?.value} />
              {profile.industry_code === "PRP" || properties.length > 0 || showProperties ? (
                <>
        {/* Section 6: Properties */}
        <div>
          <div className="flex items-center justify-between mb-1">
            <label className="block text-[11px] font-bold text-slate-700">
              Properties (each one held to earn rent, or to sell)
            </label>
            <div className="flex gap-2">
              <Button type="button" size="sm" variant="outline" onClick={handleSuggestProperties}
                      disabled={isSuggesting} className="h-7 text-[11px]">
                {isSuggesting ? <RefreshCw className="w-3 h-3 mr-1 animate-spin" /> : <Sparkles className="w-3 h-3 mr-1" />}
                Suggest from ledger
              </Button>
              <Button type="button" size="sm" variant="outline" className="h-7 text-[11px]"
                      onClick={() => setProperties([...properties, { name: "", model: "RENTAL", rent_start: null, words: [] }])}>
                <Plus className="w-3 h-3 mr-1" />
                Add
              </Button>
            </div>
          </div>
          <div className="space-y-2 p-2 bg-slate-50 border border-slate-200 rounded-lg">
            {properties.length === 0 ? (
              <span className="text-[11px] text-slate-400 italic">
                No properties. Add one if the company rents out or sells property.
              </span>
            ) : (
              properties.map((p, idx) => (
                <div key={idx} className="grid grid-cols-12 gap-1.5 items-center">
                  <input type="text" placeholder="Property (e.g. 12 High Street)" value={p.name}
                         onChange={(e) => updateProperty(idx, { name: e.target.value })}
                         title={p.reason || undefined}
                         className="col-span-4 text-xs rounded-md border border-slate-300 bg-white px-2 py-1 text-slate-800" />
                  <CustomSelect
                    fullWidth
                    size="sm"
                    className="col-span-2"
                    value={p.model}
                    onChange={(v) => updateProperty(idx, { model: v as "RENTAL" | "TRADING" })}
                    options={[
                      { value: "RENTAL", label: "Rental" },
                      { value: "TRADING", label: "Trading" },
                    ]}
                  />
                  <input type="date" value={p.rent_start || ""} title="Rent start (blank: from the first rent in the ledger)"
                         disabled={p.model !== "RENTAL"}
                         onChange={(e) => updateProperty(idx, { rent_start: e.target.value || null })}
                         className="col-span-2 text-xs rounded-md border border-slate-300 bg-white px-1 py-1 text-slate-800 disabled:opacity-40" />
                  <input type="text" placeholder="Ledger words, comma separated" value={(p.words || []).join(", ")}
                         onChange={(e) => updateProperty(idx, { words: e.target.value.split(",").map((w) => w.trim()).filter(Boolean) })}
                         className="col-span-3 text-xs rounded-md border border-slate-300 bg-white px-2 py-1 text-slate-800" />
                  <button type="button" onClick={() => setProperties(properties.filter((_, i) => i !== idx))}
                          className="col-span-1 text-slate-400 hover:text-rose-600 cursor-pointer justify-self-center">
                    <X className="w-3.5 h-3.5" />
                  </button>
                </div>
              ))
            )}
          </div>
          <p className="text-[11px] text-slate-400 mt-1">
            Rental = fixed asset, rent start from the first rent if left blank. Trading = stock / WIP.
            Ledger words help find each property&apos;s lines when there is more than one.
          </p>
        </div>

                            </>
              ) : (
                <button type="button" onClick={() => setShowProperties(true)} className="text-[11px] font-medium text-teal-800 hover:underline">
                  + The company owns or lets property
                </button>
              )}
            </div>
  );
}
