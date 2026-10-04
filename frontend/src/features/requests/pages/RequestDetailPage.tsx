import { useMemo } from "react";
import { Link, useParams } from "react-router-dom";
import { ArrowLeft, FileSearch, MessageSquareWarning } from "lucide-react";
import { useCurrentUser } from "@/features/auth/AuthProvider";
import { isStaff } from "@/features/auth/types";
import { EpisodeTable, useAssignedEpisodes } from "@/features/episodes";
import { ApiError, errorMessage } from "@/shared/lib/api";
import { CardSkeleton, Skeleton } from "@/shared/ui/Skeleton";
import { EmptyState, ErrorState } from "@/shared/ui/EmptyState";
import { LoadMore } from "@/shared/ui/LoadMore";
import { useRequest } from "../hooks";
import { AssignmentPanel } from "../components/AssignmentPanel";
import { BriefCard } from "../components/BriefCard";
import { EpisodeTape } from "../components/EpisodeTape";
import { ExportPanel } from "../components/ExportPanel";
import { Lifecycle } from "../components/Lifecycle";
import { StatusBadge } from "../components/StatusBadge";
import { TransitionActions } from "../components/TransitionActions";

export function RequestDetailPage() {
  const { id = "" } = useParams();
  const user = useCurrentUser();
  const staff = isStaff(user.role);
  const q = useRequest(id);
  const r = q.data;

  // Staff may always see assigned episodes; a client only after delivery (the API enforces it too).
  const canSeeEpisodes =
    !!r &&
    r.assigned_count > 0 &&
    (staff || r.status === "delivered" || r.status === "accepted");
  const assigned = useAssignedEpisodes(id, canSeeEpisodes);
  const assignedRows = useMemo(
    () => assigned.data?.pages.flatMap((p) => p.items) ?? [],
    [assigned.data],
  );

  const back = (
    <Link
      to={staff ? "/queue" : "/requests"}
      className="inline-flex items-center gap-1.5 text-sm text-ink-soft hover:text-ink"
    >
      <ArrowLeft className="h-4 w-4" /> {staff ? "Queue" : "My requests"}
    </Link>
  );

  if (q.isLoading) {
    return (
      <div className="space-y-6" aria-busy="true" aria-label="Loading request">
        {back}
        <div className="space-y-2">
          <Skeleton className="h-8 w-80" />
          <Skeleton className="h-4 w-48" />
        </div>
        <CardSkeleton lines={2} />
        <div className="grid gap-6 lg:grid-cols-[320px_1fr]">
          <CardSkeleton lines={5} />
          <CardSkeleton lines={8} />
        </div>
      </div>
    );
  }

  if (q.isError || !r) {
    const notFound = q.error instanceof ApiError && q.error.status === 404;
    return (
      <div className="space-y-6">
        {back}
        <div className="card">
          {notFound ? (
            <EmptyState
              icon={<FileSearch className="h-5 w-5" />}
              title="Request not found"
              hint="It may have been removed, or it belongs to another account."
            />
          ) : (
            <ErrorState
              message={errorMessage(q.error)}
              onRetry={() => void q.refetch()}
            />
          )}
        </div>
      </div>
    );
  }

  return (
    <div className="space-y-6">
      {back}

      <header className="flex flex-wrap items-start justify-between gap-4">
        <div className="min-w-0">
          <div className="flex flex-wrap items-center gap-3">
            <h1 className="text-2xl font-semibold">{r.title}</h1>
            <StatusBadge status={r.status} />
          </div>
          <p className="mt-1 font-mono text-xs text-ink-mute">{r.id}</p>
        </div>
        <TransitionActions request={r} />
      </header>

      {r.status === "rejected" && (
        <div
          role="status"
          className="flex gap-3 rounded-xl border border-st-rejected/25 bg-st-rejected-tint px-5 py-4"
        >
          <MessageSquareWarning className="mt-0.5 h-5 w-5 shrink-0 text-st-rejected" />
          <div>
            <p className="text-sm font-semibold text-st-rejected">
              Dataset rejected
            </p>
            <p className="mt-0.5 text-sm text-ink-soft">
              {r.decision_reason ?? "No reason was given."}
            </p>
            <p className="mt-1 text-[13px] text-ink-mute">
              The episodes were released back to the pool.
            </p>
          </div>
        </div>
      )}
      {!staff && r.status === "delivered" && (
        <div
          role="status"
          className="rounded-xl border border-st-delivered/25 bg-st-delivered-tint px-5 py-4 text-sm text-st-delivered"
        >
          <span className="font-semibold">
            Your dataset has been delivered.
          </span>{" "}
          Review the episodes below, then accept or reject it.
        </div>
      )}

      <section className="card p-5" aria-label="Progress">
        <Lifecycle request={r} />
        <div className="mt-5 border-t border-line pt-4">
          <div className="mb-2 flex items-baseline justify-between text-sm">
            <span className="font-medium">Episodes assigned</span>
            <span className="num text-ink-soft">
              <span className="font-semibold text-ink">{r.assigned_count}</span>{" "}
              / {r.episodes_requested}
            </span>
          </div>
          <EpisodeTape
            assigned={r.assigned_count}
            requested={r.episodes_requested}
          />
        </div>
      </section>

      <section className="card p-5" aria-labelledby="history-h">
        <h2 id="history-h" className="text-base font-semibold">
          Status history
        </h2>
        <ol className="mt-3 space-y-2 text-sm">
          {r.status_history.map((event, index) => (
            <li
              key={`${event.changed_at}-${index}`}
              className="flex flex-wrap gap-x-2 text-ink-soft"
            >
              <span className="font-medium text-ink">
                {event.to_status.replace("_", " ")}
              </span>
              <span>{new Date(event.changed_at).toLocaleString()}</span>
              {event.reason && <span>· {event.reason}</span>}
            </li>
          ))}
        </ol>
      </section>

      <div className="grid items-start gap-6 lg:grid-cols-[320px_minmax(0,1fr)]">
        <div className="space-y-6">
          <BriefCard request={r} />
          {staff && <ExportPanel request={r} />}
        </div>

        <div className="min-w-0 space-y-6">
          {staff && r.status === "in_progress" && (
            <AssignmentPanel request={r} />
          )}

          {canSeeEpisodes && (
            <section
              className="card overflow-hidden"
              aria-labelledby="assigned-h"
            >
              <div className="flex items-center justify-between px-5 py-4">
                <h2 id="assigned-h" className="text-base font-semibold">
                  {staff ? "Assigned episodes" : "Your episodes"}
                </h2>
                <span className="num text-sm text-ink-mute">
                  {r.assigned_count}
                </span>
              </div>
              {assigned.isError ? (
                <ErrorState
                  message={errorMessage(assigned.error)}
                  onRetry={() => void assigned.refetch()}
                />
              ) : (
                <>
                  <EpisodeTable
                    rows={assignedRows}
                    loading={assigned.isLoading}
                  />
                  {assignedRows.length > 0 && (
                    <LoadMore
                      hasMore={!!assigned.hasNextPage}
                      loading={assigned.isFetchingNextPage}
                      onLoad={() => void assigned.fetchNextPage()}
                      shown={assignedRows.length}
                      noun="episodes"
                    />
                  )}
                </>
              )}
            </section>
          )}

          {!canSeeEpisodes && !(staff && r.status === "in_progress") && (
            <section className="card">
              <EmptyState
                title={
                  staff
                    ? "No episodes assigned"
                    : "Episodes appear here once delivered"
                }
                hint={
                  staff
                    ? "Start work on the request, then assign matching episodes."
                    : "An operator is matching episodes to your brief. You’ll be able to review them as soon as the dataset is delivered."
                }
              />
            </section>
          )}
        </div>
      </div>
    </div>
  );
}
