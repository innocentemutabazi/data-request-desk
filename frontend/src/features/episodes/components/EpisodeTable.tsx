import { Link } from "react-router-dom";
import { cn } from "@/shared/lib/cn";
import { fmtDateTime, fmtDuration } from "@/shared/lib/format";
import { TableSkeleton } from "@/shared/ui/Skeleton";
import type { Episode } from "../types";
import { QualityBadge } from "./QualityBadge";

export interface Selection {
  selected: ReadonlySet<string>;
  onToggle: (id: string) => void;
  /** Remaining capacity: once reached, unchecked rows are disabled (can't over-assign). */
  limit: number;
}

interface Props {
  rows: Episode[];
  loading?: boolean;
  selection?: Selection;
  showRequestLink?: boolean;
  empty?: React.ReactNode;
}

export function EpisodeTable({ rows, loading, selection, showRequestLink, empty }: Props) {
  const widths = ["w-24", "w-28", "w-20", "w-32", "w-12", "w-16", "w-16", ...(selection ? ["w-4"] : []), ...(showRequestLink ? ["w-16"] : [])];
  const full = selection ? selection.selected.size >= selection.limit : false;

  return (
    <div className="overflow-x-auto">
      <table className="w-full min-w-[720px]">
        <thead>
          <tr>
            {selection && <th className="th w-10" aria-label="Select" />}
            <th className="th">Episode</th>
            <th className="th">Task</th>
            <th className="th">Robot</th>
            <th className="th">Recorded</th>
            <th className="th text-right">Duration</th>
            <th className="th">Operator</th>
            <th className="th">Quality</th>
            {showRequestLink && <th className="th">Assigned to</th>}
          </tr>
        </thead>
        {loading ? (
          <TableSkeleton widths={widths} rows={6} />
        ) : (
          <tbody>
            {rows.map((e) => {
              const checked = selection?.selected.has(e.episode_id) ?? false;
              const disabled = !!selection && !checked && full;
              return (
                <tr key={e.episode_id} className={cn("border-t border-line", checked ? "bg-brand-tint/60" : "hover:bg-sunken/70")}>
                  {selection && (
                    <td className="td">
                      <input
                        type="checkbox"
                        className="h-4 w-4 rounded border-line-strong accent-[#0B7A66]"
                        checked={checked}
                        disabled={disabled}
                        onChange={() => selection.onToggle(e.episode_id)}
                        aria-label={`Select ${e.episode_id}`}
                        title={disabled ? "The request's quota is already covered by your selection" : undefined}
                      />
                    </td>
                  )}
                  <td className="td font-mono text-[13px] font-medium">{e.episode_id}</td>
                  <td className="td capitalize">{e.task_name}</td>
                  <td className="td font-mono text-[13px] text-ink-soft">{e.robot_id}</td>
                  <td className="td num whitespace-nowrap text-ink-soft">{fmtDateTime(e.recorded_at)}</td>
                  <td className="td num text-right">{fmtDuration(e.duration_seconds)}</td>
                  <td className="td text-ink-soft">{e.operator_name ?? <span className="text-ink-mute">—</span>}</td>
                  <td className="td">
                    <QualityBadge quality={e.quality} />
                  </td>
                  {showRequestLink && (
                    <td className="td">
                      {e.assigned_request_id ? (
                        <Link to={`/requests/${e.assigned_request_id}`} className="font-mono text-[13px] text-brand hover:underline">
                          {e.assigned_request_id.slice(0, 8)}
                        </Link>
                      ) : (
                        <span className="text-ink-mute">available</span>
                      )}
                    </td>
                  )}
                </tr>
              );
            })}
          </tbody>
        )}
      </table>
      {!loading && rows.length === 0 && empty}
    </div>
  );
}
