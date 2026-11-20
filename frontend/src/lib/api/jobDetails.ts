import { API_BASE, fetch } from "./client";

/** The job's own details (the Create Workpaper form): pack dates, job dates, who works on it */
export interface JobDetails {
  first_day: string | null;
  last_day: string | null;
  start_date: string | null;
  due_date: string | null;
  assigned_to: string | null;
  managed_by: string | null;
  partner: string | null;
}

export const jobDetailsApi = {
  async getJobDetails(engagementId: string): Promise<JobDetails> {
    const res = await fetch(`${API_BASE}/engagements/${engagementId}/job-details`);
    if (!res.ok) throw new Error("Could not load the job details");
    return res.json();
  },
  async saveJobDetails(engagementId: string, body: JobDetails): Promise<JobDetails> {
    const res = await fetch(`${API_BASE}/engagements/${engagementId}/job-details`, {
      method: "PUT", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body),
    });
    if (!res.ok) throw new Error((await res.json().catch(() => ({}))).detail || "Could not save the job details");
    return res.json();
  },
};
