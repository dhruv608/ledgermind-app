// The client's profile and Engagement Setup, Companies House, last year's balances.
import type { SetupStatus, CompaniesHouseChoice, CompaniesHouseRecord, ClientProfile, ClientProperty } from "@/types/engagement";
import { API_BASE, fetch } from "./client";

export interface LastYear {
  source: string;
  accounts: Record<string, { last_year: number | null; big: boolean }>;
  gone: { name: string; amount: number }[];
}

export const setupApi = {
  /** Last year's balance beside each account (null: not known), where it came from ("" = nothing to compare with),
   *  and last year's balances with no account this year. big = the change is put to the client. */
  async getLastYear(engagementId: string): Promise<LastYear> {
    const res = await fetch(`${API_BASE}/engagements/${engagementId}/last-year`);
    if (!res.ok) throw new Error("Failed to load last year's balances");
    return res.json();
  },

  async getProfile(engagementId: string): Promise<ClientProfile> {
    const res = await fetch(`${API_BASE}/engagements/${engagementId}/profile`);
    if (!res.ok) throw new Error("Failed to load client profile");
    return res.json();
  },

  async updateProfile(engagementId: string, updates: Partial<ClientProfile>): Promise<ClientProfile> {
    const res = await fetch(`${API_BASE}/engagements/${engagementId}/profile`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(updates),
    });
    if (!res.ok) throw new Error("Failed to update client profile");
    return res.json();
  },

  async getPropertySuggestions(engagementId: string): Promise<ClientProperty[]> {
    const res = await fetch(`${API_BASE}/engagements/${engagementId}/profile/property-suggestions`);
    if (!res.ok) throw new Error("Failed to read property suggestions");
    return res.json();
  },

  async getSetupStatus(engagementId: string): Promise<SetupStatus> {
    const res = await fetch(`${API_BASE}/engagements/${engagementId}/setup-status`);
    if (!res.ok) throw new Error("Failed to load the setup status");
    return res.json();
  },

  /** The setup status for the setup as it is on screen (unsaved edits applied, nothing stored). */
  async previewSetupStatus(engagementId: string, changes: Record<string, any>): Promise<SetupStatus> {
    const res = await fetch(`${API_BASE}/engagements/${engagementId}/setup-status`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(changes),
    });
    if (!res.ok) throw new Error("Failed to preview the setup");
    return res.json();
  },

  /** Directors / shareholders over 25% from Companies House; without a number, choices come back when the name is unclear. */
  async lookupCompaniesHouse(
    engagementId: string,
    companyNumber?: string
  ): Promise<CompaniesHouseRecord | { choices: CompaniesHouseChoice[] }> {
    const q = companyNumber ? `?company_number=${encodeURIComponent(companyNumber)}` : "";
    const res = await fetch(`${API_BASE}/engagements/${engagementId}/profile/companies-house${q}`);
    if (!res.ok) {
      const err = await res.json().catch(() => null);
      throw new Error(err?.detail || "Companies House lookup failed");
    }
    return res.json();
  },

  async autoDetectProfile(engagementId: string): Promise<ClientProfile> {
    const res = await fetch(`${API_BASE}/engagements/${engagementId}/profile/auto-detect`, {
      method: "POST",
    });
    if (!res.ok) throw new Error("Failed to auto-detect client profile");
    return res.json();
  },
};
