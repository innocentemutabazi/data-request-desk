import { cn } from "@/shared/lib/cn";
import type { RequestStatus } from "../types";

// Full class names (not interpolated) so Tailwind's scanner can see them.
export const STATUS_LOOK: Record<RequestStatus, { label: string; badge: string; dot: string; bar: string; text: string }> = {
  submitted: { label: "Submitted", badge: "bg-st-submitted-tint text-st-submitted", dot: "bg-st-submitted", bar: "border-t-st-submitted", text: "text-st-submitted" },
  in_progress: { label: "In progress", badge: "bg-st-progress-tint text-st-progress", dot: "bg-st-progress", bar: "border-t-st-progress", text: "text-st-progress" },
  delivered: { label: "Delivered", badge: "bg-st-delivered-tint text-st-delivered", dot: "bg-st-delivered", bar: "border-t-st-delivered", text: "text-st-delivered" },
  accepted: { label: "Accepted", badge: "bg-st-accepted-tint text-st-accepted", dot: "bg-st-accepted", bar: "border-t-st-accepted", text: "text-st-accepted" },
  rejected: { label: "Rejected", badge: "bg-st-rejected-tint text-st-rejected", dot: "bg-st-rejected", bar: "border-t-st-rejected", text: "text-st-rejected" },
};

export function StatusBadge({ status, className }: { status: RequestStatus; className?: string }) {
  const look = STATUS_LOOK[status];
  return (
    <span className={cn("inline-flex items-center gap-1.5 rounded-full px-2.5 py-1 text-xs font-medium", look.badge, className)}>
      <span className={cn("h-1.5 w-1.5 rounded-full", look.dot)} aria-hidden="true" />
      {look.label}
    </span>
  );
}
