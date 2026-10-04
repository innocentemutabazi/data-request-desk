import { useState } from "react";
import { errorMessage } from "@/shared/lib/api";
import { Input } from "@/shared/ui/Field";
import { ErrorState } from "@/shared/ui/EmptyState";
import { BreakdownTable } from "../components/BreakdownTable";
import { OverviewStrip } from "../components/OverviewStrip";
import { TimeseriesChart } from "../components/TimeseriesChart";
import { useOverview } from "../hooks";
import type { AnalyticsRange } from "../api";

export function AnalyticsPage() {
  const [range, setRange] = useState<AnalyticsRange>({});
  const overview = useOverview(range);
  return (
    <div className="space-y-6">
      <header>
        <h1 className="text-2xl font-semibold">Analytics</h1>
        <p className="mt-1 text-sm text-ink-soft">Inventory health and desk throughput. Aggregated in the database; no rows are loaded into the app.</p>
      </header>
      <div className="card flex flex-wrap items-end gap-3 p-4">
        <label className="text-xs font-medium text-ink-mute">From<Input className="mt-1 text-ink" type="date" value={range.from ?? ""} onChange={(e) => setRange((r) => ({ ...r, from: e.target.value || undefined }))} /></label>
        <label className="text-xs font-medium text-ink-mute">To<Input className="mt-1 text-ink" type="date" value={range.to ?? ""} onChange={(e) => setRange((r) => ({ ...r, to: e.target.value || undefined }))} /></label>
      </div>
      {overview.isError ? (
        <div className="card"><ErrorState message={errorMessage(overview.error)} onRetry={() => void overview.refetch()} /></div>
      ) : (
        <OverviewStrip data={overview.data} loading={overview.isLoading} />
      )}
      <TimeseriesChart range={range} />
      <BreakdownTable range={range} />
    </div>
  );
}
