import { api, type Page } from "@/shared/lib/api";
import type { Episode, EpisodeFilters, ImportReport } from "./types";

export const listEpisodes = (f: EpisodeFilters, cursor?: string | null, limit = 50) =>
  api<Page<Episode>>("/episodes", { query: { ...f, cursor, limit } });

export const listCandidates = (requestId: string, cursor?: string | null, limit = 50) =>
  api<Page<Episode>>(`/requests/${requestId}/candidates`, { query: { cursor, limit } });

export const listAssigned = (requestId: string, cursor?: string | null, limit = 50) =>
  api<Page<Episode>>(`/requests/${requestId}/assignments`, { query: { cursor, limit } });

export const importEpisodes = (file: File) => {
  const form = new FormData();
  form.append("file", file);
  return api<ImportReport>("/episodes/import", { method: "POST", form });
};
