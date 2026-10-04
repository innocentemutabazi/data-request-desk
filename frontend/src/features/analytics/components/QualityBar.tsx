import { cn } from "@/shared/lib/cn";
import type { QualityMix } from "../types";

export function QualityBar({ mix, className }: { mix: QualityMix; className?: string }) {
  const total = mix.good + mix.usable + mix.bad || 1;
  const seg = (n: number) => `${(n / total) * 100}%`;
  return (
    <div
      role="img"
      aria-label={`${mix.good} good, ${mix.usable} usable, ${mix.bad} bad`}
      title={`${mix.good} good · ${mix.usable} usable · ${mix.bad} bad`}
      className={cn("flex h-2.5 overflow-hidden rounded-full bg-line", className)}
    >
      <span className="bg-st-accepted" style={{ width: seg(mix.good) }} />
      <span className="bg-st-progress" style={{ width: seg(mix.usable) }} />
      <span className="bg-st-rejected" style={{ width: seg(mix.bad) }} />
    </div>
  );
}
