const dtf = new Intl.DateTimeFormat(undefined, { dateStyle: "medium", timeStyle: "short" });
const df = new Intl.DateTimeFormat(undefined, { dateStyle: "medium" });
const nf = new Intl.NumberFormat();

export const fmtDateTime = (iso: string | null | undefined) => (iso ? dtf.format(new Date(iso)) : "—");
export const fmtDate = (iso: string | null | undefined) => (iso ? df.format(new Date(iso)) : "—");
export const fmtNum = (n: number | null | undefined) => (n == null ? "—" : nf.format(n));

export function fmtDuration(seconds: number | null | undefined): string {
  if (seconds == null) return "—";
  const s = Math.round(seconds);
  if (s < 60) return `${s}s`;
  const m = Math.floor(s / 60);
  if (m < 60) return `${m}m ${s % 60}s`;
  return `${Math.floor(m / 60)}h ${m % 60}m`;
}

export function fmtHours(seconds: number): string {
  const h = seconds / 3600;
  return h >= 100 ? nf.format(Math.round(h)) : h.toFixed(1);
}

export function timeAgo(iso: string): string {
  const diff = (Date.now() - new Date(iso).getTime()) / 1000;
  if (diff < 45) return "just now";
  if (diff < 3600) return `${Math.round(diff / 60)}m ago`;
  if (diff < 86400) return `${Math.round(diff / 3600)}h ago`;
  return `${Math.round(diff / 86400)}d ago`;
}
