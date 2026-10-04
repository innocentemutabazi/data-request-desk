import { api, type Page } from "@/shared/lib/api";
import type {
  AssignmentResult,
  DatasetRequest,
  ExportStatus,
  NewRequestInput,
  RequestStatus,
  StatusSummary,
  TaskCount,
} from "./types";

export interface RequestFilters {
  status?: RequestStatus[];
  export_status?: ExportStatus[];
}

export const listRequests = (
  f: RequestFilters,
  cursor?: string | null,
  limit = 20,
) => api<Page<DatasetRequest>>("/requests", { query: { ...f, cursor, limit } });

export const getRequest = (id: string) =>
  api<DatasetRequest>(`/requests/${id}`);
export const getSummary = () => api<StatusSummary>("/requests/summary");
export const listTasks = () => api<TaskCount[]>("/catalog/tasks");

export const createRequest = (body: NewRequestInput) =>
  api<DatasetRequest>("/requests", { method: "POST", json: body });

export type Transition = "start" | "deliver" | "accept" | "rework";
export const transition = (id: string, action: Transition) =>
  api<DatasetRequest>(`/requests/${id}/${action}`, { method: "POST" });
export const rejectRequest = (id: string, reason?: string) =>
  api<DatasetRequest>(`/requests/${id}/reject`, {
    method: "POST",
    json: { reason: reason || null },
  });

export const assignEpisodes = (id: string, episodeIds: string[]) =>
  api<AssignmentResult>(`/requests/${id}/assignments`, {
    method: "POST",
    json: { episode_ids: episodeIds },
  });
export const autoAssign = (id: string, count?: number) =>
  api<AssignmentResult>(`/requests/${id}/assignments/auto`, {
    method: "POST",
    json: count ? { count } : {},
  });
export const retryExport = (id: string) =>
  api<DatasetRequest>(`/requests/${id}/export/retry`, { method: "POST" });
