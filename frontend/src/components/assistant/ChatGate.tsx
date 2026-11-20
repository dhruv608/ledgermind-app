"use client";

import { useEffect, useRef, useState } from "react";
import { Loader2 } from "lucide-react";
import { API_BASE, CHAT_LOCKED_EVENT, fetch } from "@/lib/api/client";
import { AssistantPanel } from "./AssistantPanel";

/** The test chat page (/chat): asks for the 4-digit code once on a device (the server checks it and remembers the
 * device), then shows the assistant full screen. If the device is forgotten, the code screen comes back. */

type State = "loading" | "off" | "locked" | "open";

export function ChatGate() {
  const [state, setState] = useState<State>("loading");

  useEffect(() => {
    fetch(`${API_BASE}/chat-access/status`)
      .then((r) => r.json())
      .then((s: { enabled: boolean; unlocked: boolean }) => setState(!s.enabled ? "off" : s.unlocked ? "open" : "locked"))
      .catch(() => setState("locked"));
    const locked = () => setState((s) => (s === "open" ? "locked" : s));
    window.addEventListener(CHAT_LOCKED_EVENT, locked);
    return () => window.removeEventListener(CHAT_LOCKED_EVENT, locked);
  }, []);

  if (state === "open") return <AssistantPanel standalone />;
  return (
    <div className="fixed inset-0 z-[60] flex items-center justify-center bg-slate-50 px-4">
      {state === "loading" && <Loader2 className="h-6 w-6 animate-spin text-slate-400" />}
      {state === "off" && (
        <Card>
          <p className="text-[14px] text-slate-600">This chat is switched off at the moment.</p>
        </Card>
      )}
      {state === "locked" && <CodeScreen onOpen={() => setState("open")} />}
    </div>
  );
}

function Card({ children }: { children: React.ReactNode }) {
  return (
    <div className="w-full max-w-sm rounded-2xl border border-slate-200 bg-white px-6 py-8 text-center shadow-sm">
      {/* eslint-disable-next-line @next/next/no-img-element */}
      <img src="/logo.png" alt="LedgerMind" width={56} height={56} className="mx-auto h-14 w-14" />
      <p className="mt-4 text-[18px] font-semibold tracking-tight text-slate-900">LedgerMind Chat</p>
      <div className="mt-3">{children}</div>
    </div>
  );
}

/** Four boxes like a phone's PIN: each digit moves to the next box; the fourth sends it. */
function CodeScreen({ onOpen }: { onOpen: () => void }) {
  const [digits, setDigits] = useState(["", "", "", ""]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const boxes = useRef<(HTMLInputElement | null)[]>([]);

  useEffect(() => { boxes.current[0]?.focus(); }, []);

  const submit = async (code: string) => {
    setBusy(true);
    setError(null);
    try {
      const r = await fetch(`${API_BASE}/chat-access/code`, {
        method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ code }),
      });
      if (r.ok) {
        onOpen();
        return;
      }
      const body = await r.json().catch(() => ({}));
      setError(body.detail || "Wrong code. Try again.");
    } catch {
      setError("The server could not be reached. Try again.");
    }
    setBusy(false);
    setDigits(["", "", "", ""]);
    setTimeout(() => boxes.current[0]?.focus(), 0);
  };

  const put = (i: number, raw: string) => {
    const typed = raw.replace(/\D/g, "");
    const next = [...digits];
    if (!typed) {
      next[i] = "";                       // the digit deleted
      setDigits(next);
      return;
    }
    // Typed into a filled box: the old digit is first, the new one after it
    const fresh = digits[i] && typed.length > 1 && typed.startsWith(digits[i]) ? typed.slice(1) : typed;
    // A pasted code fills the boxes from here on
    fresh.split("").slice(0, 4 - i).forEach((d, k) => { next[i + k] = d; });
    setDigits(next);
    setError(null);
    const filled = next.findIndex((d) => !d);
    if (filled === -1) submit(next.join(""));
    else boxes.current[filled]?.focus();
  };

  return (
    <Card>
      <p className="text-[13px] text-slate-500">Enter the 4-digit code</p>
      <div className="mt-5 flex justify-center gap-3">
        {digits.map((d, i) => (
          <input
            key={i}
            ref={(el) => { boxes.current[i] = el; }}
            value={d}
            disabled={busy}
            inputMode="numeric"
            autoComplete="one-time-code"
            maxLength={4}
            type="password"
            aria-label={`Digit ${i + 1}`}
            onChange={(e) => put(i, e.target.value)}
            onKeyDown={(e) => {
              // The code opens on its 4th digit; Enter sends it too (after a wrong code, say)
              if (e.key === "Enter") {
                e.preventDefault();
                const code = digits.join("");
                if (code.length === 4 && !busy) submit(code);
                else setError("Enter all 4 digits.");
                return;
              }
              if (e.key === "Backspace" && !d && i > 0) {
                const next = [...digits];
                next[i - 1] = "";
                setDigits(next);
                boxes.current[i - 1]?.focus();
              }
            }}
            className={`h-14 w-12 rounded-xl border bg-white text-center text-[22px] font-semibold text-slate-900 outline-none transition focus:border-teal-500 focus:ring-2 focus:ring-teal-100 disabled:opacity-60 ${error ? "border-rose-300" : "border-slate-300"}`}
          />
        ))}
      </div>
      <p className={`mt-4 min-h-[20px] text-[12.5px] ${error ? "text-rose-600" : "text-slate-400"}`}>
        {busy ? "Checking…" : error || "You will only be asked once on this device."}
      </p>
    </Card>
  );
}
