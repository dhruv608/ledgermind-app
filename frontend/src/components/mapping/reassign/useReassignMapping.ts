// State and actions of the change-code modal: the chart, the search and category filter, and changing, confirming or
// resetting an account's code.
import { useState, useEffect, useMemo } from "react";
import { api } from "@/lib/api";
import { toast } from "@/lib/notify";
import { TBRecord } from "@/types/engagement";
import { CATEGORY_GROUPS, MasterCOAItem } from "@/components/mapping/reassign/categories";

export interface ReassignMappingModalProps {
  isOpen: boolean;
  onClose: () => void;
  record: TBRecord | null;
  onMappingUpdated: (rawAccountName: string, stdCode: number, stdName: string) => void;
  engagementId?: string;
}

/** The category filter an account's name points to (bank, sales, staff...), else all */
function guessCategory(record: TBRecord): string {
  const raw = record.raw_account_name.toLowerCase();
  if (raw.includes("bank") || raw.includes("cash") || raw.includes("deposit") || raw.includes("current acc")) {
    return "BANK";
  } else if (raw.includes("sale") || raw.includes("revenue") || raw.includes("turnover") || raw.includes("income")) {
    return "SALES";
  } else if (raw.includes("cost of sale") || raw.includes("purchases") || raw.includes("materials")) {
    return "COS";
  } else if (raw.includes("wage") || raw.includes("salar") || raw.includes("ni") || raw.includes("nest") || raw.includes("pension")) {
    return "STAFF";
  } else if (raw.includes("fa -") || raw.includes("asset") || raw.includes("depn") || raw.includes("equipment")) {
    return "ASSETS";
  } else if (raw.includes("debtor") || raw.includes("prepay")) {
    return "DEBTORS";
  } else if (raw.includes("creditor") || raw.includes("loan") || raw.includes("vat") || raw.includes("accrual")) {
    return "CREDITORS";
  }
  return "ALL";
}

export function useReassignMapping({
  isOpen,
  onClose,
  record,
  onMappingUpdated,
  engagementId,
}: ReassignMappingModalProps) {
  const [coaList, setCoaList] = useState<MasterCOAItem[]>([]);
  const [isLoading, setIsLoading] = useState(false);
  const [isSaving, setIsSaving] = useState(false);
  const [isResetting, setIsResetting] = useState(false);
  const [searchQuery, setSearchQuery] = useState("");
  const [selectedCategory, setSelectedCategory] = useState<string>("ALL");

  // Confirmation state
  const [pendingItem, setPendingItem] = useState<MasterCOAItem | null>(null);
  const [isConfirmingReset, setIsConfirmingReset] = useState(false);

  // Opening the modal: a fresh search and no pending choice; loading shows until the chart has come (set during
  // render, so the effect below only fetches)
  const [wasOpen, setWasOpen] = useState(false);
  if (isOpen !== wasOpen) {
    setWasOpen(isOpen);
    if (isOpen) {
      setSearchQuery("");
      setPendingItem(null);
      setIsConfirmingReset(false);
      if (coaList.length === 0) setIsLoading(true);
    }
  }

  // Auto-detect the best category filter when the modal opens or record changes
  const openRecord = isOpen ? record : null;
  const [categoryFor, setCategoryFor] = useState<TBRecord | null>(null);
  if (openRecord !== categoryFor) {
    setCategoryFor(openRecord);
    if (openRecord) setSelectedCategory(guessCategory(openRecord));
  }

  // The chart loads once, the first time the modal opens
  const haveCoa = coaList.length > 0;
  useEffect(() => {
    if (!isOpen || haveCoa) return;
    api
      .getMasterCOA()
      .then(setCoaList)
      .catch(() => toast.error("The chart of accounts did not load"))
      .finally(() => setIsLoading(false));
  }, [isOpen, haveCoa]);

  const currentCOAItem = useMemo(() => {
    if (!record?.std_code) return null;
    return coaList.find((c) => c.std_code === record.std_code) || null;
  }, [record, coaList]);

  // Filter COA by search query and category group
  const filteredCOA = useMemo(() => {
    let list = coaList;

    // Apply category filter if not ALL
    if (selectedCategory !== "ALL") {
      const group = CATEGORY_GROUPS.find((g) => g.id === selectedCategory);
      if (group) {
        list = list.filter((c) => (c.category ? group.matcher(c.category) : false));
      }
    }

    // Apply search query: a typed code jumps to that code first, then codes starting with it
    const q = searchQuery.toLowerCase().trim();
    if (q) {
      // Every typed word must appear in the code, name or section ("0 sales", "3070 staff" both work)
      const parts = q.split(/\s+/);
      list = list.filter((c) => {
        const text = `${c.std_code} ${c.std_name} ${c.category || ""}`.toLowerCase();
        return parts.every((p) => (/^\d+$/.test(p) ? String(c.std_code).startsWith(p) || text.includes(p) : text.includes(p)));
      });
      const first = parts[0];
      const rank = (c: MasterCOAItem) => {
        const code = String(c.std_code);
        if (code === first) return 0;
        if (code.startsWith(first)) return 1;
        if (c.std_name.toLowerCase().startsWith(q) || c.std_name.toLowerCase().startsWith(first)) return 2;
        return 3;
      };
      list = [...list].sort((a, b) => rank(a) - rank(b));
    }

    return list;
  }, [coaList, selectedCategory, searchQuery]);

  // A row clicked: open the confirmation step
  const handleInitiateSelect = (item: MasterCOAItem) => {
    if (record?.std_code === item.std_code) {
      if (record.mapping_status === "MATCHED" || !engagementId) {
        toast.info("Already confirmed", { description: `"${record.raw_account_name}" is on code ${item.std_code}.` });
        return;
      }
      // The suggested code is right: confirming it clears the review
      setIsSaving(true);
      api.confirmMappings(engagementId, [record.raw_account_name])
        .then(() => {
          onMappingUpdated(record.raw_account_name, item.std_code, item.std_name);
          toast.success("Mapping confirmed", { description: `"${record.raw_account_name}" stays on code ${item.std_code}.` });
          onClose();
        })
        .catch((err) => toast.error("Could not confirm", { description: err.message }))
        .finally(() => setIsSaving(false));
      return;
    }
    setPendingItem(item);
  };

  // The change confirmed in the confirmation step
  const handleConfirmReassign = async () => {
    if (!record || !pendingItem) return;
    setIsSaving(true);
    try {
      await api.updateSingleMapping(record.raw_account_name, pendingItem.std_code, engagementId);
      onMappingUpdated(record.raw_account_name, pendingItem.std_code, pendingItem.std_name);
      toast.success("Mapping changed", {
        description: `"${record.raw_account_name}" now goes to ${pendingItem.std_code} ${pendingItem.std_name}.`,
      });
      setPendingItem(null);
      onClose();
    } catch (err: any) {
      toast.error("Mapping not changed", {
        description: err.message || "Please try again.",
      });
    } finally {
      setIsSaving(false);
    }
  };

  // Reset to the AI's code confirmed
  const handleConfirmResetToAI = async () => {
    if (!record) return;
    setIsResetting(true);
    try {
      const res = await api.resetToAISuggestion(record.raw_account_name, engagementId);
      onMappingUpdated(record.raw_account_name, res.std_code, res.std_name);
      toast.success("Back to the AI suggestion", {
        description: `"${record.raw_account_name}" goes to ${res.std_code} ${res.std_name} again.`,
      });
      setIsConfirmingReset(false);
      onClose();
    } catch (err: any) {
      toast.error("Not reset", {
        description: err.message || "Please try again.",
      });
    } finally {
      setIsResetting(false);
    }
  };
  return {
    coaList, isLoading, isSaving, isResetting, searchQuery, setSearchQuery, selectedCategory, setSelectedCategory,
    pendingItem, setPendingItem, isConfirmingReset, setIsConfirmingReset, currentCOAItem, filteredCOA,
    handleInitiateSelect, handleConfirmReassign, handleConfirmResetToAI,
  };
}
