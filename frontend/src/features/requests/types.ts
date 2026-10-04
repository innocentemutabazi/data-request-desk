export type RequestStatus =
  | "submitted"
  | "in_progress"
  | "delivered"
  | "accepted"
  | "rejected";
export type ExportStatus =
  | "not_started"
  | "pending"
  | "running"
  | "succeeded"
  | "failed";
export type Quality = "good" | "usable" | "bad";

export interface ExportInfo {
  status: ExportStatus;
  attempts: number;
  max_attempts: number;
  error: string | null;
  updated_at: string | null;
}

export interface DatasetRequest {
  id: string;
  title: string;
  deadline: string;
  notes: string | null;
  task_name: string;
  min_quality: Quality | null;
  recorded_after: string | null;
  recorded_before: string | null;
  episodes_requested: number;
  assigned_count: number;
  status: RequestStatus;
  client_id: string;
  client_name: string;
  client_organisation: string | null;
  operator_id: string | null;
  decision_reason: string | null;
  /** Operator-facing; the API omits it (null) for clients. */
  export: ExportInfo | null;
  available_transitions: RequestStatus[];
  created_at: string;
  updated_at: string;
  started_at: string | null;
  delivered_at: string | null;
  decided_at: string | null;
  status_history: StatusHistory[];
}

export interface StatusHistory {
  from_status: RequestStatus | null;
  to_status: RequestStatus;
  changed_by_id: string;
  changed_at: string;
  reason: string | null;
}

export interface NewRequestInput {
  title: string;
  task_name: string;
  episodes_requested: number;
  deadline: string;
  notes?: string | null;
  min_quality?: Quality | null;
  recorded_after?: string | null;
  recorded_before?: string | null;
}

export interface AssignmentResult {
  request: DatasetRequest;
  assigned_episode_ids: string[];
  fully_assigned: boolean;
  export_scheduled: boolean;
}

export type StatusSummary = Record<RequestStatus, number>;

export interface TaskCount {
  task_name: string;
  episodes: number;
}

/** Lifecycle order, as drawn by the pipeline strip. */
export const PIPELINE: RequestStatus[] = [
  "submitted",
  "in_progress",
  "delivered",
  "accepted",
  "rejected",
];

export const isTerminal = (s: RequestStatus) =>
  s === "accepted" || s === "rejected";
