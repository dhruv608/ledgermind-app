// Companies House lookup for the setup: the register record, the company choices offered, and each person's role.

import React, { useEffect, useState } from "react";
import { ClientProfile, CompaniesHouseChoice, CompaniesHouseRecord } from "@/types/engagement";
import { api } from "@/lib/api";
import { toast } from "@/lib/notify";
import { plural } from "@/lib/formatters";

export function useCompaniesHouse(
  engagementId: string,
  profile: Partial<ClientProfile>,
  setProfile: React.Dispatch<React.SetStateAction<Partial<ClientProfile>>>,
) {
  // Companies House: directors and shareholders over 25% during the year (the accountant checks, then saves)
  const [isLookingUp, setIsLookingUp] = useState(false);
  const [chChoices, setChChoices] = useState<CompaniesHouseChoice[] | null>(null);
  const [chFromUpload, setChFromUpload] = useState(false);
  const register = (profile.companies_house as CompaniesHouseRecord | undefined)?.company_number
    ? (profile.companies_house as CompaniesHouseRecord)
    : null;
  // No exact Companies House match at upload: the closest companies are offered at once ("Is this your company?")
  const uploadChoices = profile.detection_signals?.ch_choices;
  // Checked on the first render and whenever the register record or the upload's choices change
  const [offeredFor, setOfferedFor] = useState<{ register: CompaniesHouseRecord | null; uploadChoices: typeof uploadChoices } | null>(null);
  if (!offeredFor || offeredFor.register !== register || offeredFor.uploadChoices !== uploadChoices) {
    setOfferedFor({ register, uploadChoices });
    if (!register && uploadChoices?.length && chChoices === null) {
      setChChoices(uploadChoices);
      setChFromUpload(true);
    }
  }
  const roleOf = (name: string) => {
    const p = register?.people.find((x) => x.name.toLowerCase() === name.toLowerCase());
    if (!p) return undefined;
    return p.roles.join(" · ") + (p.also_listed_as?.length ? ` · also listed as ${p.also_listed_as.join(", ")}` : "");
  };

  const handleCompaniesHouse = async (companyNumber?: string) => {
    setIsLookingUp(true);
    try {
      const res = await api.lookupCompaniesHouse(engagementId, companyNumber || register?.company_number);
      if ("choices" in res) {
        setChChoices(res.choices);
        if (!res.choices.length) toast.error("No company with this name on Companies House");
        return;
      }
      setChChoices(null);
      // The same person under a second name (merged by the register lookup) comes off the list
      const aliases = new Set(res.people.flatMap((p) => p.also_listed_as || []).map((n) => n.toLowerCase()));
      const current = (profile.directors || []).filter((d) => !aliases.has(d.toLowerCase()));
      const removed = (profile.directors || []).length - current.length;
      const known = new Set(current.map((d) => d.toLowerCase()));
      const added = res.people.map((p) => p.name).filter((n) => !known.has(n.toLowerCase()));
      setProfile((prev) => ({ ...prev, companies_house: res, directors: [...current, ...added] }));
      toast.success(`${res.company_name}: ${plural(res.people.length, "director or shareholder", "directors and shareholders")} found`, {
        description: [added.length ? `${added.length} added to the list.` : "All were already in the list.",
                      removed ? `${removed} listed twice under another name, merged.` : "", "Check them, then save."].filter(Boolean).join(" "),
      });
    } catch (err: any) {
      toast.error("Companies House", { description: err.message });
    } finally {
      setIsLookingUp(false);
    }
  };

  return { isLookingUp, chChoices, setChChoices, chFromUpload, setChFromUpload, register, roleOf, handleCompaniesHouse };
}
