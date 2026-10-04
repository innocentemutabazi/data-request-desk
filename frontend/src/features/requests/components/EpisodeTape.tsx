import { cn } from "@/shared/lib/cn";

/**
 * Assigned / requested as a strip of recording cells - one cell per episode - so progress reads
 * as "tape filling up". Beyond 40 episodes individual cells would be noise, so it becomes a bar.
 */
export function EpisodeTape({ assigned, requested, size = "md", className }: { assigned: number; requested: number; size?: "sm" | "md"; className?: string }) {
  const label = `${assigned} of ${requested} episodes assigned`;
  const done = assigned >= requested;
  const fill = done ? "bg-st-accepted" : "bg-brand";

  if (requested > 40) {
    return (
      <div role="img" aria-label={label} className={cn("overflow-hidden rounded-full bg-line", size === "sm" ? "h-2" : "h-3", className)}>
        <div className={cn("h-full rounded-full transition-[width] duration-500", fill)} style={{ width: `${Math.min(100, (assigned / requested) * 100)}%` }} />
      </div>
    );
  }
  return (
    <div role="img" aria-label={label} className={cn("flex gap-[3px]", size === "sm" ? "h-3" : "h-6", className)}>
      {Array.from({ length: requested }, (_, i) => (
        <span
          key={i}
          className={cn("min-w-[3px] flex-1 origin-bottom rounded-[2px]", i < assigned ? cn(fill, "animate-tape-fill") : "bg-line")}
          style={i < assigned ? { animationDelay: `${Math.min(i, 20) * 25}ms` } : undefined}
        />
      ))}
    </div>
  );
}
