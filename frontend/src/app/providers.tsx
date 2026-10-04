import { useState, type ReactNode } from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { BrowserRouter } from "react-router-dom";
import { AuthProvider } from "@/features/auth/AuthProvider";
import { ExportWatcherProvider } from "@/features/exports";
import { ApiError } from "@/shared/lib/api";
import { ToastProvider } from "@/shared/toast/ToastProvider";

function makeQueryClient() {
  return new QueryClient({
    defaultOptions: {
      queries: {
        staleTime: 15_000,
        refetchOnWindowFocus: true,
        // Retrying a 4xx can never succeed; only retry transient failures.
        retry: (count, err) => !(err instanceof ApiError && err.status >= 400 && err.status < 500) && count < 2,
      },
    },
  });
}

/** Order matters: Query + Toast are leaves of the tree that Auth and the export watcher both need. */
export function Providers({ children }: { children: ReactNode }) {
  const [client] = useState(makeQueryClient);
  return (
    <QueryClientProvider client={client}>
      <ToastProvider>
        <BrowserRouter>
          <AuthProvider>
            <ExportWatcherProvider>{children}</ExportWatcherProvider>
          </AuthProvider>
        </BrowserRouter>
      </ToastProvider>
    </QueryClientProvider>
  );
}
