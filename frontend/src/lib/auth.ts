/**
 * Sign-in: the server checks the email and password against its users table (passwords kept only as hashes) and
 * keeps the browser signed in with a session cookie (http-only, so the page itself cannot read it). Every other
 * call to the server needs that cookie and only reaches the signed-in user's own clients. The browser also keeps
 * the email, to show it in the header.
 */

import { getApiBaseUrl } from "@/lib/api";

const KEY = "ff_login";

export function signedInEmail(): string | null {
  try {
    const raw = window.localStorage.getItem(KEY);
    if (!raw) return null;
    const saved = JSON.parse(raw) as { email?: string };
    return saved.email || null;
  } catch {
    return null;
  }
}

/** Returns null when signed in, or the reason it failed. */
export async function signIn(email: string, password: string): Promise<string | null> {
  if (!email.trim() || !password) return "Enter your email and password.";
  let res: Response;
  try {
    res = await fetch(`${getApiBaseUrl()}/auth/login`, {
      method: "POST",
      credentials: "include",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ email: email.trim(), password }),
    });
  } catch {
    return "The server is not answering. Check it is running, then try again.";
  }
  if (!res.ok) {
    const detail = (await res.json().catch(() => ({}))).detail;
    return typeof detail === "string" ? detail : "Email or password is not right.";
  }
  const user = await res.json();
  try {
    window.localStorage.setItem(KEY, JSON.stringify({ email: user.email, name: user.name, at: new Date().toISOString() }));
  } catch {
    // private browsing: the sign-in lasts for this page only
  }
  return null;
}

export async function signOut(): Promise<void> {
  try {
    window.localStorage.removeItem(KEY);
  } catch {
    // nothing saved
  }
  await fetch(`${getApiBaseUrl()}/auth/logout`, { method: "POST", credentials: "include" }).catch(() => undefined);
}

/** The server's answer to "who is signed in" (null: nobody, or the session ended). */
export async function checkSession(): Promise<string | null> {
  try {
    const res = await fetch(`${getApiBaseUrl()}/auth/me`, { credentials: "include" });
    if (!res.ok) return null;
    const user = await res.json();
    try {
      window.localStorage.setItem(KEY, JSON.stringify({ email: user.email, name: user.name }));
    } catch {
      // private browsing
    }
    return user.email as string;
  } catch {
    return signedInEmail();      // server not answering: keep the page, its calls will say so
  }
}
