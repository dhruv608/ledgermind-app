// Last year's return, the yes/no questions and the client queries.
import { API_BASE, fetch } from "../client";
import { detail } from "./detail";
import type { SaExpectIn, SaLastYear, SaQueries, SaQuestions } from "./types";

export const saQuestionsApi = {
  async getSaLastYear(jobId: string): Promise<SaLastYear> {
    const res = await fetch(`${API_BASE}/sa/jobs/${jobId}/last-year`);
    if (!res.ok) throw new Error(await detail(res, "Could not load last year"));
    return res.json();
  },

  async addSaLastYearLine(jobId: string, body: SaExpectIn): Promise<SaLastYear> {
    const res = await fetch(`${API_BASE}/sa/jobs/${jobId}/last-year/lines`, {
      method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body),
    });
    if (!res.ok) throw new Error(await detail(res, "Could not add the line"));
    return res.json();
  },

  async editSaLastYearLine(jobId: string, lineId: number, body: SaExpectIn): Promise<SaLastYear> {
    const res = await fetch(`${API_BASE}/sa/jobs/${jobId}/last-year/lines/${lineId}`, {
      method: "PATCH", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body),
    });
    if (!res.ok) throw new Error(await detail(res, "Could not save the line"));
    return res.json();
  },

  async deleteSaLastYearLine(jobId: string, lineId: number): Promise<SaLastYear> {
    const res = await fetch(`${API_BASE}/sa/jobs/${jobId}/last-year/lines/${lineId}`, { method: "DELETE" });
    if (!res.ok) throw new Error(await detail(res, "Could not remove the line"));
    return res.json();
  },

  async useAsLastYear(jobId: string, docId: number): Promise<SaLastYear> {
    const res = await fetch(`${API_BASE}/sa/jobs/${jobId}/documents/${docId}/last-year`, { method: "POST" });
    if (!res.ok) throw new Error(await detail(res, "Could not read the working paper"));
    return res.json();
  },

  async getSaQuestions(jobId: string): Promise<SaQuestions> {
    const res = await fetch(`${API_BASE}/sa/jobs/${jobId}/questions`);
    if (!res.ok) throw new Error(await detail(res, "Could not load the questions"));
    return res.json();
  },

  async putSaAnswer(jobId: string, key: string, value: string | null, note?: string | null): Promise<SaQuestions> {
    const res = await fetch(`${API_BASE}/sa/jobs/${jobId}/answers`, {
      method: "PUT", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ key, value, note }),
    });
    if (!res.ok) throw new Error(await detail(res, "Could not save the answer"));
    return res.json();
  },

  async getSaQueries(jobId: string): Promise<SaQueries> {
    const res = await fetch(`${API_BASE}/sa/jobs/${jobId}/queries`);
    if (!res.ok) throw new Error(await detail(res, "Could not load the queries"));
    return res.json();
  },

  async answerSaQuery(jobId: string, key: string, answer: string | null): Promise<SaQueries> {
    const res = await fetch(`${API_BASE}/sa/jobs/${jobId}/queries/answer`, {
      method: "PUT", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ key, answer }),
    });
    if (!res.ok) throw new Error(await detail(res, "Could not save the answer"));
    return res.json();
  },
};
