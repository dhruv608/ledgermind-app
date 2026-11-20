// Family and student loans, and foster or shared lives care relief.
import { API_BASE, fetch } from "../client";
import { detail } from "./detail";
import type { SaFamily, SaFamilyFacts, SaFosterView } from "./types";

export const saFamilyApi = {
  async getSaFamily(jobId: string): Promise<SaFamily> {
    const res = await fetch(`${API_BASE}/sa/jobs/${jobId}/family`);
    if (!res.ok) throw new Error(await detail(res, "Could not load family and loans"));
    return res.json();
  },

  async putSaFamily(jobId: string, facts: SaFamilyFacts): Promise<SaFamily> {
    const res = await fetch(`${API_BASE}/sa/jobs/${jobId}/family`, {
      method: "PUT", headers: { "Content-Type": "application/json" }, body: JSON.stringify(facts),
    });
    if (!res.ok) throw new Error(await detail(res, "Could not save"));
    return res.json();
  },

  async getSaFoster(jobId: string): Promise<SaFosterView> {
    const res = await fetch(`${API_BASE}/sa/jobs/${jobId}/foster`);
    if (!res.ok) throw new Error(await detail(res, "Could not load the care relief"));
    return res.json();
  },

  async putSaFoster(jobId: string, body: { receipts: number | null; carers: number; method: string | null; actual_costs: number | null }): Promise<SaFosterView> {
    const res = await fetch(`${API_BASE}/sa/jobs/${jobId}/foster`, {
      method: "PUT", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
    if (!res.ok) throw new Error(await detail(res, "Could not save the care relief"));
    return res.json();
  },

  async addSaPlacement(jobId: string, body: { label: string; band: string; weeks: number }): Promise<SaFosterView> {
    const res = await fetch(`${API_BASE}/sa/jobs/${jobId}/foster/placements`, {
      method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
    if (!res.ok) throw new Error(await detail(res, "Could not add the placement"));
    return res.json();
  },

  async removeSaPlacement(jobId: string, id: number): Promise<SaFosterView> {
    const res = await fetch(`${API_BASE}/sa/jobs/${jobId}/foster/placements/${id}`, { method: "DELETE" });
    if (!res.ok) throw new Error(await detail(res, "Could not remove the placement"));
    return res.json();
  },
};
