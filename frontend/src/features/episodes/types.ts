import type { Quality } from "@/features/requests/types";

export interface Episode {
  episode_id: string;
  robot_id: string;
  task_name: string;
  recorded_at: string;
  duration_seconds: number;
  operator_name: string | null;
  quality: Quality;
  assigned_request_id: string | null;
}

export type Availability = "all" | "available" | "assigned";

export interface EpisodeFilters {
  task_name?: string;
  quality?: Quality[];
  robot_id?: string;
  availability?: Availability;
}

export interface ImportReport {
  filename: string | null;
  rows_read: number;
  blank_lines_skipped: number;
  inserted: number;
  duplicates_identical: number;
  duplicates_conflicting: number;
  rejected: number;
  rejected_by_reason: Record<string, number>;
  normalizations: Record<string, number>;
  warnings: Record<string, number>;
  rejected_samples: { line: number; reason: string; detail: string; raw: string }[];
  duplicate_samples: { line: number; episode_id: string; identical: boolean; note: string }[];
  duration_ms: number;
}
