import { cn } from "@/shared/lib/cn";
import type { Quality } from "@/features/requests/types";

const LOOK: Record<Quality, string> = {
  good: "bg-st-accepted",
  usable: "bg-st-progress",
  bad: "bg-st-rejected",
};

export function QualityBadge({ quality }: { quality: Quality }) {
  return (
    <span className="inline-flex items-center gap-1.5 text-sm capitalize">
      <span className={cn("h-2 w-2 rounded-full", LOOK[quality])} aria-hidden="true" />
      {quality}
    </span>
  );
}
