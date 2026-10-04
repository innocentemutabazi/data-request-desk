import { useMemo, useState } from "react";
import { Sparkles, Layers } from "lucide-react";
import { EpisodeTable, useCandidates } from "@/features/episodes";
import { useExportWatcher } from "@/features/exports";
import { ApiError, errorMessage } from "@/shared/lib/api";
import { Button } from "@/shared/ui/Button";
import { EmptyState, ErrorState } from "@/shared/ui/EmptyState";
import { LoadMore } from "@/shared/ui/LoadMore";
import { useToast } from "@/shared/toast/ToastProvider";
import { useAssign } from "../hooks";
import type { AssignmentResult, DatasetRequest } from "../types";
import { EpisodeTape } from "./EpisodeTape";

/** Operator workspace while a request is in progress: fill the quota, by hand or automatically. */
export function AssignmentPanel({ request }: { request: DatasetRequest }) {
  const toast = useToast();
  const watcher = useExportWatcher();
  const assign = useAssign(request.id);
  const candidates = useCandidates(request.id, true);
  const [selected, setSelected] = useState<ReadonlySet<string>>(new Set());

  const remaining = request.episodes_requested - request.assigned_count;
  const rows = useMemo(() => candidates.data?.pages.flatMap((p) => p.items) ?? [], [candidates.data]);

  const onSuccess = (res: AssignmentResult) => {
    setSelected(new Set());
    const n = res.assigned_episode_ids.length;
    toast.success(
      `Assigned ${n} episode${n === 1 ? "" : "s"}`,
      res.fully_assigned ? "The request is fully assigned and ready to deliver." : `${res.request.episodes_requested - res.request.assigned_count} still to go.`,
    );
    if (res.export_scheduled) watcher.track(request.id, request.title); // → toasts the background export's outcome
  };

  const onError = (e: unknown) => {
    // Another operator won the race for some of these episodes: say so precisely, drop them from the selection.
    if (e instanceof ApiError && e.code === "episodes_already_assigned") {
      const taken = new Set((e.details.episode_ids as string[] | undefined) ?? []);
      setSelected((cur) => new Set([...cur].filter((id) => !taken.has(id))));
      toast.error("Someone else claimed those episodes", `${taken.size || "Some"} episode(s) were just assigned to another request. The list has been refreshed.`);
      void candidates.refetch();
      return;
    }
    toast.error("Assignment failed", errorMessage(e));
  };

  const toggle = (id: string) =>
    setSelected((cur) => {
      const next = new Set(cur);
      if (next.has(id)) next.delete(id);
      else if (next.size < remaining) next.add(id);
      return next;
    });

  const done = remaining <= 0;

  return (
    <section className="card overflow-hidden" aria-labelledby="assign-h">
      <div className="space-y-4 p-5">
        <div className="flex flex-wrap items-end justify-between gap-3">
          <div>
            <h2 id="assign-h" className="text-base font-semibold">Assign episodes</h2>
            <p className="text-sm text-ink-soft">
              <span className="num font-medium text-ink">{request.assigned_count}</span> of <span className="num">{request.episodes_requested}</span> assigned
              {!done && <> · <span className="num">{remaining}</span> to go</>}
            </p>
          </div>
          <div className="flex flex-wrap gap-2">
            <Button
              variant="secondary"
              disabled={done || selected.size === 0}
              loading={assign.isPending && "episodeIds" in (assign.variables ?? {})}
              onClick={() => assign.mutate({ episodeIds: [...selected] }, { onSuccess, onError })}
            >
              <Layers className="h-4 w-4" /> Assign selected{selected.size ? ` (${selected.size})` : ""}
            </Button>
            <Button
              variant="primary"
              disabled={done}
              loading={assign.isPending && "auto" in (assign.variables ?? {})}
              onClick={() => assign.mutate({ auto: true }, { onSuccess, onError })}
              title="Picks the best-quality, newest unassigned matches"
            >
              <Sparkles className="h-4 w-4" /> Auto-assign {done ? "" : `remaining (${remaining})`}
            </Button>
          </div>
        </div>
        <EpisodeTape assigned={request.assigned_count} requested={request.episodes_requested} />
      </div>

      <div className="border-t border-line bg-sunken/50 px-5 py-2.5 text-xs font-medium text-ink-mute">
        Available matches · {request.task_name}
        {request.min_quality && ` · ${request.min_quality}+`}
      </div>

      {candidates.isError ? (
        <ErrorState message={errorMessage(candidates.error)} onRetry={() => void candidates.refetch()} />
      ) : (
        <>
          <EpisodeTable
            rows={rows}
            loading={candidates.isLoading}
            selection={done ? undefined : { selected, onToggle: toggle, limit: remaining }}
            empty={<EmptyState title="No unassigned episodes match this brief" hint="Everything that fits is already assigned to other requests, or the date window is too narrow." />}
          />
          {rows.length > 0 && (
            <LoadMore hasMore={!!candidates.hasNextPage} loading={candidates.isFetchingNextPage} onLoad={() => void candidates.fetchNextPage()} shown={rows.length} noun="episodes" />
          )}
        </>
      )}
    </section>
  );
}
