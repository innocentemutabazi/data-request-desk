import { fmtHours, fmtNum } from "@/shared/lib/format";
import { Skeleton } from "@/shared/ui/Skeleton";
import { QualityBar } from "./QualityBar";
import type { Overview } from "../types";

function Stat({
  label,
  value,
  sub,
}: {
  label: string;
  value: React.ReactNode;
  sub?: string;
}) {
  return (
    <div className="px-5 py-4">
      <p className="text-xs font-medium text-ink-mute">{label}</p>
      <p className="num mt-1 text-2xl font-semibold leading-tight">{value}</p>
      {sub && <p className="num mt-0.5 text-xs text-ink-mute">{sub}</p>}
    </div>
  );
}

export function OverviewStrip({
  data,
  loading,
}: {
  data: Overview | undefined;
  loading: boolean;
}) {
  if (loading || !data) {
    return (
      <div
        className="card grid grid-cols-2 divide-line sm:grid-cols-4 sm:divide-x"
        aria-busy="true"
        aria-label="Loading overview"
      >
        {Array.from({ length: 4 }, (_, i) => (
          <div key={i} className="space-y-2 px-5 py-4">
            <Skeleton className="h-3 w-16" />
            <Skeleton className="h-7 w-20" />
          </div>
        ))}
      </div>
    );
  }
  const pct = data.episodes_total
    ? Math.round((data.episodes_assigned / data.episodes_total) * 100)
    : 0;
  const rate = data.requests.acceptance_rate;
  return (
    <section className="card overflow-hidden" aria-label="Overview">
      <div className="grid grid-cols-2 sm:grid-cols-4 sm:divide-x sm:divide-line">
        <Stat
          label="Episodes"
          value={fmtNum(data.episodes_total)}
          sub={`${fmtHours(data.total_duration_seconds)} h recorded`}
        />
        <Stat
          label="Available"
          value={fmtNum(data.episodes_available)}
          sub={`${100 - pct}% of inventory`}
        />
        <Stat
          label="Assigned"
          value={fmtNum(data.episodes_assigned)}
          sub={`${pct}% of inventory`}
        />
        <Stat
          label="Acceptance rate"
          value={rate == null ? "—" : `${Math.round(rate * 100)}%`}
          sub={
            data.requests.turnaround_hours_p50 != null
              ? `median turnaround ${data.requests.turnaround_hours_p50} h`
              : "no deliveries yet"
          }
        />
      </div>
      <div className="flex flex-wrap items-center gap-x-6 gap-y-2 border-t border-line bg-sunken/50 px-5 py-3">
        <span className="text-xs font-medium text-ink-mute">Quality mix</span>
        <QualityBar mix={data.quality} className="min-w-[160px] flex-1" />
        <span className="num flex gap-4 text-xs text-ink-soft">
          <span>
            <i className="mr-1 inline-block h-2 w-2 rounded-full bg-st-accepted" />
            {fmtNum(data.quality.good)} good
          </span>
          <span>
            <i className="mr-1 inline-block h-2 w-2 rounded-full bg-st-progress" />
            {fmtNum(data.quality.usable)} usable
          </span>
          <span>
            <i className="mr-1 inline-block h-2 w-2 rounded-full bg-st-rejected" />
            {fmtNum(data.quality.bad)} bad
          </span>
        </span>
      </div>
      <div className="border-t border-line px-5 py-4">
        <p className="text-xs font-medium text-ink-mute">
          Top tasks by good episodes
        </p>
        <div className="mt-2 flex flex-wrap gap-x-5 gap-y-1 text-sm">
          {data.top_good_tasks.map((task) => (
            <span key={task.task_name}>
              <strong>{task.task_name}</strong>{" "}
              <span className="num text-ink-mute">{fmtNum(task.episodes)}</span>
            </span>
          ))}
        </div>
      </div>
    </section>
  );
}
