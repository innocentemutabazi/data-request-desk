import { CheckCircle2, CircleDashed, Clock, XCircle } from "lucide-react";
import { cn } from "@/shared/lib/cn";
import { Spinner } from "@/shared/ui/Spinner";
import type { ExportInfo } from "@/features/requests/types";

const LOOK: Record<ExportInfo["status"], { label: string; cls: string }> = {
  not_started: { label: "Export not started", cls: "bg-sunken text-ink-mute" },
  pending: { label: "Export queued", cls: "bg-st-progress-tint text-st-progress" },
  running: { label: "Exporting", cls: "bg-st-progress-tint text-st-progress" },
  succeeded: { label: "Export ready", cls: "bg-st-accepted-tint text-st-accepted" },
  failed: { label: "Export failed", cls: "bg-st-rejected-tint text-st-rejected" },
};

export function ExportStatusPill({ info, compact }: { info: ExportInfo | null; compact?: boolean }) {
  if (!info) return null;
  const look = LOOK[info.status];
  const retrying = info.status === "running" && info.attempts > 1;
  const icon =
    info.status === "running" ? <Spinner className="h-3.5 w-3.5" /> :
    info.status === "pending" ? <Clock className="h-3.5 w-3.5" /> :
    info.status === "succeeded" ? <CheckCircle2 className="h-3.5 w-3.5" /> :
    info.status === "failed" ? <XCircle className="h-3.5 w-3.5" /> :
    <CircleDashed className="h-3.5 w-3.5" />;
  return (
    <span className={cn("inline-flex items-center gap-1.5 rounded-full px-2.5 py-1 text-xs font-medium", look.cls)}>
      {icon}
      {compact ? look.label.replace("Export ", "") : look.label}
      {retrying && <span className="num opacity-80">· attempt {info.attempts}/{info.max_attempts}</span>}
    </span>
  );
}
