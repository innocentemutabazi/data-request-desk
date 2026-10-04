import { useMemo, useState } from "react";
import { Boxes } from "lucide-react";
import { useAuth } from "@/features/auth/AuthProvider";
import { EpisodeTable, useEpisodesInfinite, type EpisodeFilters } from "@/features/episodes";
import { ImportPanel } from "@/features/imports";
import { useTasks } from "@/features/requests";
import { errorMessage } from "@/shared/lib/api";
import { cn } from "@/shared/lib/cn";
import { EmptyState, ErrorState } from "@/shared/ui/EmptyState";
import { Select } from "@/shared/ui/Field";
import { LoadMore } from "@/shared/ui/LoadMore";

export function InventoryPage() {
  const { user } = useAuth();
  const canImport = user?.role === "operator" || user?.role === "admin";
  const [tab, setTab] = useState<"browse" | "import">("browse");

  return (
    <div className="space-y-6">
      <header className="flex flex-wrap items-end justify-between gap-4">
        <div>
          <h1 className="text-2xl font-semibold">Inventory</h1>
          <p className="mt-1 text-sm text-ink-soft">Every recorded episode, newest first. Pages load by cursor, so the millionth row is as fast as the first.</p>
        </div>
        {canImport && (
          <div role="tablist" aria-label="Inventory view" className="inline-flex rounded-lg bg-sunken p-1">
            {(["browse", "import"] as const).map((t) => (
              <button key={t} role="tab" aria-selected={tab === t} onClick={() => setTab(t)}
                className={cn("rounded-md px-3.5 py-1.5 text-[13px] font-medium capitalize transition-colors", tab === t ? "bg-surface shadow-card" : "text-ink-soft hover:text-ink")}>
                {t === "browse" ? "Browse" : "Import CSV"}
              </button>
            ))}
          </div>
        )}
      </header>
      {tab === "import" && canImport ? <ImportPanel /> : <Browse />}
    </div>
  );
}

function Browse() {
  const tasks = useTasks();
  const [filters, setFilters] = useState<EpisodeFilters>({ availability: "all" });
  const q = useEpisodesInfinite(filters);
  const rows = useMemo(() => q.data?.pages.flatMap((p) => p.items) ?? [], [q.data]);
  const set = (patch: Partial<EpisodeFilters>) => setFilters((f) => ({ ...f, ...patch }));

  return (
    <section className="card overflow-hidden" aria-label="Episodes">
      <div className="grid gap-3 border-b border-line p-4 sm:grid-cols-3">
        <label className="text-xs font-medium text-ink-mute">Task
          <Select className="mt-1 text-ink" value={filters.task_name ?? ""} onChange={(e) => set({ task_name: e.target.value || undefined })}>
            <option value="">All tasks</option>
            {tasks.data?.map((t) => <option key={t.task_name} value={t.task_name}>{t.task_name}</option>)}
          </Select>
        </label>
        <label className="text-xs font-medium text-ink-mute">Quality
          <Select className="mt-1 text-ink" value={filters.quality?.[0] ?? ""} onChange={(e) => set({ quality: e.target.value ? [e.target.value as "good" | "usable" | "bad"] : undefined })}>
            <option value="">Any quality</option><option value="good">Good</option><option value="usable">Usable</option><option value="bad">Bad</option>
          </Select>
        </label>
        <label className="text-xs font-medium text-ink-mute">Availability
          <Select className="mt-1 text-ink" value={filters.availability ?? "all"} onChange={(e) => set({ availability: e.target.value as EpisodeFilters["availability"] })}>
            <option value="all">All</option><option value="available">Available</option><option value="assigned">Assigned</option>
          </Select>
        </label>
      </div>

      {q.isError ? (
        <ErrorState message={errorMessage(q.error)} onRetry={() => void q.refetch()} />
      ) : (
        <>
          <EpisodeTable rows={rows} loading={q.isLoading} showRequestLink empty={<EmptyState icon={<Boxes className="h-5 w-5" />} title="No episodes match" hint="Loosen the filters, or import episodes.csv." />} />
          {rows.length > 0 && <LoadMore hasMore={!!q.hasNextPage} loading={q.isFetchingNextPage} onLoad={() => void q.fetchNextPage()} shown={rows.length} noun="episodes" />}
        </>
      )}
    </section>
  );
}
