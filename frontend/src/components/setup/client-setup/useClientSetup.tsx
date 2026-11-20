// The client setup's state: the profile being edited, what is saved, the server's status and suggestions,
// saving or discarding each part, the accordion, properties and directors.

import React, { useState, useEffect } from "react";
import { UK_INDUSTRIES, getIndustryBadge } from "@/lib/badges";
import { ClientProfile, ClientProperty, SetupStatus } from "@/types/engagement";
import { SectionState, SetSetup, SetupData, Suggestion } from "@/components/setup/SetupFields";
import { api } from "@/lib/api";
import { toast } from "@/lib/notify";
import { plural } from "@/lib/formatters";
import { SECTIONS, SUGGESTION_SECTION, SectionKey, pounds, same } from "./sections";
import { useCompaniesHouse } from "./useCompaniesHouse";

export interface ClientSetupPanelProps {
  engagementId: string;
  initialProfile?: ClientProfile | null;
  onProfileUpdated: (profile: ClientProfile) => void;
  /** Tells the page when there are unsaved changes (so it can warn before leaving). */
  onDirtyChange?: (dirty: boolean) => void;
}

export function useClientSetup({
  engagementId,
  initialProfile,
  onProfileUpdated,
  onDirtyChange,
}: ClientSetupPanelProps) {
  const [profile, setProfile] = useState<Partial<ClientProfile>>({
    industry_code: "UNIV",
    is_vat_registered: false,
    vat_scheme: "STANDARD",
    has_payroll: false,
    cis_status: "NONE",
    directors: [],
    accounting_framework: "FRS102_1A",
    materiality_threshold: 1000.0,
    capitalisation_threshold: 500.0,
    auto_detected: false,
  });

  // The setup as last saved, to tell whether there are unsaved changes
  const [savedSnapshot, setSavedSnapshot] = useState("");
  const remember = (p: Partial<ClientProfile>) => setSavedSnapshot(JSON.stringify(p));
  const saved: Partial<ClientProfile> = savedSnapshot ? JSON.parse(savedSnapshot) : {};
  // Suggestions the accountant chose to use (they count as answers once their part is saved, even if unchanged)
  const [accepted, setAccepted] = useState<Set<string>>(new Set());
  // Answers the accountant picked in the box themselves: they count as answered once saved, even when the pick is what
  // was already there (not only after pressing "Use" on the suggestion)
  const [picked, setPicked] = useState<Set<string>>(new Set());
  const pick = (field: string, value: any) => {
    setProfile((prev) => ({ ...prev, [field]: value }));
    setPicked((prev) => new Set(prev).add(field));
  };
  const sectionOf = (key: SectionKey) => SECTIONS.find((x) => x.key === key)!;
  const sectionDirty = (key: SectionKey) => {
    if (!savedSnapshot) return false;
    const sec = sectionOf(key);
    const cur = (profile.setup || {}) as SetupData, old = (saved.setup || {}) as SetupData;
    return sec.fields.some((f) => !same(profile[f], saved[f])) || sec.parts.some((p) => !same(cur[p], old[p]))
      || [...accepted, ...picked].some((f) => SUGGESTION_SECTION[f] === key);
  };
  const dirtySections = SECTIONS.filter((x) => sectionDirty(x.key)).map((x) => x.key);
  const isDirty = dirtySections.length > 0;
  // What saving these parts sends: their fields, and the saved setup record with their parts replaced
  const payloadFor = (keys: SectionKey[]): Partial<ClientProfile> => {
    const out: Record<string, any> = {};
    const setupOut: SetupData = { ...((saved.setup || {}) as SetupData) };
    for (const key of keys) {
      const sec = sectionOf(key);
      sec.fields.forEach((f) => { if (profile[f] !== undefined) out[f] = profile[f]; });
      sec.parts.forEach((p) => { const v = ((profile.setup || {}) as SetupData)[p]; if (v === undefined) delete setupOut[p]; else setupOut[p] = v; });
    }
    const carried = setupOut._carried as { fields?: string[]; parts?: string[] } | undefined;
    if (carried) {
      const fields = (carried.fields || []).filter((f) => !keys.some((k) => (sectionOf(k).fields as string[]).includes(f)));
      const parts = (carried.parts || []).filter((p) => !keys.some((k) => sectionOf(k).parts.includes(p)));
      if (fields.length || parts.length) setupOut._carried = { ...carried, fields, parts };
      else delete setupOut._carried;
    }
    out.setup = setupOut;
    return out as Partial<ClientProfile>;
  };
  useEffect(() => {
    onDirtyChange?.(isDirty);
  }, [isDirty]); // eslint-disable-line react-hooks/exhaustive-deps

  // Which of the seven steps is shown, and the server's view of the saved setup (gaps, warnings, checks, suggestions)
  const [showProperties, setShowProperties] = useState(false);
  const [status, setStatus] = useState<SetupStatus | null>(null);
  const [statusLoading, setStatusLoading] = useState(false);
  const loadStatus = async () => {
    setStatusLoading(true);
    try {
      setStatus(await api.getSetupStatus(engagementId));
    } catch {
      // the panel shows the last status it had
    } finally {
      setStatusLoading(false);
    }
  };
  // The same as loadStatus(), written out: busy from the first render for each client, the status set when it arrives
  const [statusFor, setStatusFor] = useState<string | null>(null);
  if (engagementId && engagementId !== statusFor) {
    setStatusFor(engagementId);
    setStatusLoading(true);
  }
  useEffect(() => {
    if (!engagementId) return;
    api.getSetupStatus(engagementId)
      .then(setStatus)
      .catch(() => undefined)   // the panel shows the last status it had
      .finally(() => setStatusLoading(false));
  }, [engagementId]);

  // The panel follows the screen as you type: the server works out the checks for the unsaved setup (nothing stored)
  useEffect(() => {
    if (!savedSnapshot || !isDirty) return;
    const timer = setTimeout(async () => {
      setStatusLoading(true);
      try {
        setStatus(await api.previewSetupStatus(engagementId, payloadFor(dirtySections)));
      } catch {
        // keep the last status
      } finally {
        setStatusLoading(false);
      }
    }, 600);
    return () => clearTimeout(timer);
  }, [profile, accepted, picked]); // eslint-disable-line react-hooks/exhaustive-deps
  const catalogue = status?.catalogue;

  const setup = (profile.setup || {}) as SetupData;
  const setS: SetSetup = (part, key, value) =>
    setProfile((prev) => {
      const current = (prev.setup || {}) as SetupData;
      return { ...prev, setup: { ...current, [part]: { ...(current[part] || {}), [key]: value } } };
    });

  // An open answer the data suggests, with a button to use it (it still has to be saved to count)
  const SUGGESTION_LABELS: Record<string, (v: any) => string> = {
    industry_code: (v) => UK_INDUSTRIES.find((i) => i.code === v)?.name || v,
    is_vat_registered: (v) => (v ? "VAT registered" : "Not VAT registered"),
    has_payroll: (v) => (v ? "Runs a payroll" : "No payroll"),
    cis_status: (v) => ({ NONE: "Not in CIS", CONTRACTOR: "CIS contractor", SUBCONTRACTOR: "CIS subcontractor", BOTH: "CIS both" } as Record<string, string>)[v] || v,
    accounting_framework: (v) => ({ FRS105: "FRS 105", FRS102_1A: "FRS 102 1A", FULL_FRS102: "FRS 102 full", IFRS: "IFRS" } as Record<string, string>)[v] || v,
    prior_year_tb_gl: (v) => (v ? "Last year's data available" : "No last year's data"),
  };
  const suggestionFor = (field: string) => {
    const sug = status?.suggestions?.[field];
    if (!sug || !SUGGESTION_LABELS[field] || (picked.has(field) && !accepted.has(field))) return null;
    const use = () => {
      if (field === "prior_year_tb_gl") setS("client", "prior_year_tb_gl", sug.value);
      else setProfile((prev) => ({ ...prev, [field]: sug.value }));
      setAccepted((prev) => new Set(prev).add(field));
    };
    return <Suggestion text={SUGGESTION_LABELS[field](sug.value)} reason={sug.reason} onUse={use} used={accepted.has(field)} />;
  };

  const [isDetecting, setIsDetecting] = useState(false);
  const [directorInput, setDirectorInput] = useState("");
  const [isSuggesting, setIsSuggesting] = useState(false);

  // Properties: one row per property, classified as rental or trading
  const properties = profile.properties || [];
  const setProperties = (next: ClientProperty[]) => setProfile((prev) => ({ ...prev, properties: next }));
  const updateProperty = (index: number, changes: Partial<ClientProperty>) =>
    setProperties(properties.map((p, i) => (i === index ? { ...p, ...changes } : p)));

  const handleSuggestProperties = async () => {
    setIsSuggesting(true);
    try {
      const suggested = await api.getPropertySuggestions(engagementId);
      const known = new Set(properties.map((p) => p.name.toLowerCase()));
      const added = suggested.filter((s) => !known.has(s.name.toLowerCase()));
      setProperties([...properties, ...added]);
      toast.success(added.length ? `${added.length} property(ies) suggested` : "No new properties found in the ledger", {
        description: added.length ? "Check each one and its rental / trading model, then save." : undefined,
      });
    } catch (err: any) {
      toast.error("Could not read the ledger", { description: err.message });
    } finally {
      setIsSuggesting(false);
    }
  };

  // The profile the page passed in (taken at once, and again whenever it or the client changes), else read here
  const [profileFrom, setProfileFrom] = useState<{ initialProfile?: ClientProfile | null; engagementId: string } | null>(null);
  if (!profileFrom || profileFrom.initialProfile !== initialProfile || profileFrom.engagementId !== engagementId) {
    setProfileFrom({ initialProfile, engagementId });
    if (initialProfile) {
      const loaded = {
        ...initialProfile,
        directors: Array.isArray(initialProfile.directors) ? initialProfile.directors : [],
      };
      setProfile(loaded);
      remember(loaded);
    }
  }
  useEffect(() => {
    if (initialProfile || !engagementId) return;
    api.getProfile(engagementId)
      .then((data) => {
        setProfile(data);
        remember(data);
      })
      .catch((err) => console.warn("Could not load profile", err));
  }, [initialProfile, engagementId]);

  const handleAutoDetect = async () => {
    setIsDetecting(true);
    try {
      const detected = await api.autoDetectProfile(engagementId);
      setProfile(detected);
      remember(detected);
      onProfileUpdated(detected);
      loadStatus();
      const ind = UK_INDUSTRIES.find((i) => i.code === detected.industry_code)?.name || detected.industry_code;
      toast.success("Suggestions filled in", {
        description: `Suggested industry: ${ind}. Check the setup and save it to confirm.`,
      });
    } catch (err: any) {
      toast.error("No suggestions", {
        description: err.message || "The accounts could not be read.",
      });
    } finally {
      setIsDetecting(false);
    }
  };

  // Save one part (or several), keeping the other parts' unsaved edits on screen
  const [savingKeys, setSavingKeys] = useState<SectionKey[]>([]);
  const handleSave = async (keys: SectionKey[]) => {
    if (!keys.length) return;
    setSavingKeys(keys);
    try {
      const updated = await api.updateProfile(engagementId, payloadFor(keys));
      setProfile((prev) => {
        const next: Record<string, any> = { ...prev, confirmed_fields: updated.confirmed_fields };
        const setupNext: SetupData = { ...((prev.setup || {}) as SetupData) };
        for (const key of keys) {
          const sec = sectionOf(key);
          sec.fields.forEach((f) => { next[f] = updated[f]; });
          sec.parts.forEach((p) => { setupNext[p] = ((updated.setup || {}) as SetupData)[p]; });
        }
        const carriedNow = ((updated.setup || {}) as SetupData)._carried;
        if (carriedNow) setupNext._carried = carriedNow;
        else delete setupNext._carried;
        next.setup = setupNext;
        return next as Partial<ClientProfile>;
      });
      remember(updated);
      setAccepted((prev) => new Set([...prev].filter((f) => !keys.includes(SUGGESTION_SECTION[f]))));
      setPicked((prev) => new Set([...prev].filter((f) => !keys.includes(SUGGESTION_SECTION[f]))));
      onProfileUpdated(updated);
      if (keys.length === 1) {
        const i = SECTIONS.findIndex((x) => x.key === keys[0]);
        const next = SECTIONS[i + 1];
        setOpenKeys(next ? new Set([next.key]) : new Set());
        if (next) setTimeout(() => document.getElementById(`setup-${next.key}`)?.scrollIntoView({ behavior: "smooth", block: "start" }), 80);
      }
      toast.success(keys.length === 1 ? `${sectionOf(keys[0]).title} saved` : "Setup saved", {
        description: "The next review uses these settings.",
      });
      loadStatus();
    } catch (err: any) {
      toast.error("Not saved", {
        description: err.message || "Please check your inputs.",
      });
    } finally {
      setSavingKeys([]);
    }
  };
  const handleDiscard = (key: SectionKey) => {
    const sec = sectionOf(key);
    setProfile((prev) => {
      const next: Record<string, any> = { ...prev };
      const setupNext: SetupData = { ...((prev.setup || {}) as SetupData) };
      sec.fields.forEach((f) => { next[f] = saved[f]; });
      sec.parts.forEach((p) => { const v = ((saved.setup || {}) as SetupData)[p]; if (v === undefined) delete setupNext[p]; else setupNext[p] = v; });
      next.setup = setupNext;
      return next as Partial<ClientProfile>;
    });
    setAccepted((prev) => new Set([...prev].filter((f) => SUGGESTION_SECTION[f] !== key)));
    setPicked((prev) => new Set([...prev].filter((f) => SUGGESTION_SECTION[f] !== key)));
  };

  // Each part's state from what is saved: answered, still needed for the review, optional, or edited and not saved
  const confirmed = new Set(saved.confirmed_fields || []);
  const savedSetup = (saved.setup || {}) as SetupData;
  const answered: Record<SectionKey, boolean | null> = {
    engagement: confirmed.has("accounting_framework"),
    industry: confirmed.has("industry_code"),
    tax: confirmed.has("is_vat_registered") && confirmed.has("has_payroll"),
    people: (saved.directors || []).length > 0,
    policies: confirmed.has("capitalisation_threshold") || Object.keys(savedSetup.policies || {}).length > 0 ? true : null,
    materiality: Boolean(savedSetup.materiality?.overall) || confirmed.has("materiality_threshold"),
    last_year: Object.keys(savedSetup.prior_year || {}).length > 0 ? true : null,
  };
  // Carried over from last year and not yet checked this year
  const carriedInfo = savedSetup._carried as { from?: string; fields?: string[]; parts?: string[] } | undefined;
  const isCarried = (key: SectionKey) => {
    const sec = sectionOf(key);
    return Boolean(carriedInfo) && ((carriedInfo!.fields || []).some((f) => (sec.fields as string[]).includes(f))
      || (carriedInfo!.parts || []).some((p) => sec.parts.includes(p)));
  };
  const stateOf = (key: SectionKey): SectionState =>
    sectionDirty(key) ? "unsaved" : isCarried(key) ? "carried"
      : answered[key] === true ? "saved" : answered[key] === null ? "optional" : "todo";
  const FRAMEWORKS: Record<string, string> = { FRS105: "FRS 105", FRS102_1A: "FRS 102 1A", FULL_FRS102: "FRS 102 full", IFRS: "IFRS" };
  const summaryOf = (key: SectionKey): string => {
    const s = (profile.setup || {}) as SetupData;
    const names = profile.directors || [];
    switch (key) {
      case "engagement":
        return [FRAMEWORKS[profile.accounting_framework || ""], status?.record?.client?.size && `Size: ${status.record.client.size}`].filter(Boolean).join(" · ");
      case "industry":
        return [UK_INDUSTRIES.find((i) => i.code === profile.industry_code)?.name, (s.industry?.models || []).join(", ")].filter(Boolean).join(" · ");
      case "tax":
        return [profile.is_vat_registered ? "VAT registered" : "Not VAT registered", profile.has_payroll ? "Payroll" : "No payroll",
                profile.cis_status && profile.cis_status !== "NONE" ? `CIS ${profile.cis_status.toLowerCase()}` : null].filter(Boolean).join(" · ");
      case "people":
        return names.length ? `${plural(names.length, "director or shareholder", "directors and shareholders")}: ${names.slice(0, 3).join(", ")}${names.length > 3 ? "…" : ""}` : "No directors yet";
      case "policies":
        return `Capitalisation £${(profile.capitalisation_threshold || 500).toLocaleString("en-GB")}`
          + (Object.keys(s.policies?.depreciation || {}).length ? " · depreciation rates entered" : "");
      case "materiality":
        return s.materiality?.overall
          ? `Overall £${pounds(s.materiality.overall)} · trivial £${pounds(s.materiality.trivial || 0)}`
          : "Not set";
      case "last_year":
        return (s.prior_year?.issues || []).length ? (s.prior_year?.issues || []).join(", ") : "No issues ticked";
    }
  };

  // Accordion: one part open at a time (opening one closes the other), or all of them with Expand all
  const [openKeys, setOpenKeys] = useState<Set<SectionKey>>(new Set());
  const [openedFirst, setOpenedFirst] = useState(false);
  if (!openedFirst && savedSnapshot) {
    // The first part still needing an answer; when everything is saved, all closed (an overview)
    const first = SECTIONS.find((x) => stateOf(x.key) === "todo" || stateOf(x.key) === "carried");
    setOpenKeys(new Set(first ? [first.key] : []));
    setOpenedFirst(true);
  }
  const toggle = (key: SectionKey) => {
    const opening = !openKeys.has(key);
    setOpenKeys((prev) => (prev.has(key) ? new Set([...prev].filter((k) => k !== key)) : new Set([key])));
    if (opening) setTimeout(() => document.getElementById(`setup-${key}`)?.scrollIntoView({ behavior: "smooth", block: "start" }), 60);
  };
  const sectionProps = (key: SectionKey, number: number) => {
    const sec = sectionOf(key);
    return {
      id: `setup-${key}`, number, title: sec.title, lead: sec.lead, open: openKeys.has(key), onToggle: () => toggle(key),
      state: stateOf(key), summary: summaryOf(key), onSave: () => handleSave([key]), onDiscard: () => handleDiscard(key),
      saving: savingKeys.includes(key),
    };
  };
  const savedCount = SECTIONS.filter((x) => stateOf(x.key) === "saved").length;

  const handleAddDirector = (e: React.KeyboardEvent | React.MouseEvent) => {
    if (e.type === "keydown" && (e as React.KeyboardEvent).key !== "Enter") return;
    e.preventDefault();
    const name = directorInput.trim();
    if (!name) return;
    const current = profile.directors || [];
    if (!current.includes(name)) {
      setProfile((prev) => ({ ...prev, directors: [...(prev.directors || []), name] }));
    }
    setDirectorInput("");
  };

  const { isLookingUp, chChoices, setChChoices, chFromUpload, setChFromUpload, register, roleOf, handleCompaniesHouse }
    = useCompaniesHouse(engagementId, profile, setProfile);

  const handleRemoveDirector = (index: number) => {
    setProfile((prev) => ({
      ...prev,
      directors: (prev.directors || []).filter((_, i) => i !== index),
    }));
  };

  const currentBadge = getIndustryBadge(profile.industry_code);

  return {
    profile, setProfile, savedSnapshot, isDirty, dirtySections, pick, status, statusLoading, catalogue, setup, setS,
    suggestionFor, showProperties, setShowProperties, isDetecting, directorInput, setDirectorInput, isSuggesting,
    properties, setProperties, updateProperty, handleSuggestProperties, handleAutoDetect, savingKeys, handleSave,
    carriedInfo, setOpenKeys, sectionProps, savedCount, handleAddDirector, isLookingUp, chChoices, setChChoices,
    chFromUpload, setChFromUpload, register, roleOf, handleCompaniesHouse, handleRemoveDirector, currentBadge,
  };
}

export type ClientSetupState = ReturnType<typeof useClientSetup>;
