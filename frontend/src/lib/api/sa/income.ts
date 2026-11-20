// Income lines on a return, and dividends taken from the director's own company.
import { API_BASE, fetch } from "../client";
import { detail } from "./detail";
import type { SaDividend, SaLine, SaLineIn } from "./types";

export const saIncomeApi = {
  async listSaLines(jobId: string): Promise<SaLine[]> {
    const res = await fetch(`${API_BASE}/sa/jobs/${jobId}/lines`);
    if (!res.ok) throw new Error(await detail(res, "Could not load the figures"));
    return res.json();
  },

  async addSaLine(jobId: string, line: SaLineIn): Promise<SaLine[]> {
    const res = await fetch(`${API_BASE}/sa/jobs/${jobId}/lines`, {
      method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(line),
    });
    if (!res.ok) throw new Error(await detail(res, "Could not add the line"));
    return res.json();
  },

  async editSaLine(jobId: string, lineId: number, patch: Partial<SaLine>): Promise<SaLine[]> {
    const res = await fetch(`${API_BASE}/sa/jobs/${jobId}/lines/${lineId}`, {
      method: "PATCH", headers: { "Content-Type": "application/json" }, body: JSON.stringify(patch),
    });
    if (!res.ok) throw new Error(await detail(res, "Could not save the line"));
    return res.json();
  },

  async deleteSaLine(jobId: string, lineId: number): Promise<SaLine[]> {
    const res = await fetch(`${API_BASE}/sa/jobs/${jobId}/lines/${lineId}`, { method: "DELETE" });
    if (!res.ok) throw new Error(await detail(res, "Could not remove the line"));
    return res.json();
  },

  async getDirectorDividends(jobId: string): Promise<SaDividend[]> {
    const res = await fetch(`${API_BASE}/sa/jobs/${jobId}/director-dividends`);
    if (!res.ok) throw new Error(await detail(res, "Could not read the company's dividends"));
    return res.json();
  },

  async addDirectorDividends(jobId: string): Promise<SaLine[]> {
    const res = await fetch(`${API_BASE}/sa/jobs/${jobId}/director-dividends`, { method: "POST" });
    if (!res.ok) throw new Error(await detail(res, "Could not add the dividends"));
    return res.json();
  },
};
