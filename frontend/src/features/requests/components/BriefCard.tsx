import { fmtDate } from "@/shared/lib/format";
import type { DatasetRequest } from "../types";

export function BriefCard({ request: r }: { request: DatasetRequest }) {
  const window =
    r.recorded_after || r.recorded_before
      ? `${r.recorded_after ? fmtDate(r.recorded_after) : "any time"} → ${r.recorded_before ? fmtDate(new Date(new Date(r.recorded_before).getTime() - 1).toISOString()) : "now"}`
      : "Any date";
  const rows: [string, React.ReactNode][] = [
    ["Client", r.client_organisation ?? r.client_name],
    ["Task", <span className="capitalize" key="t">{r.task_name}</span>],
    ["Minimum quality", r.min_quality ? <span className="capitalize" key="q">{r.min_quality} or better</span> : "Any"],
    ["Recorded", window],
    ["Episodes requested", <span className="num" key="n">{r.episodes_requested}</span>],
    ["Deadline", fmtDate(r.deadline)],
    ["Notes", r.notes || "None"],
    ["Submitted", fmtDate(r.created_at)],
  ];
  return (
    <section className="card p-5" aria-labelledby="brief-h">
      <h2 id="brief-h" className="mb-3 text-base font-semibold">Brief</h2>
      <dl className="space-y-2.5 text-sm">
        {rows.map(([k, v]) => (
          <div key={k} className="flex justify-between gap-4">
            <dt className="text-ink-mute">{k}</dt>
            <dd className="text-right font-medium">{v}</dd>
          </div>
        ))}
      </dl>
    </section>
  );
}
