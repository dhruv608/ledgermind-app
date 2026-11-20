import type { Metadata } from "next";
import Link from "next/link";
import { Toaster } from "sonner";
import { CircleHelp, ListFilter, Settings2 } from "lucide-react";
import { NavLink } from "@/components/common/NavLink";
import { AuthGate, HideOnLogin, SignedInUser } from "@/components/auth/AuthGate";
import { AssistantPanel } from "@/components/assistant/AssistantPanel";
import { QueryProvider } from "@/components/common/QueryProvider";
import "./globals.css";

export const metadata: Metadata = {
  title: "LedgerMind",
  description: "UK year-end working papers: mapping, review checks, VAT, corporation tax and the Excel workbook.",
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="en" className="h-full bg-slate-50 text-slate-900 antialiased">
      <body className="min-h-screen flex flex-col font-sans bg-slate-50 text-slate-900">
        <Toaster
          position="top-right"
          richColors
          closeButton
          duration={4000}
          toastOptions={{
            style: {
              background: "#ffffff",
              color: "#0f172a",
              border: "1px solid #e2e8f0",
              boxShadow: "0 10px 25px -5px rgba(0, 0, 0, 0.08), 0 8px 10px -6px rgba(0, 0, 0, 0.05)",
              borderRadius: "0.75rem",
              padding: "14px 16px",
            },
          }}
        />
        {/* Top App Bar */}
        <header className="sticky top-0 z-40 border-b border-slate-200 bg-white/90 backdrop-blur">
          <div className="mx-auto flex h-14 max-w-[100rem] items-center justify-between px-4 sm:px-6 lg:px-8">
            <Link href="/" className="flex items-center gap-2.5 transition hover:opacity-90">
              {/* eslint-disable-next-line @next/next/no-img-element */}
              <img src="/logo.png" alt="" width={32} height={32} className="h-8 w-8" />
              <div className="leading-tight">
                <span className="block text-sm font-bold tracking-tight text-slate-900">LedgerMind</span>
                <span className="hidden whitespace-nowrap text-[11px] text-slate-500 sm:block">Year-end working papers</span>
              </div>
            </Link>

            <HideOnLogin>
            <nav className="flex items-center gap-0.5 text-xs">
              <NavLink href="/rules" label="Mapping" icon={<ListFilter className="h-3.5 w-3.5" />} />
              <NavLink href="/firm-settings" label="Firm settings" icon={<Settings2 className="h-3.5 w-3.5" />} />
              <NavLink href="/guide" label="Guide" icon={<CircleHelp className="h-3.5 w-3.5" />} />
              <SignedInUser />
            </nav>
            </HideOnLogin>
          </div>
        </header>

        <QueryProvider>
        {/* Main Content Area */}
        <main className="flex-1 max-w-[100rem] w-full mx-auto px-4 sm:px-6 lg:px-8 py-6">
          <AuthGate>{children}</AuthGate>
        </main>

        <footer className="border-t border-slate-200 bg-white py-4 text-center text-[11px] text-slate-400">
          LedgerMind · UK year-end working papers
        </footer>
        <AssistantPanel />
        </QueryProvider>
      </body>
    </html>
  );
}
