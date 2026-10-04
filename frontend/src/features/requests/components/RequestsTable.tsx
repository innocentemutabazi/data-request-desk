import { Link, useNavigate } from "react-router-dom";
import { Play } from "lucide-react";
import { ExportStatusPill } from "@/features/exports";
import { fmtDate, timeAgo } from "@/shared/lib/format";
import { Button } from "@/shared/ui/Button";
import { TableSkeleton } from "@/shared/ui/Skeleton";
import type { DatasetRequest } from "../types";
import { EpisodeTape } from "./EpisodeTape";
import { StatusBadge } from "./StatusBadge";

interface Props {
  rows: DatasetRequest[];
  loading?: boolean;
  variant: "client" | "staff";
  onStart?: (r: DatasetRequest) => void;
  startingId?: string | null;
  empty?: React.ReactNode;
}

export function RequestsTable({ rows, loading, variant, onStart, startingId, empty }: Props) {
  const navigate = useNavigate();
  const staff = variant === "staff";
  const widths = staff ? ["w-44", "w-24", "w-24", "w-28", "w-20", "w-20", "w-12", "w-16"] : ["w-48", "w-24", "w-32", "w-20", "w-24"];

  return (
    <div className="overflow-x-auto">
      <table className="w-full min-w-[760px]">
        <thead>
          <tr>
            <th className="th">Request</th>
            {staff && <th className="th">Client</th>}
            <th className="th">Task</th>
            <th className="th w-44">Episodes</th>
            {staff && <th className="th">Export</th>}
            <th className="th">Status</th>
            <th className="th">{staff ? "Age" : "Created"}</th>
            {staff && <th className="th w-24" aria-label="Actions" />}
          </tr>
        </thead>
        {loading ? (
          <TableSkeleton widths={widths} rows={6} />
        ) : (
          <tbody>
            {rows.map((r) => (
              <tr
                key={r.id}
                className="cursor-pointer border-t border-line hover:bg-sunken/70"
                onClick={(e) => !(e.target as HTMLElement).closest("a,button") && navigate(`/requests/${r.id}`)}
              >
                <td className="td">
                  <Link to={`/requests/${r.id}`} className="font-medium hover:text-brand hover:underline">
                    {r.title}
                  </Link>
                  <div className="font-mono text-xs text-ink-mute">{r.id.slice(0, 8)}</div>
                </td>
                {staff && (
                  <td className="td">
                    {r.client_name}
                    {r.client_organisation && r.client_organisation !== r.client_name && <div className="text-xs text-ink-mute">{r.client_organisation}</div>}
                  </td>
                )}
                <td className="td capitalize">{r.task_name}</td>
                <td className="td">
                  <div className="flex items-center gap-3">
                    <EpisodeTape assigned={r.assigned_count} requested={r.episodes_requested} size="sm" className="w-24 shrink-0" />
                    <span className="num text-[13px] text-ink-soft">
                      {r.assigned_count}/{r.episodes_requested}
                    </span>
                  </div>
                </td>
                {staff && (
                  <td className="td">
                    <ExportStatusPill info={r.export} compact />
                  </td>
                )}
                <td className="td">
                  <StatusBadge status={r.status} />
                </td>
                <td className="td num whitespace-nowrap text-ink-soft" title={r.created_at}>
                  {staff ? timeAgo(r.created_at) : fmtDate(r.created_at)}
                </td>
                {staff && (
                  <td className="td text-right">
                    {r.available_transitions.includes("in_progress") && onStart && (
                      <Button size="sm" variant="secondary" loading={startingId === r.id} onClick={() => onStart(r)} aria-label={`Start work on ${r.title}`}>
                        <Play className="h-3.5 w-3.5" /> Start
                      </Button>
                    )}
                  </td>
                )}
              </tr>
            ))}
          </tbody>
        )}
      </table>
      {!loading && rows.length === 0 && empty}
    </div>
  );
}
