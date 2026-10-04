import { useMemo, useState } from "react";
import { useNavigate, useSearchParams } from "react-router-dom";
import { ArrowRight, Inbox, Plus } from "lucide-react";
import { Button } from "@/shared/ui/Button";
import { EmptyState, ErrorState } from "@/shared/ui/EmptyState";
import { LoadMore } from "@/shared/ui/LoadMore";
import { errorMessage } from "@/shared/lib/api";
import { useRequestsInfinite, useRequestSummary } from "../hooks";
import { NewRequestDialog } from "../components/NewRequestDialog";
import { PipelineStrip } from "../components/PipelineStrip";
import { RequestsTable } from "../components/RequestsTable";
import type { RequestStatus } from "../types";

export function ClientDashboard() {
  const navigate = useNavigate();
  const [params, setParams] = useSearchParams();
  const active = (params.get("status") as RequestStatus | null) ?? "all";
  const [creating, setCreating] = useState(false);

  const summary = useRequestSummary();
  const list = useRequestsInfinite(active === "all" ? {} : { status: [active] });
  const rows = useMemo(() => list.data?.pages.flatMap((p) => p.items) ?? [], [list.data]);
  const awaiting = summary.data?.delivered ?? 0;

  const select = (s: RequestStatus | "all") => setParams(s === "all" ? {} : { status: s }, { replace: true });

  return (
    <div className="space-y-6">
      <header className="flex flex-wrap items-end justify-between gap-4">
        <div>
          <h1 className="text-2xl font-semibold">My dataset requests</h1>
          <p className="mt-1 text-sm text-ink-soft">Track each request from submission to delivery.</p>
        </div>
        <Button variant="primary" onClick={() => setCreating(true)}>
          <Plus className="h-4 w-4" /> New request
        </Button>
      </header>

      {awaiting > 0 && (
        <div role="status" className="flex flex-wrap items-center justify-between gap-3 rounded-xl border border-st-delivered/25 bg-st-delivered-tint px-5 py-3.5">
          <p className="text-sm font-medium text-st-delivered">
            {awaiting} dataset{awaiting === 1 ? " is" : "s are"} waiting for your decision.
          </p>
          <Button size="sm" variant="secondary" onClick={() => select("delivered")}>
            Review <ArrowRight className="h-3.5 w-3.5" />
          </Button>
        </div>
      )}

      <PipelineStrip counts={summary.data} loading={summary.isLoading} active={active} onSelect={select} />

      <section className="card overflow-hidden" aria-label="Requests">
        {list.isError ? (
          <ErrorState message={errorMessage(list.error)} onRetry={() => void list.refetch()} />
        ) : (
          <>
            <RequestsTable
              variant="client"
              rows={rows}
              loading={list.isLoading}
              empty={
                <EmptyState
                  icon={<Inbox className="h-5 w-5" />}
                  title={active === "all" ? "No requests yet" : "Nothing in this stage"}
                  hint={active === "all" ? "Describe the robot demonstrations you need and an operator will match episodes to your brief." : "Pick another stage above, or clear the filter."}
                  action={
                    active === "all" ? (
                      <Button variant="primary" onClick={() => setCreating(true)}><Plus className="h-4 w-4" /> Create your first request</Button>
                    ) : (
                      <Button onClick={() => select("all")}>Show all</Button>
                    )
                  }
                />
              }
            />
            {rows.length > 0 && <LoadMore hasMore={!!list.hasNextPage} loading={list.isFetchingNextPage} onLoad={() => void list.fetchNextPage()} shown={rows.length} noun="requests" />}
          </>
        )}
      </section>

      <NewRequestDialog open={creating} onClose={() => setCreating(false)} onCreated={(r) => { setCreating(false); navigate(`/requests/${r.id}`); }} />
    </div>
  );
}
