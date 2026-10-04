export interface QualityMix {
  good: number;
  usable: number;
  bad: number;
}

export interface Overview {
  episodes_total: number;
  episodes_assigned: number;
  episodes_available: number;
  total_duration_seconds: number;
  avg_duration_seconds: number | null;
  quality: QualityMix;
  requests: {
    by_status: Record<string, number>;
    acceptance_rate: number | null;
    turnaround_hours_p50: number | null;
    turnaround_hours_p90: number | null;
  };
  top_good_tasks: TaskCount[];
}

export interface TaskCount {
  task_name: string;
  episodes: number;
}

export type GroupBy = "task_name" | "robot_id" | "quality" | "operator_name";
export type Bucket = "day" | "week" | "month";

export interface BreakdownRow {
  key: string | null;
  episodes: number;
  total_duration_seconds: number;
  avg_duration_seconds: number | null;
  min_duration_seconds: number;
  max_duration_seconds: number;
  p50_duration_seconds: number | null;
  p90_duration_seconds: number | null;
  p95_duration_seconds: number | null;
  quality: QualityMix;
}

export interface TimeseriesPoint {
  bucket: string;
  episodes: number;
  total_duration_seconds: number;
}
