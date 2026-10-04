import { useState } from "react";
import { CheckCircle2, PackageCheck, Play, ThumbsDown } from "lucide-react";
import { errorMessage } from "@/shared/lib/api";
import { Button } from "@/shared/ui/Button";
import { Dialog } from "@/shared/ui/Dialog";
import { Field } from "@/shared/ui/Field";
import { useToast } from "@/shared/toast/ToastProvider";
import { useReject, useTransition } from "../hooks";
import type { DatasetRequest } from "../types";

/**
 * Buttons are derived from `available_transitions` (the server's state machine, filtered by the
 * caller's role) - the UI never re-implements who may do what. The one data-dependent guard
 * (deliver needs a full assignment) is explained inline instead of failing with a 409.
 */
export function TransitionActions({ request: r }: { request: DatasetRequest }) {
  const toast = useToast();
  const move = useTransition(r.id);
  const reject = useReject(r.id);
  const [rejecting, setRejecting] = useState(false);
  const [reason, setReason] = useState("");
  const can = (s: DatasetRequest["status"]) =>
    r.available_transitions.includes(s);

  const run = (
    action: "start" | "deliver" | "accept" | "rework",
    ok: string,
    detail?: string,
  ) =>
    move.mutate(action, {
      onSuccess: () => toast.success(ok, detail),
      onError: (e) => toast.error("Action failed", errorMessage(e)),
    });

  const missing = r.episodes_requested - r.assigned_count;

  return (
    <div className="flex flex-col items-start gap-2 sm:items-end">
      <div className="flex flex-wrap gap-2">
        {can("in_progress") && (
          <Button
            variant="primary"
            loading={move.isPending}
            onClick={() =>
              run(
                r.status === "rejected" ? "rework" : "start",
                r.status === "rejected" ? "Rework started" : "Work started",
                "You can now assign episodes.",
              )
            }
          >
            <Play className="h-4 w-4" /> Start work
          </Button>
        )}
        {can("delivered") && (
          <Button
            variant="primary"
            disabled={missing > 0}
            loading={move.isPending}
            onClick={() =>
              run(
                "deliver",
                "Delivered",
                "The client can now review the dataset.",
              )
            }
          >
            <PackageCheck className="h-4 w-4" /> Mark delivered
          </Button>
        )}
        {can("accepted") && (
          <Button
            variant="primary"
            loading={move.isPending}
            onClick={() =>
              run(
                "accept",
                "Dataset accepted",
                "Thanks — the episodes are yours.",
              )
            }
          >
            <CheckCircle2 className="h-4 w-4" /> Accept dataset
          </Button>
        )}
        {can("rejected") && (
          <Button
            variant="secondary"
            className="text-st-rejected"
            onClick={() => setRejecting(true)}
          >
            <ThumbsDown className="h-4 w-4" /> Reject…
          </Button>
        )}
      </div>
      {can("delivered") && missing > 0 && (
        <p className="text-[13px] text-ink-mute">
          Assign <span className="num font-medium text-ink">{missing}</span>{" "}
          more episode{missing === 1 ? "" : "s"} to deliver.
        </p>
      )}

      <Dialog
        open={rejecting}
        onClose={() => setRejecting(false)}
        title="Reject this dataset?"
        description="The episodes are released back to the pool. This can’t be undone."
        footer={
          <>
            <Button variant="ghost" onClick={() => setRejecting(false)}>
              Keep reviewing
            </Button>
            <Button
              variant="danger"
              loading={reject.isPending}
              onClick={() =>
                reject.mutate(reason.trim() || undefined, {
                  onSuccess: () => {
                    setRejecting(false);
                    setReason("");
                    toast.info(
                      "Dataset rejected",
                      "The operator will see your feedback.",
                    );
                  },
                  onError: (e) =>
                    toast.error("Couldn’t reject", errorMessage(e)),
                })
              }
            >
              Reject dataset
            </Button>
          </>
        }
      >
        <Field
          label="What was wrong?"
          hint="Optional, but it helps the operator fix it."
        >
          {(id) => (
            <textarea
              id={id}
              data-autofocus
              rows={4}
              maxLength={1000}
              value={reason}
              onChange={(e) => setReason(e.target.value)}
              className="w-full rounded-lg border border-line-strong p-3 text-sm focus:border-brand focus:outline-none focus:ring-2 focus:ring-brand/20"
              placeholder="e.g. Lighting too dim in most episodes"
            />
          )}
        </Field>
      </Dialog>
    </div>
  );
}
