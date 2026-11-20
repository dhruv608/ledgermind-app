// State and actions of the accounts and mappings table: last year, filters, sorting, ticks, the AI's options and
// confirming codes.
import React, { useState, useMemo, useEffect, useCallback } from "react";
import { TBRecord } from "@/types/engagement";
import { toast } from "@/lib/notify";
import { api, ConfirmResult, LastYear } from "@/lib/api";
import { useRememberedState } from "@/hooks/useRememberedState";
import { plural } from "@/lib/formatters";
import { usePagination } from "@/hooks/usePagination";
import {
  isBalanceSheet,
  isFlagged,
  matchesStatus,
  MappingTableProps,
  needsReview,
  SortField,
  SortOrder,
  StatusFilter,
  TRIVIAL_FLOOR,
} from "@/components/mapping/mapping-table/helpers";

export function useMappingTable({ records, engagementId, onChanged }: MappingTableProps) {
  const [localRecords, setLocalRecords] = useState<TBRecord[]>(records);
  // New records from the parent replace the local copy (during render, React's pattern for state that follows a prop)
  const [prevRecords, setPrevRecords] = useState(records);
  if (records !== prevRecords) {
    setPrevRecords(records);
    setLocalRecords(records);
  }

  // Last year's balances (last year's job in the app, else last year's TB in the files)
  const [lastYear, setLastYear] = useState<LastYear | null>(null);
  useEffect(() => {
    if (!engagementId) return;
    api.getLastYear(engagementId).then(setLastYear, () => setLastYear(null));
  }, [engagementId, records]);

  const [searchTerm, setSearchTerm] = useState("");
  const [statementArea, setStatementArea] = useState<"ALL" | "PL" | "BS">("ALL");
  const [balanceFilter, setBalanceFilter] = useState<string>("ALL");
  // The client's overall materiality (setup), for the "Over materiality" filter; else the default:
  // the lower of 1% of turnover or 5% of profit before tax, never under £250)
  const [setMateriality, setSetMateriality] = useState<number | null>(null);
  useEffect(() => {
    if (!engagementId) return;
    api.getSetupStatus(engagementId).then((s) => {
      const v = Number(s?.record?.materiality?.overall);
      setSetMateriality(Number.isFinite(v) && v > 0 ? v : null);
    }).catch(() => setSetMateriality(null));
  }, [engagementId]);
  const [sortField, setSortField] = useState<SortField>("raw_account_name");
  const [sortOrder, setSortOrder] = useState<SortOrder>("asc");
  const [statusFilter, setStatusFilter] = useRememberedState<StatusFilter>("accounts.status", "ALL");
  // Debit and credit columns: off by default (Net, Last year and Change are enough to read the table); remembered
  const [showDrCr, setShowDrCr] = useState(false);
  // Last year and Change only when last year's figures exist (empty columns otherwise); the table's column count
  const hasLastYear = Boolean(lastYear && Object.values(lastYear.accounts || {}).some((a) => a?.last_year !== null && a?.last_year !== undefined));
  const columns = 5 + (showDrCr ? 2 : 0) + (hasLastYear ? 2 : 0);
  useEffect(() => {
    try {
      // Read after mount so the server render and the first browser render agree (localStorage is browser-only)
      // eslint-disable-next-line react-hooks/set-state-in-effect -- one read of a browser-only setting after hydration
      setShowDrCr(localStorage.getItem("accounts.showDrCr") === "1");
    } catch {}
  }, []);
  const toggleDrCr = () => {
    setShowDrCr((v) => {
      try {
        localStorage.setItem("accounts.showDrCr", v ? "0" : "1");
      } catch {}
      return !v;
    });
  };
  const [isConfirmingAll, setIsConfirmingAll] = useState(false);
  const [askConfirmAll, setAskConfirmAll] = useState(false);
  // The AI's top 3 codes for one account, shown under its row (one click applies a code)
  const [optionsFor, setOptionsFor] = useState<string | null>(null);
  const [options, setOptions] = useState<{ std_code: number; std_name: string; confidence: number; reason: string }[]>([]);
  const [loadingOptions, setLoadingOptions] = useState(false);
  const showOptions = async (e: React.MouseEvent, rec: TBRecord) => {
    e.stopPropagation();
    if (!engagementId) return;
    if (optionsFor === rec.raw_account_name) {
      setOptionsFor(null);
      return;
    }
    setOptionsFor(rec.raw_account_name);
    setOptions([]);
    setLoadingOptions(true);
    try {
      setOptions(await api.getMappingOptions(engagementId, rec.raw_account_name));
    } catch (err: any) {
      toast.error("Suggestions not available", { description: err.message });
      setOptionsFor(null);
    } finally {
      setLoadingOptions(false);
    }
  };
  const chooseOption = async (rec: TBRecord, code: number, name: string) => {
    if (!engagementId) return;
    try {
      if (code === rec.std_code) {
        await api.confirmMappings(engagementId, [rec.raw_account_name]);
      } else {
        await api.updateSingleMapping(rec.raw_account_name, code, engagementId);
      }
      handleMappingUpdated(rec.raw_account_name, code, name);
      setOptionsFor(null);
      toast.success("Mapping set", { description: `"${rec.raw_account_name}" goes to ${code} ${name}.` });
    } catch (err: any) {
      toast.error("Mapping not set", { description: err.message });
    }
  };

  // Accounts ticked for confirming together
  const [ticked, setTicked] = useState<Set<string>>(new Set());


  // Materiality for the filter: the setup's, else the default from the TB (sales = codes 0-499, credit)
  const materiality = useMemo(() => {
    if (setMateriality) return setMateriality;
    const net = (r: TBRecord) => Number(r.net_amount || 0);
    const code = (r: TBRecord) => Number(r.std_code);
    const turnover = -localRecords.filter((r) => !isNaN(code(r)) && r.std_code !== null && code(r) < 500).reduce((s, r) => s + net(r), 0);
    const profit = -localRecords.filter((r) => !isBalanceSheet(r)).reduce((s, r) => s + net(r), 0);
    const options = [turnover > 0 ? turnover * 0.01 : null, profit > 0 ? profit * 0.05 : null].filter((v): v is number => v !== null);
    return Math.max(TRIVIAL_FLOOR, Math.round(options.length ? Math.min(...options) : TRIVIAL_FLOOR));
  }, [setMateriality, localRecords]);

  // The search, P&L / balance sheet and balance filters (the status tabs are counted within them, so a tab's count
  // is always what its list shows)
  const matchesView = useCallback((rec: TBRecord) => {
    const q = searchTerm.toLowerCase().trim();
    if (q && !(rec.raw_account_name.toLowerCase().includes(q) || (rec.std_name && rec.std_name.toLowerCase().includes(q))
               || (rec.std_code && rec.std_code.toString().includes(q)))) return false;
    if (statementArea === "PL" && isBalanceSheet(rec)) return false;
    if (statementArea === "BS" && !isBalanceSheet(rec)) return false;
    const debit = Number(rec.debit_amount || 0);
    const credit = Number(rec.credit_amount || 0);
    const net = Number(rec.net_amount || 0);
    const over = (limit: number) => Math.abs(net) >= limit || debit >= limit || credit >= limit;
    if (balanceFilter === "MATERIAL" && !over(materiality)) return false;
    if (balanceFilter === "OVER_250" && !over(TRIVIAL_FLOOR)) return false;
    if (balanceFilter === "NON_ZERO" && Math.abs(net) === 0) return false;
    if (balanceFilter === "ZERO_ONLY" && Math.abs(net) !== 0) return false;
    return true;
  }, [searchTerm, statementArea, balanceFilter, materiality]);
  const viewFiltered = searchTerm.trim() !== "" || statementArea !== "ALL" || balanceFilter !== "ALL";
  const plCount = localRecords.filter((r) => !isBalanceSheet(r)).length;
  const bsCount = localRecords.length - plCount;
  // Accounts of the chosen status that the filters hide (said under the filters, with a way to show them)
  const hiddenByView = viewFiltered ? localRecords.filter((r) => matchesStatus(r, statusFilter) && !matchesView(r)).length : 0;
  const inView = localRecords.filter(matchesView);
  const statusCounts = {
    REVIEW: inView.filter(needsReview).length,
    AI: inView.filter((r) => r.mapping_status === "AI_SUGGESTED").length,
    CONFIRMED: inView.filter((r) => r.mapping_status === "MATCHED").length,
    ALL: inView.length,
  };

  // Reassign Modal State
  const [reassignRecord, setReassignRecord] = useState<TBRecord | null>(null);
  const [isReassignOpen, setIsReassignOpen] = useState(false);
  const [confirmingAccount, setConfirmingAccount] = useState<string | null>(null);

  // Drawer state for inspecting itemized GL transactions
  const [selectedDrawerAccount, setSelectedDrawerAccount] = useState<TBRecord | null>(null);
  const [isDrawerOpen, setIsDrawerOpen] = useState(false);

  const handleSort = (field: SortField) => {
    if (sortField === field) {
      if (sortOrder === "asc") setSortOrder("desc");
      else if (sortOrder === "desc") setSortOrder("none");
      else setSortOrder("asc");
    } else {
      setSortField(field);
      setSortOrder("asc");
    }
  };

  const handleOpenReassign = (e: React.MouseEvent, rec: TBRecord) => {
    e.stopPropagation();
    setReassignRecord(rec);
    setIsReassignOpen(true);
  };

  const handleMappingUpdated = (rawAccountName: string, stdCode: number, stdName: string) => {
    setLocalRecords((prev) =>
      prev.map((r) =>
        r.raw_account_name === rawAccountName
          ? {
              ...r,
              std_code: stdCode,
              std_name: stdName,
              mapping_status: "MATCHED",
              confidence_score: 1.0,
            }
          : r
      )
    );
    onChanged?.();
  };

  const handleSingleConfirm = async (e: React.MouseEvent, rec: TBRecord) => {
    e.stopPropagation();
    if (!rec.std_code || !engagementId) return;
    setConfirmingAccount(rec.raw_account_name);
    try {
      await api.confirmMappings(engagementId, [rec.raw_account_name]);
      handleMappingUpdated(rec.raw_account_name, rec.std_code, rec.std_name || "");
      toast.success("Mapping confirmed", {
        description: `"${rec.raw_account_name}" stays on code ${rec.std_code}.`,
      });
    } catch (err: any) {
      toast.error("Mapping not confirmed", {
        description: err.message || "An unexpected error occurred.",
      });
    } finally {
      setConfirmingAccount(null);
    }
  };

  // Filter & Sort Logic
  const filteredAndSorted = useMemo(() => {
    let result = localRecords.filter((rec) => matchesStatus(rec, statusFilter) && matchesView(rec));

    if (sortOrder !== "none") {
      result = [...result].sort((a, b) => {
        let valA: any = a[sortField];
        let valB: any = b[sortField];

        // Handle nulls
        if (valA === null || valA === undefined) valA = "";
        if (valB === null || valB === undefined) valB = "";

        // Numeric comparison
        if (
          sortField === "debit_amount" ||
          sortField === "credit_amount" ||
          sortField === "net_amount" ||
          sortField === "std_code"
        ) {
          valA = Number(valA || 0);
          valB = Number(valB || 0);
          return sortOrder === "asc" ? valA - valB : valB - valA;
        }

        // String comparison
        const strA = String(valA).toLowerCase();
        const strB = String(valB).toLowerCase();
        if (strA < strB) return sortOrder === "asc" ? -1 : 1;
        if (strA > strB) return sortOrder === "asc" ? 1 : -1;
        return 0;
      });
    }

    return result;
  }, [localRecords, statusFilter, matchesView, sortField, sortOrder]);

  const announceConfirmed = (result: ConfirmResult) => {
    const left = [
      result.inSuspense.length ? `${plural(result.inSuspense.length, "account")} still in suspense` : "",
      result.toCheck.length ? `${plural(result.toCheck.length, "account")} to check one by one` : "",
    ].filter(Boolean);
    toast.success(`${plural(result.confirmed, "mapping")} confirmed`, left.length ? { description: `Not confirmed: ${left.join(", ")}.` } : undefined);
  };

  // Confirm every account the filter shows that still waits for a decision (after the accountant has read them)
  // Accounts still in suspense (9999) are never confirmed in bulk: each needs a real code first. Nor are those the
  // app flagged "Check" (the code contradicts the account's name or balance): each is looked at on its own.
  const confirmable = filteredAndSorted.filter(
    (r) => r.std_code !== null && r.std_code !== 9999 && r.mapping_status !== "MATCHED" && !isFlagged(r)
  );
  const handleConfirmAllShown = async () => {
    if (!engagementId || confirmable.length === 0) return;
    setAskConfirmAll(false);
    setIsConfirmingAll(true);
    try {
      const result = await api.confirmMappings(engagementId, confirmable.map((r) => r.raw_account_name));
      const names = new Set(result.names);
      setLocalRecords((prev) => prev.map((r) => (names.has(r.raw_account_name) ? { ...r, mapping_status: "MATCHED", confidence_score: 1.0 } : r)));
      announceConfirmed(result);
      onChanged?.();
    } catch (err: any) {
      toast.error("Could not confirm", { description: err.message });
    } finally {
      setIsConfirmingAll(false);
    }
  };

  // A page at a time; back to page 1 when the status, search, area, balance filter or the sort changes
  const page = usePagination({ items: filteredAndSorted, initialPageSize: 25,
                               resetDependencies: [statusFilter, searchTerm, statementArea, balanceFilter, sortField, sortOrder] });
  const paginatedRecords = page.paginatedItems;

  const canTick = (r: TBRecord) => r.std_code !== null && r.std_code !== 9999 && r.mapping_status !== "MATCHED" && !isFlagged(r);
  const tickablePage = paginatedRecords.filter(canTick);
  const allPageTicked = tickablePage.length > 0 && tickablePage.every((r) => ticked.has(r.raw_account_name));
  const toggleTick = (name: string) =>
    setTicked((prev) => {
      const next = new Set(prev);
      if (next.has(name)) next.delete(name);
      else next.add(name);
      return next;
    });
  const togglePage = () =>
    setTicked((prev) => {
      const next = new Set(prev);
      tickablePage.forEach((r) => (allPageTicked ? next.delete(r.raw_account_name) : next.add(r.raw_account_name)));
      return next;
    });
  const handleConfirmTicked = async () => {
    if (!engagementId || ticked.size === 0) return;
    setIsConfirmingAll(true);
    try {
      const names = Array.from(ticked);
      const result = await api.confirmMappings(engagementId, names);
      const done = new Set(result.names);
      setLocalRecords((prev) => prev.map((r) => (done.has(r.raw_account_name) ? { ...r, mapping_status: "MATCHED", confidence_score: 1.0 } : r)));
      setTicked(new Set());
      announceConfirmed(result);
      onChanged?.();
    } catch (err: any) {
      toast.error("Could not confirm", { description: err.message });
    } finally {
      setIsConfirmingAll(false);
    }
  };
  return {
    localRecords, lastYear, searchTerm, setSearchTerm, statementArea, setStatementArea, balanceFilter, setBalanceFilter,
    setMateriality, sortField, sortOrder, statusFilter, setStatusFilter, showDrCr, hasLastYear, columns, toggleDrCr,
    isConfirmingAll, askConfirmAll, setAskConfirmAll, optionsFor, setOptionsFor, options, loadingOptions, showOptions,
    chooseOption, ticked, setTicked, materiality, plCount, bsCount, hiddenByView, statusCounts, reassignRecord,
    isReassignOpen, setIsReassignOpen, confirmingAccount, selectedDrawerAccount, setSelectedDrawerAccount, isDrawerOpen,
    setIsDrawerOpen, handleSort, handleOpenReassign, handleMappingUpdated, handleSingleConfirm, confirmable,
    handleConfirmAllShown, page, paginatedRecords, allPageTicked, tickablePage, toggleTick, togglePage, handleConfirmTicked,
  };
}
