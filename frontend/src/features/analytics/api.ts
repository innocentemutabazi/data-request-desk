import { api } from "@/shared/lib/api";
import type { BreakdownRow, Bucket, GroupBy, Overview, TimeseriesPoint } from "./types";

export interface AnalyticsRange { from?: string; to?: string }
const queryRange = (range: AnalyticsRange) => ({
  recorded_from: range.from ? `${range.from}T00:00:00Z` : undefined,
  recorded_to: range.to ? new Date(new Date(`${range.to}T00:00:00Z`).getTime() + 86_400_000).toISOString() : undefined,
});
export const getOverview = (range: AnalyticsRange) => api<Overview>("/analytics/overview", { query: queryRange(range) });
export const getBreakdown = (group_by: GroupBy, range: AnalyticsRange) => api<BreakdownRow[]>("/analytics/episodes/breakdown", { query: { group_by, ...queryRange(range) } });
export const getTimeseries = (bucket: Bucket, range: AnalyticsRange) => api<TimeseriesPoint[]>("/analytics/episodes/timeseries", { query: { bucket, ...queryRange(range) } });
