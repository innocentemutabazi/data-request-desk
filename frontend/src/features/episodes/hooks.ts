import { useInfiniteQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import * as api from "./api";
import type { EpisodeFilters } from "./types";

export function useEpisodesInfinite(filters: EpisodeFilters) {
  return useInfiniteQuery({
    queryKey: ["episodes", "browse", filters],
    queryFn: ({ pageParam }) => api.listEpisodes(filters, pageParam),
    initialPageParam: null as string | null,
    getNextPageParam: (last) => last.next_cursor,
  });
}

export function useCandidates(requestId: string, enabled: boolean) {
  return useInfiniteQuery({
    queryKey: ["episodes", "candidates", requestId],
    queryFn: ({ pageParam }) => api.listCandidates(requestId, pageParam),
    initialPageParam: null as string | null,
    getNextPageParam: (last) => last.next_cursor,
    enabled,
  });
}

export function useAssignedEpisodes(requestId: string, enabled: boolean) {
  return useInfiniteQuery({
    queryKey: ["episodes", "assigned", requestId],
    queryFn: ({ pageParam }) => api.listAssigned(requestId, pageParam),
    initialPageParam: null as string | null,
    getNextPageParam: (last) => last.next_cursor,
    enabled,
  });
}

export function useImportEpisodes() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: api.importEpisodes,
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ["episodes"] });
      void qc.invalidateQueries({ queryKey: ["catalog"] });
      void qc.invalidateQueries({ queryKey: ["analytics"] });
    },
  });
}
