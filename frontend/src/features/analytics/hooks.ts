import { useQuery } from "@tanstack/react-query";
import * as api from "./api";
import type { Bucket, GroupBy } from "./types";
import type { AnalyticsRange } from "./api";

// Aggregates over millions of rows are comparatively expensive and change only on import/assignment:
// cache them for a minute rather than refetching on every focus.
const STALE = 60_000;

export const useOverview = (range: AnalyticsRange) => useQuery({ queryKey: ["analytics", "overview", range], queryFn: () => api.getOverview(range), staleTime: STALE });
export const useBreakdown = (g: GroupBy, range: AnalyticsRange = {}) => useQuery({ queryKey: ["analytics", "breakdown", g, range], queryFn: () => api.getBreakdown(g, range), staleTime: STALE });
export const useTimeseries = (b: Bucket, range: AnalyticsRange = {}) => useQuery({ queryKey: ["analytics", "timeseries", b, range], queryFn: () => api.getTimeseries(b, range), staleTime: STALE });
