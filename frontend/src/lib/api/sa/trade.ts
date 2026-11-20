// Self-employed businesses: settings, amounts, allowances and books built from the bank.
import { API_BASE, fetch } from "../client";
import { detail } from "./detail";
import type { SaBankBooks, SaBusinessSettings, SaTradeView } from "./types";

export const saTradeApi = {
  async getSaTrade(jobId: string): Promise<SaTradeView> {
    const res = await fetch(`${API_BASE}/sa/jobs/${jobId}/trade`);
    if (!res.ok) throw new Error(await detail(res, "Could not load the businesses"));
    return res.json();
  },

  async addSaBusiness(jobId: string, name: string): Promise<SaTradeView> {
    const res = await fetch(`${API_BASE}/sa/jobs/${jobId}/trade`, {
      method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ name }),
    });
    if (!res.ok) throw new Error(await detail(res, "Could not add the business"));
    return res.json();
  },

  async editSaBusiness(jobId: string, businessId: number, patch: Partial<SaBusinessSettings>): Promise<SaTradeView> {
    const res = await fetch(`${API_BASE}/sa/jobs/${jobId}/trade/${businessId}`, {
      method: "PATCH", headers: { "Content-Type": "application/json" }, body: JSON.stringify(patch),
    });
    if (!res.ok) throw new Error(await detail(res, "Could not save the business"));
    return res.json();
  },

  async deleteSaBusiness(jobId: string, businessId: number): Promise<SaTradeView> {
    const res = await fetch(`${API_BASE}/sa/jobs/${jobId}/trade/${businessId}`, { method: "DELETE" });
    if (!res.ok) throw new Error(await detail(res, "Could not remove the business"));
    return res.json();
  },

  async addSaTradeItem(jobId: string, businessId: number, body: { heading: string; amount: number; disallowed: number; description: string }): Promise<SaTradeView> {
    const res = await fetch(`${API_BASE}/sa/jobs/${jobId}/trade/${businessId}/items`, {
      method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body),
    });
    if (!res.ok) throw new Error(await detail(res, "Could not add the amount"));
    return res.json();
  },

  async addSaAllowance(jobId: string, businessId: number, body: { kind: string; description: string; amount: number; private_use: number }): Promise<SaTradeView> {
    const res = await fetch(`${API_BASE}/sa/jobs/${jobId}/trade/${businessId}/allowances`, {
      method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body),
    });
    if (!res.ok) throw new Error(await detail(res, "Could not add the allowance"));
    return res.json();
  },

  async deleteSaAllowance(jobId: string, businessId: number, id: number): Promise<SaTradeView> {
    const res = await fetch(`${API_BASE}/sa/jobs/${jobId}/trade/${businessId}/allowances/${id}`, { method: "DELETE" });
    if (!res.ok) throw new Error(await detail(res, "Could not remove the allowance"));
    return res.json();
  },

  async deleteSaTradeItem(jobId: string, businessId: number, itemId: number): Promise<SaTradeView> {
    const res = await fetch(`${API_BASE}/sa/jobs/${jobId}/trade/${businessId}/items/${itemId}`, { method: "DELETE" });
    if (!res.ok) throw new Error(await detail(res, "Could not remove the amount"));
    return res.json();
  },

  async getSaTradeBank(jobId: string, businessId: number): Promise<SaBankBooks> {
    const res = await fetch(`${API_BASE}/sa/jobs/${jobId}/trade/${businessId}/bank`);
    if (!res.ok) throw new Error(await detail(res, "Could not load the bank lines"));
    return res.json();
  },

  async chooseSaTradeBank(jobId: string, businessId: number, keys: string[], heading: string | null): Promise<SaBankBooks> {
    const res = await fetch(`${API_BASE}/sa/jobs/${jobId}/trade/${businessId}/bank`, {
      method: "PATCH", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ keys, heading }),
    });
    if (!res.ok) throw new Error(await detail(res, "Could not save the heading"));
    return res.json();
  },

  async suggestSaTradeBank(jobId: string, businessId: number): Promise<SaBankBooks> {
    const res = await fetch(`${API_BASE}/sa/jobs/${jobId}/trade/${businessId}/bank/suggest`, { method: "POST" });
    if (!res.ok) throw new Error(await detail(res, "Could not get the AI's suggestions"));
    return res.json();
  },

  async putSaPrivateUse(jobId: string, businessId: number, kind: string, business_pct: number | null): Promise<SaBankBooks> {
    const res = await fetch(`${API_BASE}/sa/jobs/${jobId}/trade/${businessId}/private-use`, {
      method: "PUT", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ kind, business_pct }) });
    if (!res.ok) throw new Error(await detail(res, "Could not save the business use"));
    return res.json();
  },

  async postSaTradeBank(jobId: string, businessId: number): Promise<SaTradeView> {
    const res = await fetch(`${API_BASE}/sa/jobs/${jobId}/trade/${businessId}/bank/post`, { method: "POST" });
    if (!res.ok) throw new Error(await detail(res, "Could not put the totals in"));
    return res.json();
  },
};
