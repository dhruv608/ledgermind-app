"use client";

import { useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { Loader2 } from "lucide-react";
import { toast } from "@/lib/notify";
import type { JobDetails } from "@/lib/api";
import { api } from "@/lib/api";
import { Button } from "@/components/ui/button";
import { Modal } from "@/components/ui/dialog";
import { jobKeys, useJobDetails } from "@/lib/queries/job";

/**
 * The job's own details under the client's name (the Create Workpaper form): first and last day in the
 * pack, the job's start and due dates, assigned to, managed by, partner. One quiet line; Edit opens the form.
 */
const EMPTY: JobDetails = { first_day: null, last_day: null, start_date: null, due_date: null, assigned_to: null, managed_by: null, partner: null };
const day = (iso: string | null) => (iso ? iso.split("-").reverse().join("/") : "");
const field = "w-full rounded-md border border-slate-300 bg-white px-2.5 py-1.5 text-xs text-slate-800 focus:outline-none focus:ring-2 focus:ring-teal-200";

export function JobDetailsLine({ engagementId }: { engagementId: string }) {
  const q = useJobDetails(engagementId);
  const [editing, setEditing] = useState(false);
  const j = q.data ?? EMPTY;
  const parts = [
    j.first_day && j.last_day ? `Pack ${day(j.first_day)} to ${day(j.last_day)}` : "",
    j.due_date ? `Due ${day(j.due_date)}` : "",
    j.assigned_to ? `Assigned to ${j.assigned_to}` : "",
    j.managed_by ? `Managed by ${j.managed_by}` : "",
    j.partner ? `Partner ${j.partner}` : "",
  ].filter(Boolean);
  return (
    <>
      <p className="mt-0.5 text-[11px] leading-relaxed text-slate-500">
        {parts.length ? parts.join(" · ") : "No job details yet"}
        <button type="button" onClick={() => setEditing(true)} className="ml-1.5 font-semibold text-teal-700 hover:underline">
          {parts.length ? "Edit" : "Add"}
        </button>
      </p>
      {editing && <JobDetailsForm engagementId={engagementId} start={j} onClose={() => setEditing(false)} />}
    </>
  );
}

function JobDetailsForm({ engagementId, start, onClose }: { engagementId: string; start: JobDetails; onClose: () => void }) {
  const qc = useQueryClient();
  const [v, setV] = useState<JobDetails>(start);
  const [saving, setSaving] = useState(false);
  const set = (k: keyof JobDetails) => (e: React.ChangeEvent<HTMLInputElement>) => setV({ ...v, [k]: e.target.value || null });
  const save = async () => {
    setSaving(true);
    try {
      qc.setQueryData(jobKeys.jobDetails(engagementId), await api.saveJobDetails(engagementId, v));
      onClose();
    } catch (e) {
      toast.error((e as Error).message);
    } finally {
      setSaving(false);
    }
  };
  const input = (k: keyof JobDetails, label: string, type: "date" | "text" = "text") => (
    <label className="block space-y-1">
      <span className="text-[11px] font-semibold text-slate-600">{label}</span>
      <input type={type} value={v[k] ?? ""} onChange={set(k)} className={field} />
    </label>
  );
  return (
    <Modal isOpen onClose={onClose} title="Job details" description="The pack, the dates and who works on this job.">
      <div className="space-y-4">
        <div className="grid gap-3 sm:grid-cols-2">
          {input("first_day", "First day in the pack", "date")}
          {input("last_day", "Last day in the pack", "date")}
          {input("start_date", "Job start date", "date")}
          {input("due_date", "Job due date", "date")}
        </div>
        <div className="grid gap-3 sm:grid-cols-3">
          {input("assigned_to", "Assigned to")}
          {input("managed_by", "Managed by")}
          {input("partner", "Partner")}
        </div>
        <div className="flex justify-end gap-2">
          <Button variant="outline" size="sm" className="h-8 text-xs" onClick={onClose}>Cancel</Button>
          <Button variant="primary" size="sm" className="h-8 text-xs" disabled={saving} onClick={save}>
            {saving && <Loader2 className="mr-1.5 h-3.5 w-3.5 animate-spin" />} Save
          </Button>
        </div>
      </div>
    </Modal>
  );
}
