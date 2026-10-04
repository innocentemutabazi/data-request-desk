import { useRef, useState, type DragEvent } from "react";
import { AlertTriangle, CheckCircle2, FileUp, RotateCcw } from "lucide-react";
import { errorMessage } from "@/shared/lib/api";
import { cn } from "@/shared/lib/cn";
import { fmtNum } from "@/shared/lib/format";
import { Button } from "@/shared/ui/Button";
import { useToast } from "@/shared/toast/ToastProvider";
import { useImportEpisodes } from "@/features/episodes/hooks";
import type { ImportReport } from "@/features/episodes/types";

const REASON_LABEL: Record<string, string> = {
  malformed_row: "Wrong column count",
  missing_episode_id: "Missing episode id",
  invalid_episode_id: "Invalid episode id",
  unknown_robot: "Unknown / blank robot",
  missing_task_name: "Missing task",
  invalid_recorded_at: "Unparseable date",
  future_recorded_at: "Date in the future",
  invalid_duration: "Invalid duration",
  invalid_quality: "Invalid / blank quality",
  value_too_long: "Value too long",
  invalid_encoding: "Undecodable bytes",
};
const NOTE_LABEL: Record<string, string> = {
  whitespace_trimmed: "rows had whitespace trimmed",
  case_normalized: "rows had casing normalised",
  date_format_normalized: "rows had a non-standard date format parsed",
  timestamps_assumed_utc: "timestamps had no zone (assumed UTC)",
  operator_name_missing: "rows kept with a blank operator",
};

export function ImportPanel() {
  const toast = useToast();
  const mutation = useImportEpisodes();
  const input = useRef<HTMLInputElement>(null);
  const [file, setFile] = useState<File | null>(null);
  const [over, setOver] = useState(false);
  const [report, setReport] = useState<ImportReport | null>(null);

  const pick = (f: File | undefined) => {
    if (!f) return;
    setFile(f);
    setReport(null);
  };
  const onDrop = (e: DragEvent) => { e.preventDefault(); setOver(false); pick(e.dataTransfer.files[0]); };

  const upload = () => {
    if (!file) return;
    mutation.mutate(file, {
      onSuccess: (r) => {
        setReport(r);
        toast.success("Import complete", `${fmtNum(r.inserted)} new · ${fmtNum(r.duplicates_identical + r.duplicates_conflicting)} duplicates skipped · ${fmtNum(r.rejected)} rejected`);
      },
      onError: (e) => toast.error("Import failed", errorMessage(e)),
    });
  };

  return (
    <div className="space-y-5">
      <section className="card p-5">
        <div
          onDragOver={(e) => { e.preventDefault(); setOver(true); }}
          onDragLeave={() => setOver(false)}
          onDrop={onDrop}
          className={cn("flex flex-col items-center rounded-xl border-2 border-dashed px-6 py-10 text-center transition-colors", over ? "border-brand bg-brand-tint" : "border-line-strong bg-sunken/50")}
        >
          <FileUp className="mb-3 h-7 w-7 text-ink-mute" aria-hidden="true" />
          <p className="font-medium">{file ? file.name : "Drop episodes.csv here"}</p>
          <p className="mt-1 text-sm text-ink-soft">{file ? `${(file.size / 1024).toFixed(1)} KB` : "or choose a file. Re-uploading the same file is safe: duplicates are skipped."}</p>
          <input ref={input} type="file" accept=".csv,text/csv" className="sr-only" onChange={(e) => pick(e.target.files?.[0])} aria-label="Choose CSV file" />
          <div className="mt-4 flex gap-2">
            <Button onClick={() => input.current?.click()}>Choose file</Button>
            <Button variant="primary" disabled={!file} loading={mutation.isPending} onClick={upload}>
              {mutation.isPending ? "Cleaning & importing…" : "Import"}
            </Button>
          </div>
        </div>
      </section>

      {report && <Report r={report} />}
    </div>
  );
}

function Tile({ label, value, tone }: { label: string; value: number; tone?: "good" | "warn" | "bad" }) {
  const color = tone === "good" ? "text-st-accepted" : tone === "warn" ? "text-st-progress" : tone === "bad" ? "text-st-rejected" : "";
  return (
    <div className="px-5 py-4">
      <p className="text-xs font-medium text-ink-mute">{label}</p>
      <p className={cn("num mt-1 text-2xl font-semibold", color)}>{fmtNum(value)}</p>
    </div>
  );
}

function Report({ r }: { r: ImportReport }) {
  const dupes = r.duplicates_identical + r.duplicates_conflicting;
  return (
    <section className="card overflow-hidden" aria-label="Import report">
      <div className="flex items-center gap-2 border-b border-line px-5 py-3.5">
        <CheckCircle2 className="h-5 w-5 text-st-accepted" />
        <h2 className="text-base font-semibold">Import report</h2>
        <span className="ml-auto num text-xs text-ink-mute">{r.duration_ms} ms</span>
      </div>
      <div className="grid grid-cols-2 sm:grid-cols-4 sm:divide-x sm:divide-line">
        <Tile label="Records read" value={r.rows_read} />
        <Tile label="Inserted" value={r.inserted} tone="good" />
        <Tile label="Duplicates skipped" value={dupes} tone={r.duplicates_conflicting ? "warn" : undefined} />
        <Tile label="Rejected" value={r.rejected} tone={r.rejected ? "bad" : undefined} />
      </div>

      <div className="space-y-5 border-t border-line p-5">
        {(Object.keys(r.normalizations).length > 0 || Object.keys(r.warnings).length > 0) && (
          <div>
            <h3 className="mb-2 text-sm font-semibold">Cleaned automatically</h3>
            <ul className="space-y-1 text-sm text-ink-soft">
              {[...Object.entries(r.normalizations), ...Object.entries(r.warnings)].map(([k, n]) => (
                <li key={k}><span className="num font-medium text-ink">{n}</span> {NOTE_LABEL[k] ?? k}</li>
              ))}
              {r.blank_lines_skipped > 0 && <li><span className="num font-medium text-ink">{r.blank_lines_skipped}</span> blank lines skipped</li>}
            </ul>
          </div>
        )}

        {r.rejected > 0 && (
          <div>
            <h3 className="mb-2 flex items-center gap-2 text-sm font-semibold"><AlertTriangle className="h-4 w-4 text-st-rejected" /> Rejected rows (fix the source and re-import)</h3>
            <div className="mb-3 flex flex-wrap gap-2">
              {Object.entries(r.rejected_by_reason).map(([k, n]) => (
                <span key={k} className="rounded-full bg-st-rejected-tint px-2.5 py-1 text-xs font-medium text-st-rejected"><span className="num">{n}</span> · {REASON_LABEL[k] ?? k}</span>
              ))}
            </div>
            <div className="overflow-x-auto rounded-lg border border-line">
              <table className="w-full min-w-[640px]">
                <thead className="bg-sunken/60"><tr><th className="th w-16">Line</th><th className="th">Reason</th><th className="th">Raw row</th></tr></thead>
                <tbody>
                  {r.rejected_samples.map((s) => (
                    <tr key={s.line} className="border-t border-line align-top">
                      <td className="td num text-ink-mute">{s.line}</td>
                      <td className="td"><div className="font-medium">{REASON_LABEL[s.reason] ?? s.reason}</div><div className="text-xs text-ink-mute">{s.detail}</div></td>
                      <td className="td font-mono text-xs text-ink-soft break-all">{s.raw}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            {r.rejected > r.rejected_samples.length && <p className="mt-2 text-xs text-ink-mute">Showing the first {r.rejected_samples.length} of {r.rejected}.</p>}
          </div>
        )}

        {r.duplicate_samples.some((d) => !d.identical) && (
          <div>
            <h3 className="mb-2 flex items-center gap-2 text-sm font-semibold"><RotateCcw className="h-4 w-4 text-st-progress" /> Conflicting duplicates (first row kept)</h3>
            <ul className="space-y-1.5 text-sm">
              {r.duplicate_samples.filter((d) => !d.identical).map((d) => (
                <li key={`${d.line}-${d.episode_id}`} className="rounded-lg bg-st-progress-tint px-3 py-2"><span className="font-mono text-[13px] font-medium">{d.episode_id}</span> <span className="text-ink-soft">line {d.line}: {d.note}</span></li>
              ))}
            </ul>
          </div>
        )}
      </div>
    </section>
  );
}
