// The Books tab's data and actions: loading the books, saving a choice, AI suggestions and making the trial balance.

import { useEffect, useState } from "react";
import { toast } from "@/lib/notify";
import { useRememberedState } from "@/hooks/useRememberedState";
import { api, BooksData } from "@/lib/api";
import { View } from "./common";

export function useBooks(engagementId: string, onTrialBalanceMade: () => void) {
  const [data, setData] = useState<BooksData | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [view, setView] = useRememberedState<View>("books.view", "bank");
  const [onlyToCheck, setOnlyToCheck] = useRememberedState("books.onlyToCheck", true);
  const [search, setSearch] = useState("");
  const [saving, setSaving] = useState<string | null>(null);
  const [making, setMaking] = useState(false);
  const [suggesting, setSuggesting] = useState(false);

  const load = async () => {
    try {
      setData(await api.getBooks(engagementId));
      setError(null);
    } catch (e: any) {
      setError(e.message);
    }
  };
  // The same as load(), written out so the state is set only when the answer arrives
  useEffect(() => {
    api.getBooks(engagementId)
      .then((d) => { setData(d); setError(null); })
      .catch((e: any) => setError(e.message));
  }, [engagementId]);

  const choose = async (key: string, value: Record<string, unknown> | null) => {
    setSaving(key);
    try {
      await api.saveBooksChoice(engagementId, key, value);
      await load();
      // Say what was done: the coded lines leave the To check list and the next one moves into their place
      if (value && (key.startsWith("payee:") || key.startsWith("bank:"))) {
        const code = value.code !== undefined ? data?.chart?.find((c) => c.code === Number(value.code)) : undefined;
        const what = code ? `${String(code.code).padStart(4, "0")} ${code.name}` : String(value.head || "");
        const lines = key.startsWith("payee:") ? data?.bank.filter((r) => r.payee === key.slice(6)).length || 0 : 1;
        toast.success(key.startsWith("payee:") ? `${lines} "${key.slice(6)}" line${lines === 1 ? "" : "s"} coded` : "Line coded",
                      { description: what });
      }
    } catch (e: any) {
      toast.error("Not saved", { description: e.message });
    } finally {
      setSaving(null);
    }
  };

  // The AI's suggested code for each payee no rule fits: shown on the lines, used only by a click
  const suggestWithAi = async () => {
    setSuggesting(true);
    try {
      const r = await api.suggestBankHeads(engagementId);
      await load();
      setView("ai");
      toast.success(r.asked ? `AI suggestions for ${r.suggested} of ${r.asked} payees` : "Every payee already has a suggestion",
                    { description: "One row per payee: Use it codes all its lines." });
    } catch (e: any) {
      toast.error("AI suggestions not made", { description: e.message });
    } finally {
      setSuggesting(false);
    }
  };

  const makeTrialBalance = async () => {
    setMaking(true);
    try {
      const r = await api.makeBooksTrialBalance(engagementId);
      toast.success("Trial balance made", { description: `${r.accounts} accounts. The Accounts and Review tabs now use it.` });
      onTrialBalanceMade();
    } catch (e: any) {
      toast.error("Trial balance not made", { description: e.message });
    } finally {
      setMaking(false);
    }
  };

  return {
    data, error, view, setView, onlyToCheck, setOnlyToCheck, search, setSearch, saving, making, suggesting,
    choose, suggestWithAi, makeTrialBalance,
  };
}
