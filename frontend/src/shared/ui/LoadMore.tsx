import { Button } from "./Button";

/** Footer for keyset-paginated lists: "Load more" while a next cursor exists, a quiet end marker after. */
export function LoadMore({ hasMore, loading, onLoad, shown, noun = "items" }: { hasMore: boolean; loading: boolean; onLoad: () => void; shown: number; noun?: string }) {
  return (
    <div className="flex items-center justify-between border-t border-line px-4 py-3 text-sm text-ink-mute">
      <span className="num">
        {shown} {noun} loaded{hasMore ? "" : " · end of list"}
      </span>
      {hasMore && (
        <Button size="sm" onClick={onLoad} loading={loading}>
          Load more
        </Button>
      )}
    </div>
  );
}
