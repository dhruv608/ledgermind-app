"use client";

import { useEffect, useRef, useState } from "react";
import { usePathname, useRouter } from "next/navigation";
import { LogOut } from "lucide-react";
import { checkSession, signedInEmail, signOut } from "@/lib/auth";

/** Shows the app only after signing in; any other page sends you to /login first. */
export function AuthGate({ children }: { children: React.ReactNode }) {
  const router = useRouter();
  const pathname = usePathname();
  const [ready, setReady] = useState(false);

  useEffect(() => {
    // The sign-in page, and the test chat page (opened with its own code)
    if (pathname === "/login" || pathname === "/chat" || (pathname || "").startsWith("/chat/")) {
      // eslint-disable-next-line react-hooks/set-state-in-effect -- once shown, the app stays shown across page changes (ready is never reset)
      setReady(true);
      return;
    }
    let alive = true;
    // Quick start from what the browser remembers, then the server confirms the session is still valid
    if (signedInEmail()) setReady(true);
    checkSession().then((email) => {
      if (!alive) return;
      if (!email) router.replace(`/login?next=${encodeURIComponent(pathname || "/")}`);
      else setReady(true);
    });
    return () => {
      alive = false;
    };
  }, [pathname, router]);

  if (!ready) return null;
  return <>{children}</>;
}

/** Initials for the profile circle: 'jane.smith@…' -> JS, 'janesmith@…' -> J. */
function initials(email: string): string {
  const parts = email.split("@")[0].split(/[._\-+]+/).filter(Boolean);
  return (parts.length > 1 ? parts[0][0] + parts[1][0] : (parts[0] || "?")[0]).toUpperCase();
}

/** The profile circle in the header: a click shows the signed-in email and Sign out. */
export function SignedInUser() {
  const router = useRouter();
  const pathname = usePathname();
  const [email, setEmail] = useState<string | null>(null);
  const [open, setOpen] = useState(false);
  const box = useRef<HTMLDivElement>(null);
  useEffect(() => {
    // eslint-disable-next-line react-hooks/set-state-in-effect -- the signed-in email is in browser storage, read after mounting and on each page change
    setEmail(signedInEmail());
    setOpen(false);
  }, [pathname]);
  useEffect(() => {
    if (!open) return;
    const away = (e: MouseEvent) => { if (box.current && !box.current.contains(e.target as Node)) setOpen(false); };
    const esc = (e: KeyboardEvent) => { if (e.key === "Escape") setOpen(false); };
    document.addEventListener("mousedown", away);
    document.addEventListener("keydown", esc);
    return () => {
      document.removeEventListener("mousedown", away);
      document.removeEventListener("keydown", esc);
    };
  }, [open]);
  if (!email || pathname === "/login") return null;
  return (
    <div ref={box} className="relative ml-2 border-l border-slate-200 pl-3">
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        aria-haspopup="menu"
        aria-expanded={open}
        title={email}
        className={`flex h-8 w-8 items-center justify-center rounded-full bg-teal-700 text-xs font-semibold text-white ring-offset-2 transition hover:bg-teal-800 ${open ? "ring-2 ring-teal-300" : ""}`}
      >
        {initials(email)}
      </button>
      {open && (
        <div role="menu" className="absolute right-0 top-10 z-50 w-60 overflow-hidden rounded-xl border border-slate-200 bg-white shadow-lg">
          <div className="flex items-center gap-3 border-b border-slate-100 px-4 py-3">
            <span className="flex h-9 w-9 shrink-0 items-center justify-center rounded-full bg-teal-700 text-xs font-semibold text-white">
              {initials(email)}
            </span>
            <div className="min-w-0">
              <p className="text-[11px] text-slate-500">Signed in as</p>
              <p className="truncate text-xs font-medium text-slate-900" title={email}>{email}</p>
            </div>
          </div>
          <button
            type="button"
            role="menuitem"
            onClick={async () => {
              setOpen(false);
              await signOut();
              router.replace("/login");
            }}
            className="flex w-full items-center gap-2 px-4 py-2.5 text-xs font-medium text-slate-700 transition hover:bg-rose-50 hover:text-rose-700"
          >
            <LogOut className="h-3.5 w-3.5" />
            Sign out
          </button>
        </div>
      )}
    </div>
  );
}

/** Hides its content on the sign-in page (the header menu). */
export function HideOnLogin({ children }: { children: React.ReactNode }) {
  return usePathname() === "/login" ? null : <>{children}</>;
}
