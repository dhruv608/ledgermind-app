// Firm settings page: the firm's own defaults for clients without their own (depreciation per asset class, the
// standard accountancy fee accrued).
import { API_BASE, fetch } from "./client";

export type DepreciationMethod = "REDUCING_BALANCE" | "STRAIGHT_LINE" | "NONE";
export type ClassRate = { method: DepreciationMethod; rate?: number | null };
export type FirmDepreciation = {
  classes: Record<string, ClassRate>;
  additions_from: "FULL_YEAR" | "PURCHASE_MONTH" | "NEXT_MONTH";
  asset_classes: string[];
  saved: boolean;
  updated_at: string | null;
};

export type FirmAccountancyFee = { amount: number | null; updated_at: string | null };
export type FirmTaxHoldLimit = { amount: number; saved: boolean; updated_at: string | null };
/** Amortisation of non-goodwill intangibles in the tax computation (goodwill is always added back with a query) */
export type FirmIntangibles = { policy: "ADD_BACK" | "ALLOW"; saved: boolean; updated_at: string | null };

export type FirmCapitalLimits = { general: number; equipment: number; saved: boolean; updated_at: string | null };

export const firmSettingsApi = {
  async getFirmCapitalLimits(): Promise<FirmCapitalLimits> {
    const res = await fetch(`${API_BASE}/firm-settings/capital-limits`);
    if (!res.ok) throw new Error("Could not load the firm settings");
    return res.json();
  },

  /** One of the two limits ("general" or "equipment"); the other is kept. null: back to the default */
  async saveFirmCapitalLimit(kind: "general" | "equipment", amount: number | null): Promise<FirmCapitalLimits> {
    const res = await fetch(`${API_BASE}/firm-settings/capital-limits`, {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ [kind]: amount }),
    });
    if (!res.ok) throw new Error((await res.json().catch(() => ({}))).detail || "Settings not saved");
    return res.json();
  },

  async getFirmDepreciation(): Promise<FirmDepreciation> {
    const res = await fetch(`${API_BASE}/firm-settings/depreciation`);
    if (!res.ok) throw new Error("Could not load the firm settings");
    return res.json();
  },

  async saveFirmDepreciation(settings: Pick<FirmDepreciation, "classes" | "additions_from">): Promise<FirmDepreciation> {
    const res = await fetch(`${API_BASE}/firm-settings/depreciation`, {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(settings),
    });
    if (!res.ok) throw new Error((await res.json().catch(() => ({}))).detail || "Settings not saved");
    return res.json();
  },

  async getFirmChangeQuestionLimit(): Promise<FirmAccountancyFee> {
    const res = await fetch(`${API_BASE}/firm-settings/change-question-limit`);
    if (!res.ok) throw new Error("Could not load the firm settings");
    return res.json();
  },

  async saveFirmChangeQuestionLimit(amount: number | null): Promise<FirmAccountancyFee> {
    const res = await fetch(`${API_BASE}/firm-settings/change-question-limit`, {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ amount }),
    });
    if (!res.ok) throw new Error((await res.json().catch(() => ({}))).detail || "Settings not saved");
    return res.json();
  },

  async getFirmNewClientPrepayments(): Promise<FirmAccountancyFee> {
    const res = await fetch(`${API_BASE}/firm-settings/new-client-prepayments`);
    if (!res.ok) throw new Error("Could not load the firm settings");
    return res.json();
  },

  async saveFirmNewClientPrepayments(amount: number | null): Promise<FirmAccountancyFee> {
    const res = await fetch(`${API_BASE}/firm-settings/new-client-prepayments`, {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ amount }),
    });
    if (!res.ok) throw new Error((await res.json().catch(() => ({}))).detail || "Settings not saved");
    return res.json();
  },

  async getFirmAccountancyFee(): Promise<FirmAccountancyFee> {
    const res = await fetch(`${API_BASE}/firm-settings/accountancy-fee`);
    if (!res.ok) throw new Error("Could not load the firm settings");
    return res.json();
  },

  async saveFirmAccountancyFee(amount: number | null): Promise<FirmAccountancyFee> {
    const res = await fetch(`${API_BASE}/firm-settings/accountancy-fee`, {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ amount }),
    });
    if (!res.ok) throw new Error((await res.json().catch(() => ({}))).detail || "Settings not saved");
    return res.json();
  },

  async getFirmIntangibles(): Promise<FirmIntangibles> {
    const res = await fetch(`${API_BASE}/firm-settings/intangibles`);
    if (!res.ok) throw new Error("Could not load the firm settings");
    return res.json();
  },

  async saveFirmIntangibles(policy: FirmIntangibles["policy"]): Promise<FirmIntangibles> {
    const res = await fetch(`${API_BASE}/firm-settings/intangibles`, {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ policy }),
    });
    if (!res.ok) throw new Error((await res.json().catch(() => ({}))).detail || "Settings not saved");
    return res.json();
  },

  async getFirmTaxHoldLimit(): Promise<FirmTaxHoldLimit> {
    const res = await fetch(`${API_BASE}/firm-settings/tax-hold-limit`);
    if (!res.ok) throw new Error("Could not load the firm settings");
    return res.json();
  },

  async saveFirmTaxHoldLimit(amount: number | null): Promise<FirmTaxHoldLimit> {
    const res = await fetch(`${API_BASE}/firm-settings/tax-hold-limit`, {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ amount }),
    });
    if (!res.ok) throw new Error((await res.json().catch(() => ({}))).detail || "Settings not saved");
    return res.json();
  },
};
