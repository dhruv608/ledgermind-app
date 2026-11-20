"use client";

import { useState } from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";

/** The app's shared data store: each job's data is asked for once, shared by every screen that shows it, and asked for
 *  again only when an action changes it (see lib/queries/job.ts). */
export function QueryProvider({ children }: { children: React.ReactNode }) {
  const [client] = useState(() => new QueryClient({
    defaultOptions: {
      queries: {
        staleTime: 60_000,             // fresh for a minute: moving between screens does not ask again
        refetchOnWindowFocus: false,   // a working paper does not reload under the accountant
        retry: 1,
      },
    },
  }));
  return <QueryClientProvider client={client}>{children}</QueryClientProvider>;
}
