"use client";

import { rememberClients } from "@/lib/clientPeek";
import { useState, useEffect, useRef } from "react";
import { useRouter } from "next/navigation";
import { toast } from "@/lib/notify";
import { ClientListItem } from "@/types/engagement";
import { api, ConfirmedLayouts, FilesNeedRolesError, FileRole } from "@/lib/api";
import { ClientDirectory } from "@/components/clients/ClientDirectory";
import { Workspace } from "@/components/clients/Workspace";
import { UploadEngagementModal } from "@/components/upload/UploadEngagementModal";
import { WhoForChooser } from "@/components/sa/WhoForChooser";
import { NewIndividualModal } from "@/components/sa/NewIndividualModal";
import type { SaJob, SaJobStatus } from "@/lib/api";
import { plural } from "@/lib/formatters";

export default function HomePage() {
  const router = useRouter();
  const [clients, setClients] = useState<ClientListItem[]>([]);
  const [isLoadingClients, setIsLoadingClients] = useState<boolean>(true);
  const [isUploadModalOpen, setIsUploadModalOpen] = useState<boolean>(false);
  // "Add next year" on a company: the upload says which company and year-end the files are for
  const [nextYearOf, setNextYearOf] = useState<{ name: string; yearEnd: string } | undefined>(undefined);
  // A new client starts with "Who is this for?": a company (the upload) or an individual (a Self Assessment return)
  const [step, setStep] = useState<"none" | "choose" | "individual">("none");
  const [saJobs, setSaJobs] = useState<SaJob[]>([]);
  // Where each return stands (blocks, queries): read after the list, as it takes a moment
  const [saStatus, setSaStatus] = useState<Record<string, SaJobStatus> | null>(null);

  // Upload Progress States & Abort Management
  const [isUploading, setIsUploading] = useState(false);
  const [uploadProgress, setUploadProgress] = useState("");
  const [uploadStep, setUploadStep] = useState<number>(1);
  const [uploadPercent, setUploadPercent] = useState<number>(10);
  const abortControllerRef = useRef<AbortController | null>(null);
  const uploadTimersRef = useRef<NodeJS.Timeout[]>([]);

  const loadClients = async () => {
    setIsLoadingClients(true);
    try {
      const data = await api.listClients();
      setClients(data);
      rememberClients(data);
    } catch (err) {
      console.warn("Could not fetch client list:", err);
    } finally {
      setIsLoadingClients(false);
    }
  };

  useEffect(() => {
    // eslint-disable-next-line react-hooks/set-state-in-effect -- loads once on mount; loadClients shows the loading rows, then the list
    loadClients();
    api.listSaJobs().then(setSaJobs).catch(() => {});
    api.saJobsStatus().then(setSaStatus).catch(() => setSaStatus({}));
  }, []);

  // While a client's checks run in the background, its badge ("Checking · 6 of 13") is read again every 3 seconds,
  // quietly (no loading rows), until none is running
  const anyChecking = clients.some((c) => c.checking);
  useEffect(() => {
    if (!anyChecking) return;
    const timer = setInterval(() => api.listClients().then(setClients).catch(() => {}), 3000);
    return () => clearInterval(timer);
  }, [anyChecking]);

  const handleSelectClient = (engagementId: string) => {
    router.push(`/clients/${engagementId}`);
  };

  const handleDeleteClient = async (engagementId: string, clientName: string) => {
    try {
      await api.deleteClient(engagementId);
      setClients((prev) => prev.filter((c) => c.engagement_id !== engagementId));
      toast.success("Client deleted", {
        description: `"${clientName}" and its working papers are removed.`,
      });
    } catch (err: any) {
      toast.error("Client not deleted", {
        description: err.message || "Please try again.",
      });
    }
  };

  const handleBulkDeleteClients = async (engagementIds: string[]) => {
    try {
      await api.bulkDeleteClients(engagementIds);
      setClients((prev) => prev.filter((c) => !engagementIds.includes(c.engagement_id)));
      toast.success(`${plural(engagementIds.length, "client")} deleted`, {
        description: "Their working papers are removed.",
      });
    } catch (err: any) {
      toast.error("Clients not deleted", {
        description: err.message || "Please try again.",
      });
      throw err;
    }
  };

  const handleCloseUploadModal = () => {
    if (isUploading) {
      if (abortControllerRef.current) {
        abortControllerRef.current.abort();
        abortControllerRef.current = null;
      }
      uploadTimersRef.current.forEach((t) => clearTimeout(t));
      uploadTimersRef.current = [];
      setIsUploading(false);
      setIsUploadModalOpen(false);
      toast.info("Upload cancelled", {
        description: "Nothing was saved.",
      });
      return;
    }
    setIsUploadModalOpen(false);
  };

  const handleFileUpload = async (files: File[], roles?: Record<string, FileRole>, layouts?: ConfirmedLayouts, yearEnd?: string) => {
    const controller = new AbortController();
    abortControllerRef.current = controller;
    uploadTimersRef.current.forEach((t) => clearTimeout(t));
    uploadTimersRef.current = [];

    setIsUploading(true);
    setUploadStep(1);
    setUploadPercent(-1);
    setUploadProgress(`Reading the files, mapping accounts and running the first checks: 0:00`);

    // The server reads the files, maps every account and runs the first checks in one request, so there is no
    // real percentage to show: show the time taken instead (a full ledger usually takes 2-4 minutes)
    const startTime = Date.now();
    // The stage the server is at, asked every 2 seconds (so a long upload never looks stuck)
    const progressId = typeof crypto !== "undefined" && "randomUUID" in crypto ? crypto.randomUUID() : `${Date.now()}-${Math.random().toString(36).slice(2)}`;
    let asking = false;
    const progressInterval = setInterval(() => {
      const secs = Math.floor((Date.now() - startTime) / 1000);
      setUploadPercent(-1);
      setUploadProgress(`Usually 1 to 4 minutes for a full ledger: ${Math.floor(secs / 60)}:${String(secs % 60).padStart(2, "0")}`);
      if (secs % 2 === 0 && !asking) {
        asking = true;
        api.uploadProgress(progressId).then((p) => { if (p.stage > 0) setUploadStep(p.stage); }).catch(() => {}).finally(() => { asking = false; });
      }
    }, 1000);
    uploadTimersRef.current.push(progressInterval as any);

    try {
      const data = await api.uploadFiles(files, controller.signal, roles, layouts, yearEnd, progressId);

      clearInterval(progressInterval);
      uploadTimersRef.current.forEach((t) => clearTimeout(t));
      uploadTimersRef.current = [];

      // Every stage done
      setUploadStep(5);
      setUploadPercent(96);
      setUploadProgress("Running the review checks...");

      // Fetch audit findings
      await api.getAuditFindings(data.engagement_id);

      setUploadPercent(100);
      setUploadProgress("Client ready");

      toast.success("Client ready", {
        description: `${data.client_name}: ${data.total_tb_rows} accounts and ${data.total_gl_rows} ledger lines read.`,
      });

      // The client opens with the few questions the checks need on top of it
      const tRedirect = setTimeout(() => {
        setIsUploading(false);
        setIsUploadModalOpen(false);
        router.push(`/clients/${data.engagement_id}?questions=1`);
      }, 600);
      uploadTimersRef.current.push(tRedirect);
    } catch (err: any) {
      clearInterval(progressInterval);
      uploadTimersRef.current.forEach((t) => clearTimeout(t));
      uploadTimersRef.current = [];

      if (err.name === "AbortError" || controller.signal.aborted) {
        return;                     // cancelled by the user
      }

      toast.error(err instanceof FilesNeedRolesError ? "Say what each file is" : "The files could not be read", {
        description: err.message || "Failed to process accounting export files.",
      });
      setIsUploading(false);
    } finally {
      abortControllerRef.current = null;
    }
  };

  return (
    <div className="space-y-6">
      <Workspace
        clients={clients}
        saJobs={saJobs}
        saStatus={saStatus}
        isLoading={isLoadingClients}
        onNew={() => setStep("choose")}
        onOpenClient={handleSelectClient}
        onOpenReturn={(id) => router.push(`/sa/${id}`)}
        companyTable={
          <ClientDirectory
            clients={clients}
            isLoading={isLoadingClients}
            onSelectClient={handleSelectClient}
            onOpenUpload={(company) => {
              setNextYearOf(company);
              // A company's next year is a company job: straight to the upload
              if (company) setIsUploadModalOpen(true);
              else setStep("choose");
            }}
            onDeleteClient={handleDeleteClient}
            onBulkDeleteClients={handleBulkDeleteClients}
            showTitle={false}
          />
        }
      />

      <WhoForChooser
        isOpen={step === "choose"}
        onClose={() => setStep("none")}
        onCompany={() => {
          setStep("none");
          setIsUploadModalOpen(true);
        }}
        onIndividual={() => setStep("individual")}
      />
      <NewIndividualModal
        isOpen={step === "individual"}
        onClose={() => setStep("none")}
        onBack={() => setStep("choose")}
        companies={clients}
        onCreated={(job) => {
          setStep("none");
          toast.success("Return created", { description: `${job.person_name} ${job.tax_year}` });
          router.push(`/sa/${job.id}`);
        }}
      />

      {/* Centered Modal for New Client Upload */}
      <UploadEngagementModal
        isOpen={isUploadModalOpen}
        onClose={handleCloseUploadModal}
        nextYearOf={nextYearOf}
        onFileUpload={handleFileUpload}
        isUploading={isUploading}
        uploadProgress={uploadProgress}
        uploadStep={uploadStep}
        uploadPercent={uploadPercent}
      />
    </div>
  );
}
