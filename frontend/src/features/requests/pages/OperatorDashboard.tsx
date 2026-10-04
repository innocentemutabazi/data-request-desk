import { useMemo, useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { useSearchParams } from "react-router-dom";
import { Inbox } from "lucide-react";
import { errorMessage } from "@/shared/lib/api";
import { EmptyState, ErrorState } from "@/shared/ui/EmptyState";
import { LoadMore } from "@/shared/ui/LoadMore";
import { useToast } from "@/shared/toast/ToastProvider";
import { transition } from "../api";
import { requestKeys, useRequestsInfinite, useRequestSummary } from "../hooks";
import { PipelineStrip } from "../components/PipelineStrip";
import { RequestsTable } from "../components/RequestsTable";
import type { DatasetRequest, RequestStatus } from "../types";

export function OperatorDashboard() {
  const [params, setParams] = useSearchParams();
  const active = (params.get("status") as RequestStatus | null) ?? "all";
  const toast = useToast();
  const qc = useQueryClient();
  const [startingId, setStartingId] = useState<string | null>(null);

  const summary = useRequestSummary();
  const list = useRequestsInfinite(active === "all" ? {} : { status: [active] });
  const rows = useMemo(() => list.data?.pages.flatMap((p) => p.items) ?? [], [list.data]);

  const select = (s: RequestStatus | "all") => setParams(s === "all" ? {} : { status: s }, { replace: true });

  // Quick-start straight from the queue (the same endpoint the detail page uses).
  const start = (r: DatasetRequest) => {
    setStartingId(r.id);
    transition(r.id, "start")
      .then((fresh) => {
        qc.setQueryData(requestKeys.detail(r.id), fresh);
        void qc.invalidateQueries({ queryKey: ["requests", "list"] });
        void qc.invalidateQueries({ queryKey: requestKeys.summary });
        toast.success("Work started", `“${r.title}” is now in progress.`);
      })
      .catch((e) => toast.error("Couldn’t start", errorMessage(e)))
      .finally(() => setStartingId(null));
  };

  return (
    <div className="space-y-6">
      <header>
        <h1 className="text-2xl font-semibold">Request queue</h1>
        <p className="mt-1 text-sm text-ink-soft">Everything moving through the desk, newest first.</p>
      </header>

      <PipelineStrip counts={summary.data} loading={summary.isLoading} active={active} onSelect={select} />

      <section className="card overflow-hidden" aria-label="Requests">
        {list.isError ? (
          <ErrorState message={errorMessage(list.error)} onRetry={() => void list.refetch()} />
        ) : (
          <>
            <RequestsTable
              variant="staff"
              rows={rows}
              loading={list.isLoading}
              onStart={start}
              startingId={startingId}
              empty={<EmptyState icon={<Inbox className="h-5 w-5" />} title="Queue is clear" hint={active === "all" ? "No requests have been submitted yet." : "No requests in this stage right now."} />}
            />
            {rows.length > 0 && <LoadMore hasMore={!!list.hasNextPage} loading={list.isFetchingNextPage} onLoad={() => void list.fetchNextPage()} shown={rows.length} noun="requests" />}
          </>
        )}
      </section>
    </div>
  );
}
