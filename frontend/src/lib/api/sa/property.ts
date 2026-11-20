// Rental properties: facts, amounts and rent found in the bank.
import { API_BASE, fetch } from "../client";
import { detail } from "./detail";
import type { SaPropertyFacts, SaPropertyRow, SaPropertyView } from "./types";

export const saPropertyApi = {
  async getSaProperty(jobId: string, overseas = false): Promise<SaPropertyView> {
    const res = await fetch(`${API_BASE}/sa/jobs/${jobId}/property${overseas ? "?overseas=true" : ""}`);
    if (!res.ok) throw new Error(await detail(res, "Could not load the properties"));
    return res.json();
  },

  async addSaProperty(jobId: string, body: Partial<SaPropertyFacts> & { name: string; share: number }): Promise<SaPropertyView> {
    const res = await fetch(`${API_BASE}/sa/jobs/${jobId}/property`, {
      method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body),
    });
    if (!res.ok) throw new Error(await detail(res, "Could not add the property"));
    return res.json();
  },

  async editSaProperty(jobId: string, propertyId: number, patch: Partial<Pick<SaPropertyRow, "name" | "share" | "use_allowance" | "losses_bf" | "finance_bf" | "foreign_tax" | "note">> & Partial<SaPropertyFacts>): Promise<SaPropertyView> {
    const res = await fetch(`${API_BASE}/sa/jobs/${jobId}/property/${propertyId}`, {
      method: "PATCH", headers: { "Content-Type": "application/json" }, body: JSON.stringify(patch),
    });
    if (!res.ok) throw new Error(await detail(res, "Could not save the property"));
    return res.json();
  },

  async deleteSaProperty(jobId: string, propertyId: number): Promise<SaPropertyView> {
    const res = await fetch(`${API_BASE}/sa/jobs/${jobId}/property/${propertyId}`, { method: "DELETE" });
    if (!res.ok) throw new Error(await detail(res, "Could not remove the property"));
    return res.json();
  },

  async addSaPropertyItems(jobId: string, propertyId: number, body: { heading: string; amount: number; description: string; on?: string; months?: number }): Promise<SaPropertyView> {
    const res = await fetch(`${API_BASE}/sa/jobs/${jobId}/property/${propertyId}/items`, {
      method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body),
    });
    if (!res.ok) throw new Error(await detail(res, "Could not add the amount"));
    return res.json();
  },

  async addSaBankRent(jobId: string, body: { keys: string[]; property_id?: number | null; name?: string }): Promise<SaPropertyView> {
    const res = await fetch(`${API_BASE}/sa/jobs/${jobId}/property/bank-rent`, {
      method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body),
    });
    if (!res.ok) throw new Error(await detail(res, "Could not add the rent"));
    return res.json();
  },

  async deleteSaPropertyItem(jobId: string, propertyId: number, itemId: number): Promise<SaPropertyView> {
    const res = await fetch(`${API_BASE}/sa/jobs/${jobId}/property/${propertyId}/items/${itemId}`, { method: "DELETE" });
    if (!res.ok) throw new Error(await detail(res, "Could not remove the amount"));
    return res.json();
  },
};
