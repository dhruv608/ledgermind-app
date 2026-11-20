"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import type { ReactNode } from "react";
import { cn } from "@/lib/utils";

/** A link in the top bar: teal while its page is open. The icon comes as an element: the top bar is drawn on the
 *  server, which can not pass a component. */
export function NavLink({ href, label, icon }: { href: string; label: string; icon: ReactNode }) {
  const pathname = usePathname();
  const active = pathname === href || pathname.startsWith(`${href}/`);
  return (
    <Link
      href={href}
      title={label}
      aria-current={active ? "page" : undefined}
      className={cn(
        "inline-flex items-center gap-1.5 whitespace-nowrap rounded-lg px-2.5 py-1.5 font-medium transition",
        active ? "bg-teal-50 text-teal-800" : "text-slate-600 hover:bg-slate-100 hover:text-slate-900"
      )}
    >
      {icon}
      <span className="hidden md:inline">{label}</span>
    </Link>
  );
}
