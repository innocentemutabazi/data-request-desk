import { Check, X } from "lucide-react";
import { cn } from "@/shared/lib/cn";
import { fmtDateTime } from "@/shared/lib/format";
import type { DatasetRequest } from "../types";

/** Horizontal stepper for one request: where it is, and when it got there. */
export function Lifecycle({ request: r }: { request: DatasetRequest }) {
  const finalStep = r.status === "rejected" ? "rejected" : "accepted";
  const steps = [
    { key: "submitted", label: "Submitted", at: r.created_at, reached: true },
    { key: "in_progress", label: "In progress", at: r.started_at, reached: !!r.started_at },
    { key: "delivered", label: "Delivered", at: r.delivered_at, reached: !!r.delivered_at },
    { key: finalStep, label: finalStep === "rejected" ? "Rejected" : "Accepted", at: r.decided_at, reached: !!r.decided_at },
  ];
  const current = steps.reduce((last, s, i) => (s.reached ? i : last), 0); // index of the furthest reached step

  return (
    <ol className="grid grid-cols-2 gap-y-4 sm:grid-cols-4" aria-label="Request lifecycle">
      {steps.map((s, i) => {
        const bad = s.key === "rejected" && s.reached;
        return (
          <li key={s.key} className="relative flex items-start gap-3 sm:block">
            <div className="flex items-center sm:mb-2">
              <span
                className={cn(
                  "grid h-7 w-7 shrink-0 place-items-center rounded-full border-2 text-xs font-semibold",
                  bad ? "border-st-rejected bg-st-rejected text-white" : s.reached ? (i === current && i < 3 ? "border-brand bg-surface text-brand" : "border-brand bg-brand text-white") : "border-line-strong bg-surface text-ink-mute",
                )}
                aria-current={i === current ? "step" : undefined}
              >
                {bad ? <X className="h-3.5 w-3.5" /> : s.reached && !(i === current && i < 3) ? <Check className="h-3.5 w-3.5" /> : i + 1}
              </span>
              {i < steps.length - 1 && <span className={cn("ml-2 hidden h-0.5 flex-1 rounded sm:block", i < current ? "bg-brand" : "bg-line")} aria-hidden="true" />}
            </div>
            <div>
              <p className={cn("text-sm font-medium", !s.reached && "text-ink-mute")}>{s.label}</p>
              <p className="num text-xs text-ink-mute">{s.reached ? fmtDateTime(s.at) : "—"}</p>
            </div>
          </li>
        );
      })}
    </ol>
  );
}
