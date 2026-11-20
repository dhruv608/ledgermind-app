// The working paper pack: make a version and download it.
import { API_BASE, fetch } from "../client";
import { detail } from "./detail";
import type { SaPacks } from "./types";

export const saPackApi = {
  async getSaPacks(jobId: string): Promise<SaPacks> {
    const res = await fetch(`${API_BASE}/sa/jobs/${jobId}/pack`);
    if (!res.ok) throw new Error(await detail(res, "Could not load the pack"));
    return res.json();
  },

  async makeSaPack(jobId: string, final: boolean, note: string | null): Promise<SaPacks> {
    const res = await fetch(`${API_BASE}/sa/jobs/${jobId}/pack`, {
      method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ final, note }),
    });
    if (!res.ok) throw new Error(await detail(res, "Could not make the pack"));
    return res.json();
  },

  /** Save a version of the pack as it was made. */
  async downloadSaPack(jobId: string, packId: number): Promise<void> {
    const res = await fetch(`${API_BASE}/sa/jobs/${jobId}/pack/${packId}/file`);
    if (!res.ok) throw new Error(await detail(res, "Could not download the pack"));
    const name = /filename="([^"]+)"/.exec(res.headers.get("Content-Disposition") || "")?.[1] || "Working paper.xlsx";
    const url = URL.createObjectURL(await res.blob());
    const a = Object.assign(document.createElement("a"), { href: url, download: name });
    document.body.appendChild(a);
    a.click();
    a.remove();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
  },
};
