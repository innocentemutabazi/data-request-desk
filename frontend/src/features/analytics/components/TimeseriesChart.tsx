import { useMemo, useState } from "react";
import { errorMessage } from "@/shared/lib/api";
import { cn } from "@/shared/lib/cn";
import { fmtDate, fmtNum } from "@/shared/lib/format";
import { ErrorState } from "@/shared/ui/EmptyState";
import { Skeleton } from "@/shared/ui/Skeleton";
import { useTimeseries } from "../hooks";
import type { Bucket } from "../types";
import type { AnalyticsRange } from "../api";

const BUCKETS: Bucket[] = ["day", "week", "month"];

/** Dependency-free bar chart: episodes recorded per bucket. Inline SVG scales to its container. */
export function TimeseriesChart({ range }: { range: AnalyticsRange }) {
  const [bucket, setBucket] = useState<Bucket>("week");
  const q = useTimeseries(bucket, range);
  const [hover, setHover] = useState<number | null>(null);

  const { max, peak } = useMemo(() => {
    const pts = q.data ?? [];
    const m = Math.max(1, ...pts.map((p) => p.episodes));
    return { max: m, peak: pts.find((p) => p.episodes === m) };
  }, [q.data]);

  const pts = q.data ?? [];
  const W = 720, H = 180, PAD = 4;
  const bw = pts.length ? (W - PAD * 2) / pts.length : 0;
  const shown = hover != null ? pts[hover] : peak;

  return (
    <section className="card p-5" aria-labelledby="ts-h">
      <div className="mb-4 flex flex-wrap items-start justify-between gap-3">
        <div>
          <h2 id="ts-h" className="text-base font-semibold">Episodes recorded</h2>
          <p className="num text-sm text-ink-soft">
            {shown ? <>{hover != null ? "" : "Peak · "}{fmtDate(shown.bucket)} — <span className="font-medium text-ink">{fmtNum(shown.episodes)}</span> episodes</> : "\u00A0"}
          </p>
        </div>
        <div role="tablist" aria-label="Bucket" className="inline-flex rounded-lg bg-sunken p-1">
          {BUCKETS.map((b) => (
            <button key={b} role="tab" aria-selected={bucket === b} onClick={() => { setBucket(b); setHover(null); }}
              className={cn("rounded-md px-3 py-1.5 text-[13px] font-medium capitalize transition-colors", bucket === b ? "bg-surface shadow-card" : "text-ink-soft hover:text-ink")}>
              {b}
            </button>
          ))}
        </div>
      </div>

      {q.isError ? (
        <ErrorState message={errorMessage(q.error)} onRetry={() => void q.refetch()} />
      ) : q.isLoading ? (
        <Skeleton className="h-[180px] w-full" />
      ) : (
        <>
          <svg viewBox={`0 0 ${W} ${H}`} className="h-44 w-full" role="img" aria-label={`Episodes recorded per ${bucket}`} onMouseLeave={() => setHover(null)}>
            <line x1={0} x2={W} y1={H - 0.5} y2={H - 0.5} stroke="#D9DFDC" />
            {pts.map((p, i) => {
              const h = Math.max(2, (p.episodes / max) * (H - 12));
              return (
                <g key={p.bucket} onMouseEnter={() => setHover(i)}>
                  <rect x={PAD + i * bw} y={0} width={bw} height={H} fill="transparent" />
                  <rect x={PAD + i * bw + Math.min(1.5, bw * 0.15)} y={H - h} width={Math.max(1, bw - Math.min(3, bw * 0.3))} height={h} rx={1.5}
                    fill={hover === i ? "#085C4D" : p === peak ? "#0B7A66" : "#7FBFB1"}>
                    <title>{`${fmtDate(p.bucket)}: ${p.episodes} episodes`}</title>
                  </rect>
                </g>
              );
            })}
          </svg>
          <div className="num mt-1 flex justify-between text-xs text-ink-mute">
            <span>{pts[0] ? fmtDate(pts[0].bucket) : ""}</span>
            <span>{pts.length ? `${pts.length} ${bucket}${pts.length === 1 ? "" : "s"}` : "No data"}</span>
            <span>{pts.length ? fmtDate(pts[pts.length - 1]?.bucket) : ""}</span>
          </div>
        </>
      )}
    </section>
  );
}
