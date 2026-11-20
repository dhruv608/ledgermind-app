// The returns themselves: list, create, open, delete, and the whole-return views (overview, boxes, tax).
import { API_BASE, fetch } from "../client";
import { detail } from "./detail";
import type { SaBoxes, SaCalculation, SaJob, SaJobIn, SaJobStatus, SaOverview } from "./types";

export const saJobsApi = {
  async saJobsStatus(): Promise<Record<string, SaJobStatus>> {
    const res = await fetch(`${API_BASE}/sa/jobs/status`);
    if (!res.ok) throw new Error(await detail(res, "Could not load where the returns stand"));
    return res.json();
  },

  async listSaJobs(): Promise<SaJob[]> {
    const res = await fetch(`${API_BASE}/sa/jobs`);
    if (!res.ok) throw new Error(await detail(res, "Could not load the Self Assessment clients"));
    return res.json();
  },

  async createSaJob(job: SaJobIn): Promise<SaJob> {
    const res = await fetch(`${API_BASE}/sa/jobs`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(job),
    });
    if (!res.ok) throw new Error(await detail(res, "Could not create the return"));
    return res.json();
  },

  async getSaJob(jobId: string): Promise<SaJob> {
    const res = await fetch(`${API_BASE}/sa/jobs/${jobId}`);
    if (!res.ok) throw new Error(await detail(res, "Could not load the return"));
    return res.json();
  },

  async getSaOverview(jobId: string): Promise<SaOverview> {
    const res = await fetch(`${API_BASE}/sa/jobs/${jobId}/overview`);
    if (!res.ok) throw new Error(await detail(res, "Could not load the return"));
    return res.json();
  },

  async getSaBoxes(jobId: string): Promise<SaBoxes> {
    const res = await fetch(`${API_BASE}/sa/jobs/${jobId}/boxes`);
    if (!res.ok) throw new Error(await detail(res, "Could not load the figures by box"));
    return res.json();
  },

  async putSaPayments(jobId: string, body: { poa_paid: number; class2_voluntary: boolean; class4_exempt?: string;
                                             loss_claim?: string }): Promise<SaCalculation> {
    const res = await fetch(`${API_BASE}/sa/jobs/${jobId}/payments`, {
      method: "PUT", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
    if (!res.ok) throw new Error(await detail(res, "Could not save the payments"));
    return res.json();
  },

  async getSaCalculation(jobId: string): Promise<SaCalculation> {
    const res = await fetch(`${API_BASE}/sa/jobs/${jobId}/calculation`);
    if (!res.ok) throw new Error(await detail(res, "Could not work out the tax"));
    return res.json();
  },

  async deleteSaJob(jobId: string): Promise<void> {
    const res = await fetch(`${API_BASE}/sa/jobs/${jobId}`, { method: "DELETE" });
    if (!res.ok) throw new Error(await detail(res, "Could not delete the return"));
  },
};
