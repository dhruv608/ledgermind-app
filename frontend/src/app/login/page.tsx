"use client";

import { Suspense, useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { LogIn } from "lucide-react";
import { Button } from "@/components/ui/button";
import { signIn } from "@/lib/auth";

const inputClass =
  "w-full rounded-lg border border-slate-300 bg-white px-3 py-2 text-sm text-slate-800 focus:outline-none focus:ring-2 focus:ring-teal-200";

function LoginForm() {
  const router = useRouter();
  const next = useSearchParams().get("next") || "/";
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    setBusy(true);
    const problem = await signIn(email, password);
    setBusy(false);
    if (problem) setError(problem);
    else router.replace(next.startsWith("/") && !next.startsWith("//") ? next : "/");
  };

  return (
    <div className="mx-auto mt-16 w-full max-w-sm">
      <div className="rounded-2xl border border-slate-200 bg-white p-6 shadow-sm">
        <div className="mb-5 flex items-center gap-2.5">
          {/* eslint-disable-next-line @next/next/no-img-element */}
          <img src="/logo.png" alt="" width={36} height={36} className="h-9 w-9" />
          <div>
            <h1 className="text-base font-bold text-slate-900">Sign in</h1>
            <p className="text-[11px] text-slate-500">LedgerMind · year-end working papers</p>
          </div>
        </div>
        <form onSubmit={submit} className="space-y-3">
          <label className="block text-[11px] font-semibold text-slate-700">
            Email
            <input type="email" autoComplete="username" value={email} onChange={(e) => { setEmail(e.target.value); setError(""); }}
                   className={`${inputClass} mt-1 font-normal`} autoFocus />
          </label>
          <label className="block text-[11px] font-semibold text-slate-700">
            Password
            <input type="password" autoComplete="current-password" value={password}
                   onChange={(e) => { setPassword(e.target.value); setError(""); }} className={`${inputClass} mt-1 font-normal`} />
          </label>
          {error && <p className="text-xs text-rose-600">{error}</p>}
          <Button type="submit" variant="primary" className="h-9 w-full text-sm" disabled={busy}>
            <LogIn className="mr-1.5 h-4 w-4" /> {busy ? "Signing in…" : "Sign in"}
          </Button>
        </form>
      </div>
    </div>
  );
}

export default function LoginPage() {
  return (
    <Suspense fallback={null}>
      <LoginForm />
    </Suspense>
  );
}
