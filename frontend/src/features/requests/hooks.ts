import { useInfiniteQuery, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import * as api from "./api";
import type { DatasetRequest, NewRequestInput } from "./types";

export const requestKeys = {
  all: ["requests"] as const,
  list: (f: api.RequestFilters) => ["requests", "list", f] as const,
  detail: (id: string) => ["requests", "detail", id] as const,
  summary: ["requests", "summary"] as const,
  tasks: ["catalog", "tasks"] as const,
};

/** Keyset ("load more") pagination: the cursor from the previous page is the only paging state. */
export function useRequestsInfinite(filters: api.RequestFilters) {
  return useInfiniteQuery({
    queryKey: requestKeys.list(filters),
    queryFn: ({ pageParam }) => api.listRequests(filters, pageParam),
    initialPageParam: null as string | null,
    getNextPageParam: (last) => last.next_cursor,
  });
}

export const useRequestSummary = () => useQuery({ queryKey: requestKeys.summary, queryFn: api.getSummary });
export const useTasks = () => useQuery({ queryKey: requestKeys.tasks, queryFn: api.listTasks, staleTime: 60_000 });

export function useRequest(id: string) {
  return useQuery({ queryKey: requestKeys.detail(id), queryFn: () => api.getRequest(id) });
}

/** After any mutation: write the fresh request into the cache, then refresh lists + counts. */
function useAfterMutation() {
  const qc = useQueryClient();
  return (req: DatasetRequest) => {
    qc.setQueryData(requestKeys.detail(req.id), req);
    void qc.invalidateQueries({ queryKey: ["requests", "list"] });
    void qc.invalidateQueries({ queryKey: requestKeys.summary });
    void qc.invalidateQueries({ queryKey: ["episodes"] });
  };
}

export function useCreateRequest() {
  const done = useAfterMutation();
  return useMutation({ mutationFn: (b: NewRequestInput) => api.createRequest(b), onSuccess: done });
}

export function useTransition(id: string) {
  const done = useAfterMutation();
  return useMutation({ mutationFn: (action: api.Transition) => api.transition(id, action), onSuccess: done });
}

export function useReject(id: string) {
  const done = useAfterMutation();
  return useMutation({ mutationFn: (reason?: string) => api.rejectRequest(id, reason), onSuccess: done });
}

export function useAssign(id: string) {
  const done = useAfterMutation();
  return useMutation({
    mutationFn: (v: { episodeIds: string[] } | { auto: true; count?: number }) =>
      "auto" in v ? api.autoAssign(id, v.count) : api.assignEpisodes(id, v.episodeIds),
    onSuccess: (res) => done(res.request),
  });
}

export function useRetryExport(id: string) {
  const done = useAfterMutation();
  return useMutation({ mutationFn: () => api.retryExport(id), onSuccess: done });
}
