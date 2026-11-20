// Account mapping: the firm chart, each account's code, the firm's account rules.
import type { FirmRule, FirmRuleInput, FirmRuleMatch } from "@/types/engagement";
import { API_BASE, fetch } from "./client";
import type { ConfirmResult } from "./upload";

/** A code the firm's accountants confirmed for an account name, and how many of today's clients use it. */
export interface MemoryEntry {
  id: number;
  name: string;
  std_code: number;
  std_name: string;
  confirmed_by: string;
  confirmed_at: string | null;
  clients: number;
}

export const mappingApi = {
  async getFirmMemory(): Promise<MemoryEntry[]> {
    const res = await fetch(`${API_BASE}/mapping/memory`);
    if (!res.ok) throw new Error("Could not load the firm memory");
    return res.json();
  },

  async removeFirmMemory(ids: number[]): Promise<number> {
    const res = await fetch(`${API_BASE}/mapping/memory/remove`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ ids }),
    });
    if (!res.ok) throw new Error("Could not remove them");
    return (await res.json()).removed;
  },

  // Only what the server really confirmed: accounts in suspense (9999) need a real code first, and accounts the app
  // flagged "Check" are confirmed one at a time, never in bulk. One account that could not be confirmed is an error.
  async confirmMappings(engagementId: string, rawAccountNames: string[]): Promise<ConfirmResult> {
    const res = await fetch(`${API_BASE}/mapping/confirm`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ engagement_id: engagementId, raw_account_names: rawAccountNames }),
    });
    if (!res.ok) throw new Error("Failed to confirm mappings");
    const data = await res.json();
    const result: ConfirmResult = {
      confirmed: data.confirmed || 0,
      names: data.confirmed_names || [],
      inSuspense: data.skipped_suspense || [],
      toCheck: data.skipped_to_check || [],
    };
    if (rawAccountNames.length === 1 && result.confirmed === 0) {
      throw new Error(result.inSuspense.length ? "It is in suspense (9999): choose a real code first." : "Not confirmed.");
    }
    return result;
  },

  // ---- Account rules page: the firm's own account-name rules ----
  async getFirmRules(): Promise<FirmRule[]> {
    const res = await fetch(`${API_BASE}/firm-rules`);
    if (!res.ok) throw new Error("Could not load the account rules");
    return res.json();
  },

  async saveFirmRule(rule: FirmRuleInput, id?: number): Promise<FirmRule> {
    const res = await fetch(`${API_BASE}/firm-rules${id ? `/${id}` : ""}`, {
      method: id ? "PUT" : "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(rule),
    });
    if (!res.ok) throw new Error((await res.json().catch(() => ({}))).detail || "Rule not saved");
    return res.json();
  },

  async deleteFirmRule(id: number): Promise<void> {
    const res = await fetch(`${API_BASE}/firm-rules/${id}`, { method: "DELETE" });
    if (!res.ok) throw new Error("Rule not deleted");
  },

  async getFirmRuleMatches(id: number): Promise<FirmRuleMatch[]> {
    const res = await fetch(`${API_BASE}/firm-rules/${id}/matches`);
    if (!res.ok) throw new Error("Could not load the matching accounts");
    return res.json();
  },

  async applyFirmRule(id: number): Promise<{ changed: number; clients: number }> {
    const res = await fetch(`${API_BASE}/firm-rules/${id}/apply`, { method: "POST" });
    if (!res.ok) throw new Error((await res.json().catch(() => ({}))).detail || "Rule not applied");
    return res.json();
  },

  async getMasterCOA(): Promise<{ std_code: number; std_name: string; category?: string; is_extended?: boolean }[]> {
    const res = await fetch(`${API_BASE}/mapping/master-coa`);
    if (!res.ok) return [];
    return res.json();
  },

  /** The AI's top 3 codes for one account, asked on demand from the review screen. */
  async getMappingOptions(
    engagementId: string,
    rawAccountName: string
  ): Promise<{ std_code: number; std_name: string; confidence: number; reason: string }[]> {
    const res = await fetch(`${API_BASE}/mapping/options`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ engagement_id: engagementId, raw_account_names: [rawAccountName] }),
    });
    if (!res.ok) {
      const err = await res.json().catch(() => null);
      throw new Error(err?.detail || "AI options not available");
    }
    return res.json();
  },

  async updateSingleMapping(rawAccountName: string, stdCode: number, engagementId?: string): Promise<void> {
    const res = await fetch(`${API_BASE}/mapping/update`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ raw_account_name: rawAccountName, std_code: stdCode, engagement_id: engagementId }),
    });
    if (!res.ok) throw new Error("Failed to update mapping");
  },

  async resetToAISuggestion(rawAccountName: string, engagementId?: string): Promise<{ std_code: number; std_name: string; confidence_score: number }> {
    const res = await fetch(`${API_BASE}/mapping/reset-ai-suggestion`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ raw_account_name: rawAccountName, engagement_id: engagementId }),
    });
    if (!res.ok) throw new Error("Failed to reset AI suggestion");
    return res.json();
  },
};
