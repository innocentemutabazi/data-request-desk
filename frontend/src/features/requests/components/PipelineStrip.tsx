import { ChevronRight } from "lucide-react";
import { cn } from "@/shared/lib/cn";
import { Skeleton } from "@/shared/ui/Skeleton";
import { PIPELINE, type RequestStatus, type StatusSummary } from "../types";
import { STATUS_LOOK } from "./StatusBadge";

interface Props {
  counts: StatusSummary | undefined;
  loading: boolean;
  active: RequestStatus | "all";
  onSelect: (s: RequestStatus | "all") => void;
}

/**
 * The state machine, drawn. Each stage shows how many requests sit in it and doubles as the list
 * filter. submitted → in progress → delivered are sequential; accepted / rejected are the two
 * alternative outcomes, so no connector is drawn between them.
 */
export function PipelineStrip({ counts, loading, active, onSelect }: Props) {
  return (
    <ol className="grid grid-cols-2 gap-2.5 sm:grid-cols-5" aria-label="Requests by lifecycle stage">
      {PIPELINE.map((status, i) => {
        const look = STATUS_LOOK[status];
        const selected = active === status;
        return (
          <li key={status} className="relative">
            <button
              type="button"
              aria-pressed={selected}
              onClick={() => onSelect(selected ? "all" : status)}
              className={cn(
                "w-full rounded-xl border border-t-[3px] bg-surface px-4 py-3 text-left shadow-card transition-all",
                look.bar,
                selected ? "border-brand ring-2 ring-brand/25" : "border-line hover:border-line-strong hover:shadow-md",
              )}
            >
              <span className={cn("text-xs font-medium", look.text)}>{look.label}</span>
              {loading || !counts ? (
                <Skeleton className="mt-2 h-7 w-10" />
              ) : (
                <span className="num mt-0.5 block text-[28px] font-semibold leading-tight">{counts[status]}</span>
              )}
            </button>
            {i < 3 && (
              <ChevronRight
                className="absolute -right-[11px] top-1/2 z-10 hidden h-4 w-4 -translate-y-1/2 rounded-full bg-canvas text-ink-mute sm:block"
                aria-hidden="true"
              />
            )}
          </li>
        );
      })}
    </ol>
  );
}
