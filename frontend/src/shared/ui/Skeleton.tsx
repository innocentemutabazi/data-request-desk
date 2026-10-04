import { cn } from "@/shared/lib/cn";

export const Skeleton = ({ className }: { className?: string }) => (
  <div className={cn("skeleton h-4", className)} aria-hidden="true" />
);

/** Placeholder rows that match a real table's column layout, so content doesn't jump when it lands. */
export function TableSkeleton({ rows = 6, widths }: { rows?: number; widths: string[] }) {
  return (
    <tbody aria-busy="true" aria-label="Loading">
      {Array.from({ length: rows }, (_, r) => (
        <tr key={r} className="border-t border-line">
          {widths.map((w, c) => (
            <td key={c} className="td">
              <Skeleton className={cn("h-4", w)} />
            </td>
          ))}
        </tr>
      ))}
    </tbody>
  );
}

export function CardSkeleton({ lines = 3 }: { lines?: number }) {
  return (
    <div className="card space-y-3 p-5" aria-busy="true" aria-label="Loading">
      <Skeleton className="h-5 w-1/3" />
      {Array.from({ length: lines }, (_, i) => (
        <Skeleton key={i} className={i % 2 ? "w-2/3" : "w-full"} />
      ))}
    </div>
  );
}
