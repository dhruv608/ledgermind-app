// Setup step 4: directors and shareholders, typed in or fetched from Companies House, and their details.

import { RefreshCw, Plus, X, Landmark } from "lucide-react";
import { Button } from "@/components/ui/button";
import { PeopleDetails } from "@/components/setup/SetupFields";
import type { ClientSetupState } from "./useClientSetup";

export function PeopleStep({ s }: { s: ClientSetupState }) {
  const {
    handleCompaniesHouse, isLookingUp, register, chChoices, chFromUpload, setChChoices, setChFromUpload,
    directorInput, setDirectorInput, handleAddDirector, profile, handleRemoveDirector, roleOf, setup, setS,
  } = s;
  return (
            <div className="space-y-6">
        {/* Section 4: Directors */}
        <div>
          <div className="mb-1 flex flex-wrap items-center justify-between gap-2">
            <label className="block text-[11px] font-bold text-slate-700">
              Directors and shareholders (related parties, director loan account and s455 checks)
            </label>
            <Button
              type="button"
              size="sm"
              variant="outline"
              onClick={() => handleCompaniesHouse()}
              disabled={isLookingUp}
              className="h-7 text-[11px]"
            >
              {isLookingUp ? <RefreshCw className="mr-1 h-3 w-3 animate-spin" /> : <Landmark className="mr-1 h-3 w-3" />}
              {register ? "Check Companies House again" : "Get from Companies House"}
            </Button>
          </div>
          {chChoices && chChoices.length > 0 && (
            <div className="mb-2 rounded-lg border border-teal-200 bg-teal-50/60 p-2.5">
              <p className="mb-1.5 text-[11px] font-medium text-teal-900">
                {chFromUpload ? "Is this your company? (no exact match for the client's name on Companies House)" : "Which company is this client?"}
              </p>
              <ul className="space-y-1">
                {chChoices.map((c) => (
                  <li key={c.company_number}>
                    <button
                      type="button"
                      onClick={() => handleCompaniesHouse(c.company_number)}
                      className="flex w-full items-start justify-between gap-3 rounded-md border border-slate-200 bg-white px-2.5 py-1.5 text-left text-[11px] hover:border-teal-300"
                    >
                      <span>
                        <span className="font-semibold text-slate-800">{c.company_name}</span>
                        <span className="ml-1.5 font-mono text-slate-400">{c.company_number}</span>
                        {c.address && <span className="block text-slate-500">{c.address}</span>}
                      </span>
                      <span className={c.status === "active" ? "text-emerald-700" : "text-slate-400"}>{c.status}</span>
                    </button>
                  </li>
                ))}
              </ul>
              <button type="button" onClick={() => { setChChoices([]); setChFromUpload(false); }} className="mt-1.5 text-[11px] text-slate-500 hover:underline">
                None of these
              </button>
            </div>
          )}
          <div className="flex gap-2 mb-2">
            <input
              type="text"
              placeholder="Director's full name, then Enter"
              value={directorInput}
              onChange={(e) => setDirectorInput(e.target.value)}
              onKeyDown={handleAddDirector}
              className="flex-1 text-xs rounded-lg border border-slate-300 bg-white px-3 py-1.5 text-slate-800 focus:outline-none focus:border-teal-600"
            />
            <Button
              type="button"
              size="sm"
              variant="outline"
              onClick={handleAddDirector}
              className="h-8 text-xs shrink-0"
            >
              <Plus className="w-3.5 h-3.5 mr-1" />
              Add
            </Button>
          </div>

          {/* Director Tags */}
          <div className="flex flex-wrap gap-1.5 min-h-[30px] p-2 bg-slate-50 border border-slate-200 rounded-lg">
            {(profile.directors || []).length === 0 ? (
              <span className="text-[11px] text-slate-400 italic">No directors added.</span>
            ) : (
              (profile.directors || []).map((dir, idx) => (
                <span
                  key={idx}
                  className="inline-flex items-center px-2 py-0.5 rounded-full text-xs font-medium bg-white border border-slate-200 text-slate-700 shadow-2xs"
                >
                  <span className="mr-1.5">
                    {dir}
                    {roleOf(dir) && <span className="ml-1 text-[11px] font-normal text-slate-400">{roleOf(dir)}</span>}
                  </span>
                  <button
                    type="button"
                    onClick={() => handleRemoveDirector(idx)}
                    className="text-slate-400 hover:text-rose-600 transition cursor-pointer"
                  >
                    <X className="w-3 h-3" />
                  </button>
                </span>
              ))
            )}
          </div>

          {register && (
            <p className="mt-1 text-[11px] text-slate-500">
              From Companies House: {register.company_name} ({register.company_number}), directors and shareholders over 25%
              during the year{register.fetched_at ? `, checked ${register.fetched_at}` : ""}. Remove anyone who is not
              related; add family members or their companies by name.
            </p>
          )}
        </div>

              <PeopleDetails setup={setup} set={setS} directors={profile.directors || []} roleOf={roleOf} />
            </div>
  );
}
