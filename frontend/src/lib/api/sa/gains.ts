// Foreign income and capital gains.
import { API_BASE, fetch } from "../client";
import { detail } from "./detail";
import type { SaCapitalGains, SaDisposalIn, SaForeign, SaForeignIn } from "./types";

export const saGainsApi = {
  async getSaForeign(jobId: string): Promise<SaForeign> {
    const res = await fetch(`${API_BASE}/sa/jobs/${jobId}/foreign`);
    if (!res.ok) throw new Error(await detail(res, "Could not load foreign income"));
    return res.json();
  },

  async saveSaForeign(jobId: string, body: SaForeignIn, id?: number): Promise<SaForeign> {
    const res = await fetch(`${API_BASE}/sa/jobs/${jobId}/foreign${id ? `/${id}` : ""}`, {
      method: id ? "PUT" : "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body),
    });
    if (!res.ok) throw new Error(await detail(res, "Could not save"));
    return res.json();
  },

  async deleteSaForeign(jobId: string, id: number): Promise<SaForeign> {
    const res = await fetch(`${API_BASE}/sa/jobs/${jobId}/foreign/${id}`, { method: "DELETE" });
    if (!res.ok) throw new Error(await detail(res, "Could not delete"));
    return res.json();
  },

  async getSaCapitalGains(jobId: string): Promise<SaCapitalGains> {
    const res = await fetch(`${API_BASE}/sa/jobs/${jobId}/capital-gains`);
    if (!res.ok) throw new Error(await detail(res, "Could not load capital gains"));
    return res.json();
  },

  async saveSaDisposal(jobId: string, body: SaDisposalIn, id?: number): Promise<SaCapitalGains> {
    const res = await fetch(`${API_BASE}/sa/jobs/${jobId}/capital-gains/disposals${id ? `/${id}` : ""}`, {
      method: id ? "PUT" : "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body),
    });
    if (!res.ok) throw new Error(await detail(res, "Could not save the disposal"));
    return res.json();
  },

  async deleteSaDisposal(jobId: string, id: number): Promise<SaCapitalGains> {
    const res = await fetch(`${API_BASE}/sa/jobs/${jobId}/capital-gains/disposals/${id}`, { method: "DELETE" });
    if (!res.ok) throw new Error(await detail(res, "Could not delete the disposal"));
    return res.json();
  },

  async addSaShareTrade(jobId: string, body: { holding: string; kind: string; on: string; side: string; quantity: number; amount: number }): Promise<SaCapitalGains> {
    const res = await fetch(`${API_BASE}/sa/jobs/${jobId}/capital-gains/trades`, {
      method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body),
    });
    if (!res.ok) throw new Error(await detail(res, "Could not add the trade"));
    return res.json();
  },

  async deleteSaShareTrade(jobId: string, id: number): Promise<SaCapitalGains> {
    const res = await fetch(`${API_BASE}/sa/jobs/${jobId}/capital-gains/trades/${id}`, { method: "DELETE" });
    if (!res.ok) throw new Error(await detail(res, "Could not delete the trade"));
    return res.json();
  },

  async putSaCapitalLosses(jobId: string, losses_bf: number): Promise<SaCapitalGains> {
    const res = await fetch(`${API_BASE}/sa/jobs/${jobId}/capital-gains/losses`, {
      method: "PUT", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ losses_bf }),
    });
    if (!res.ok) throw new Error(await detail(res, "Could not save the losses"));
    return res.json();
  },
};
