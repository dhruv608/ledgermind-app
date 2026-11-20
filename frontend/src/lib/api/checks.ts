// The client's checks running in the background: where the latest run has got, and a way to start one.
import { API_BASE, fetch } from "./client";

export interface CheckRun {
  id?: number;
  /** NONE (never run), RUNNING, DONE or FAILED */
  status: "NONE" | "RUNNING" | "DONE" | "FAILED";
  trigger?: string | null;
  step?: string | null;
  step_label?: string;
  steps_done?: number;
  steps_total?: number;
  /** The areas in the order they are checked */
  steps: string[];
  summary?: {
    points?: number;
    journals?: number;
    seconds?: number;
    /** Seconds into the run each step started, by step key */
    started?: Record<string, number>;
    /** What each step left: open points and proposed journals (their total), by step key */
    results?: Record<string, { points: number; journals: number; amount: number }>;
  } | null;
  error?: string | null;
  started_at?: string | null;
  finished_at?: string | null;
  /** The step keys, in the order of steps */
  step_keys?: string[];
  /** The latest runs, newest first */
  history?: { id: number; status: string; trigger: string | null; started_at: string | null; seconds: number | null }[];
  /** On a start: what the setup still needs before the checks can run */
  waiting_for_setup?: string[];
}

export const checksApi = {
  async getChecks(engagementId: string): Promise<CheckRun> {
    const res = await fetch(`${API_BASE}/engagements/${engagementId}/checks`);
    if (!res.ok) throw new Error("Could not read the checks");
    return res.json();
  },

  async startChecks(engagementId: string): Promise<CheckRun> {
    const res = await fetch(`${API_BASE}/engagements/${engagementId}/checks`, { method: "POST" });
    if (!res.ok) throw new Error((await res.json().catch(() => ({}))).detail || "Could not start the checks");
    return res.json();
  },
};
