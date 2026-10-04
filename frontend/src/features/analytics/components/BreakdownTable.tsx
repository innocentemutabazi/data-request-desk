import { useState } from "react";
import { BarChart3 } from "lucide-react";
import { errorMessage } from "@/shared/lib/api";
import { cn } from "@/shared/lib/cn";
import { fmtDuration, fmtHours, fmtNum } from "@/shared/lib/format";
import { EmptyState, ErrorState } from "@/shared/ui/EmptyState";
import { TableSkeleton } from "@/shared/ui/Skeleton";
import { useBreakdown } from "../hooks";
import type { GroupBy } from "../types";
import type { AnalyticsRange } from "../api";
import { QualityBar } from "./QualityBar";

const TABS: { id: GroupBy; label: string }[] = [
  { id: "task_name", label: "Task" },
  { id: "robot_id", label: "Robot" },
  { id: "quality", label: "Quality" },
  { id: "operator_name", label: "Operator" },
];

export function BreakdownTable({ range }: { range: AnalyticsRange }) {
  const [group, setGroup] = useState<GroupBy>("task_name");
  const q = useBreakdown(group, range);
  const max = Math.max(1, ...(q.data?.map((r) => r.episodes) ?? [1]));

  return (
    <section className="card overflow-hidden" aria-labelledby="bd-h">
      <div className="flex flex-wrap items-center justify-between gap-3 px-5 py-4">
        <div>
          <h2 id="bd-h" className="text-base font-semibold">Episode breakdown</h2>
          <p className="text-xs text-ink-mute">Durations aggregated in PostgreSQL (count, avg, percentile_cont).</p>
        </div>
        <div role="tablist" aria-label="Group by" className="inline-flex rounded-lg bg-sunken p-1">
          {TABS.map((t) => (
            <button key={t.id} role="tab" aria-selected={group === t.id} onClick={() => setGroup(t.id)}
              className={cn("rounded-md px-3 py-1.5 text-[13px] font-medium transition-colors", group === t.id ? "bg-surface shadow-card" : "text-ink-soft hover:text-ink")}>
              {t.label}
            </button>
          ))}
        </div>
      </div>

      {q.isError ? (
        <ErrorState message={errorMessage(q.error)} onRetry={() => void q.refetch()} />
      ) : (
        <div className="overflow-x-auto">
          <table className="w-full min-w-[860px]">
            <thead>
              <tr>
                <th className="th">{TABS.find((t) => t.id === group)?.label}</th>
                <th className="th w-56">Episodes</th>
                <th className="th w-40">Quality</th>
                <th className="th text-right">Avg</th>
                <th className="th text-right">p50</th>
                <th className="th text-right">p90</th>
                <th className="th text-right">p95</th>
                <th className="th text-right">Hours</th>
              </tr>
            </thead>
            {q.isLoading ? (
              <TableSkeleton widths={["w-28", "w-44", "w-28", "w-12", "w-12", "w-12", "w-12", "w-10"]} rows={7} />
            ) : (
              <tbody>
                {q.data?.map((r) => (
                  <tr key={r.key ?? "∅"} className="border-t border-line hover:bg-sunken/70">
                    <td className={cn("td font-medium", group !== "operator_name" && group !== "robot_id" ? "capitalize" : "", group === "robot_id" && "font-mono text-[13px]")}>
                      {r.key ?? <span className="font-normal text-ink-mute">(unknown)</span>}
                    </td>
                    <td className="td">
                      <div className="flex items-center gap-3">
                        <div className="h-2 flex-1 overflow-hidden rounded-full bg-line"><div className="h-full rounded-full bg-brand" style={{ width: `${(r.episodes / max) * 100}%` }} /></div>
                        <span className="num w-16 text-right text-[13px]">{fmtNum(r.episodes)}</span>
                      </div>
                    </td>
                    <td className="td"><QualityBar mix={r.quality} /></td>
                    <td className="td num text-right">{fmtDuration(r.avg_duration_seconds)}</td>
                    <td className="td num text-right">{fmtDuration(r.p50_duration_seconds)}</td>
                    <td className="td num text-right">{fmtDuration(r.p90_duration_seconds)}</td>
                    <td className="td num text-right">{fmtDuration(r.p95_duration_seconds)}</td>
                    <td className="td num text-right text-ink-soft">{fmtHours(r.total_duration_seconds)}</td>
                  </tr>
                ))}
              </tbody>
            )}
          </table>
          {!q.isLoading && q.data?.length === 0 && <EmptyState icon={<BarChart3 className="h-5 w-5" />} title="No episodes yet" hint="Import episodes.csv from the Inventory page to see statistics." />}
        </div>
      )}
    </section>
  );
}
