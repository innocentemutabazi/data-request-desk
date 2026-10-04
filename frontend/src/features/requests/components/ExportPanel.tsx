import { RotateCw } from "lucide-react";
import { ExportStatusPill, useExportWatcher } from "@/features/exports";
import { errorMessage } from "@/shared/lib/api";
import { fmtDateTime } from "@/shared/lib/format";
import { Button } from "@/shared/ui/Button";
import { useToast } from "@/shared/toast/ToastProvider";
import { useRetryExport } from "../hooks";
import type { DatasetRequest } from "../types";

/** Operator-only view of the background export (the API never sends this to clients). */
export function ExportPanel({ request }: { request: DatasetRequest }) {
  const exp = request.export;
  const retry = useRetryExport(request.id);
  const watcher = useExportWatcher();
  const toast = useToast();
  if (!exp) return null;

  const explain: Record<typeof exp.status, string> = {
    not_started: "Starts automatically once every requested episode is assigned.",
    pending: "Queued — a background worker will pick it up in a moment.",
    running: "Packaging the assigned episodes…",
    succeeded: "The dataset bundle is built and ready.",
    failed: "All automatic attempts failed. Delivery is not blocked, but the bundle isn’t built.",
  };

  return (
    <section className="card p-5" aria-labelledby="export-h">
      <div className="mb-3 flex items-center justify-between gap-2">
        <h2 id="export-h" className="text-base font-semibold">Dataset export</h2>
        <ExportStatusPill info={exp} />
      </div>
      <p className="text-sm text-ink-soft">{explain[exp.status]}</p>
      <dl className="mt-3 space-y-1.5 text-sm">
        <div className="flex justify-between"><dt className="text-ink-mute">Attempts</dt><dd className="num font-medium">{exp.attempts} / {exp.max_attempts}</dd></div>
        <div className="flex justify-between"><dt className="text-ink-mute">Last update</dt><dd className="num">{fmtDateTime(exp.updated_at)}</dd></div>
      </dl>
      {exp.error && exp.status !== "succeeded" && (
        <p className="mt-3 rounded-lg bg-st-rejected-tint px-3 py-2 text-[13px] text-st-rejected" role="status">{exp.error}</p>
      )}
      {exp.status === "failed" && (
        <Button
          className="mt-4 w-full"
          variant="primary"
          loading={retry.isPending}
          onClick={() =>
            retry.mutate(undefined, {
              onSuccess: () => watcher.track(request.id, request.title),
              onError: (e) => toast.error("Couldn’t retry the export", errorMessage(e)),
            })
          }
        >
          <RotateCw className="h-4 w-4" /> Retry export
        </Button>
      )}
    </section>
  );
}
