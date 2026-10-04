import { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import { AlertTriangle, CheckCircle2, Info, X, XCircle } from "lucide-react";
import { cn } from "@/shared/lib/cn";
import { Spinner } from "@/shared/ui/Spinner";

export type ToastKind = "success" | "error" | "warning" | "info" | "loading";

export interface ToastInput {
  /** Re-using an id UPDATES that toast in place (e.g. loading → success) instead of stacking a new one. */
  id?: string;
  kind: ToastKind;
  title: string;
  description?: string;
  action?: { label: string; onClick: () => void };
  /** ms; `loading` toasts are persistent until updated or dismissed. */
  durationMs?: number;
}

interface ToastItem extends ToastInput {
  id: string;
  leaving?: boolean;
}

interface ToastApi {
  show: (t: ToastInput) => string;
  dismiss: (id: string) => void;
  success: (title: string, description?: string) => string;
  error: (title: string, description?: string) => string;
  info: (title: string, description?: string) => string;
}

const ToastContext = createContext<ToastApi | null>(null);

const DEFAULT_MS: Record<ToastKind, number> = { success: 5000, info: 5000, warning: 8000, error: 9000, loading: 0 };
const EXIT_MS = 200;
const MAX_VISIBLE = 5;

const STYLE: Record<ToastKind, { icon: ReactNode; bar: string }> = {
  success: { icon: <CheckCircle2 className="h-5 w-5 text-st-accepted" />, bar: "bg-st-accepted" },
  error: { icon: <XCircle className="h-5 w-5 text-st-rejected" />, bar: "bg-st-rejected" },
  warning: { icon: <AlertTriangle className="h-5 w-5 text-st-progress" />, bar: "bg-st-progress" },
  info: { icon: <Info className="h-5 w-5 text-st-delivered" />, bar: "bg-st-delivered" },
  loading: { icon: <Spinner className="h-5 w-5 text-brand" />, bar: "bg-brand" },
};

export function ToastProvider({ children }: { children: ReactNode }) {
  const [toasts, setToasts] = useState<ToastItem[]>([]);
  const timers = useRef(new Map<string, number>());
  const seq = useRef(0);

  const clearTimer = (id: string) => {
    const t = timers.current.get(id);
    if (t) window.clearTimeout(t);
    timers.current.delete(id);
  };

  const dismiss = useCallback((id: string) => {
    clearTimer(id);
    setToasts((cur) => cur.map((t) => (t.id === id ? { ...t, leaving: true } : t)));
    window.setTimeout(() => setToasts((cur) => cur.filter((t) => t.id !== id)), EXIT_MS);
  }, []);

  const arm = useCallback(
    (id: string, ms: number) => {
      clearTimer(id);
      if (ms > 0) timers.current.set(id, window.setTimeout(() => dismiss(id), ms));
    },
    [dismiss],
  );

  const show = useCallback(
    (input: ToastInput) => {
      const id = input.id ?? `t${++seq.current}`;
      const item: ToastItem = { ...input, id };
      setToasts((cur) => {
        const exists = cur.some((t) => t.id === id);
        const next = exists ? cur.map((t) => (t.id === id ? item : t)) : [...cur, item];
        return next.slice(-MAX_VISIBLE);
      });
      arm(id, input.durationMs ?? DEFAULT_MS[input.kind]);
      return id;
    },
    [arm],
  );

  useEffect(() => {
    const live = timers.current;
    return () => live.forEach((t) => window.clearTimeout(t));
  }, []);

  const api = useMemo<ToastApi>(
    () => ({
      show,
      dismiss,
      success: (title, description) => show({ kind: "success", title, description }),
      error: (title, description) => show({ kind: "error", title, description }),
      info: (title, description) => show({ kind: "info", title, description }),
    }),
    [show, dismiss],
  );

  return (
    <ToastContext.Provider value={api}>
      {children}
      <div
        aria-live="polite"
        aria-relevant="additions text"
        className="pointer-events-none fixed inset-x-0 bottom-0 z-50 flex flex-col items-end gap-2.5 p-4 sm:p-6"
      >
        {toasts.map((t) => (
          <ToastCard key={t.id} toast={t} onDismiss={() => dismiss(t.id)} onPause={() => clearTimer(t.id)} onResume={() => arm(t.id, 2500)} />
        ))}
      </div>
    </ToastContext.Provider>
  );
}

function ToastCard({ toast: t, onDismiss, onPause, onResume }: { toast: ToastItem; onDismiss: () => void; onPause: () => void; onResume: () => void }) {
  const s = STYLE[t.kind];
  const persistent = t.kind === "loading";
  return (
    <div
      role={t.kind === "error" ? "alert" : "status"}
      onMouseEnter={persistent ? undefined : onPause}
      onMouseLeave={persistent ? undefined : onResume}
      className={cn(
        "pointer-events-auto relative w-full overflow-hidden rounded-xl border border-line bg-surface shadow-pop sm:w-[380px]",
        t.leaving ? "animate-toast-out" : "animate-toast-in",
      )}
    >
      <span className={cn("absolute inset-y-0 left-0 w-1", s.bar)} aria-hidden="true" />
      <div className="flex items-start gap-3 py-3.5 pl-5 pr-3">
        <span className="mt-0.5 shrink-0">{s.icon}</span>
        <div className="min-w-0 flex-1">
          <p className="text-sm font-semibold leading-snug">{t.title}</p>
          {t.description && <p className="mt-0.5 break-words text-[13px] leading-snug text-ink-soft">{t.description}</p>}
          {t.action && (
            <button
              onClick={() => {
                t.action?.onClick();
                onDismiss();
              }}
              className="mt-2 rounded-md text-[13px] font-semibold text-brand hover:text-brand-dark hover:underline"
            >
              {t.action.label}
            </button>
          )}
        </div>
        <button onClick={onDismiss} aria-label="Dismiss notification" className="shrink-0 rounded-md p-1 text-ink-mute hover:bg-ink/5">
          <X className="h-4 w-4" />
        </button>
      </div>
    </div>
  );
}

export function useToast(): ToastApi {
  const ctx = useContext(ToastContext);
  if (!ctx) throw new Error("useToast must be used inside <ToastProvider>");
  return ctx;
}
