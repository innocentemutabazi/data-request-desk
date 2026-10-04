import { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { useNavigate } from "react-router-dom";
import { getRequest, listRequests, retryExport } from "@/features/requests/api";
import type { DatasetRequest, ExportStatus } from "@/features/requests/types";
import { errorMessage } from "@/shared/lib/api";
import { useToast } from "@/shared/toast/ToastProvider";
import { useAuth } from "@/features/auth/AuthProvider";
import { isStaff } from "@/features/auth/types";

/**
 * Watches in-flight background exports and reports their outcome through toasts.
 *
 *  - One persistent "Exporting…" toast per request, keyed by id, MORPHS in place into success / failure
 *    (no pile of stacked notifications).
 *  - Polls only while something is tracked, never overlaps ticks, and stops itself when idle.
 *  - Surfaces automatic retries ("attempt 2/3"), and offers one-click Retry when it finally fails.
 *  - On sign-in / page reload it re-attaches to exports that are still running server-side.
 */
interface Watcher {
  track: (requestId: string, title: string) => void;
}
const WatcherContext = createContext<Watcher>({ track: () => undefined });
export const useExportWatcher = () => useContext(WatcherContext);

interface Tracked {
  title: string;
  lastAttempts: number;
}
const POLL_MS = 1500;
const toastId = (id: string) => `export:${id}`;
const IN_FLIGHT: ExportStatus[] = ["pending", "running"];
const TERMINAL: ExportStatus[] = ["succeeded", "failed"];

export function ExportWatcherProvider({ children }: { children: ReactNode }) {
  const toast = useToast();
  const qc = useQueryClient();
  const navigate = useNavigate();
  const { user } = useAuth();
  const tracked = useRef(new Map<string, Tracked>());
  const [size, setSize] = useState(0);
  const polling = useRef(false);

  const track = useCallback(
    (id: string, title: string) => {
      if (tracked.current.has(id)) return;
      tracked.current.set(id, { title, lastAttempts: 0 });
      setSize(tracked.current.size);
      toast.show({ id: toastId(id), kind: "loading", title: `Exporting “${title}”`, description: "Packaging the assigned episodes…" });
    },
    [toast],
  );

  const settle = useCallback(
    (req: DatasetRequest, entry: Tracked) => {
      const exp = req.export;
      if (!exp) return;
      const id = req.id;
      if (exp.status === "succeeded") {
        toast.show({
          id: toastId(id),
          kind: "success",
          title: `Export ready · “${entry.title}”`,
          description: exp.attempts > 1 ? `Succeeded after ${exp.attempts} attempts.` : "The dataset is packaged and ready to deliver.",
          action: { label: "Open request", onClick: () => navigate(`/requests/${id}`) },
        });
      } else if (exp.status === "failed") {
        toast.show({
          id: toastId(id),
          kind: "error",
          title: `Export failed · “${entry.title}”`,
          description: exp.error ?? "The export could not be completed.",
          action: {
            label: "Retry export",
            onClick: () =>
              retryExport(id)
                .then((r) => {
                  qc.setQueryData(["requests", "detail", id], r);
                  track(id, entry.title);
                })
                .catch((e) => toast.error("Retry failed", errorMessage(e))),
          },
          durationMs: 15_000,
        });
      }
      tracked.current.delete(id);
      setSize(tracked.current.size);
      qc.setQueryData(["requests", "detail", id], req);
      void qc.invalidateQueries({ queryKey: ["requests", "list"] });
    },
    [toast, navigate, qc, track],
  );

  // Poll only while there is something to watch.
  useEffect(() => {
    if (size === 0) return;
    const tick = async () => {
      if (polling.current) return;
      polling.current = true;
      try {
        await Promise.all(
          [...tracked.current.entries()].map(async ([id, entry]) => {
            try {
              const req = await getRequest(id);
              const exp = req.export;
              // Anything that is not a terminal state means "keep watching" - never drop a loading toast early.
              if (!exp || !TERMINAL.includes(exp.status)) {
                if (exp && exp.attempts > entry.lastAttempts) {
                  if (exp.attempts > 1 && exp.error) {
                    toast.show({
                      id: toastId(id),
                      kind: "loading",
                      title: `Retrying export · “${entry.title}”`,
                      description: `Attempt ${exp.attempts} of ${exp.max_attempts}. ${exp.error}`,
                    });
                  }
                  entry.lastAttempts = exp.attempts;
                }
                void qc.setQueryData(["requests", "detail", id], req);
                return;
              }
              settle(req, entry);
            } catch {
              /* transient network error: keep watching, try again next tick */
            }
          }),
        );
      } finally {
        polling.current = false;
      }
    };
    const handle = window.setInterval(() => void tick(), POLL_MS);
    return () => window.clearInterval(handle);
  }, [size, settle, toast, qc]);

  // Re-attach to exports still running server-side (page reload, second tab, another operator).
  useEffect(() => {
    if (!isStaff(user?.role)) return;
    let cancelled = false;
    listRequests({ export_status: IN_FLIGHT }, null, 50)
      .then((page) => !cancelled && page.items.forEach((r) => track(r.id, r.title)))
      .catch(() => undefined);
    return () => {
      cancelled = true;
    };
  }, [user?.id, user?.role, track]);

  const value = useMemo(() => ({ track }), [track]);
  return <WatcherContext.Provider value={value}>{children}</WatcherContext.Provider>;
}
