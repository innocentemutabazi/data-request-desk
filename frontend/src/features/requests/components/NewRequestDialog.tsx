import { useMemo, useState, type FormEvent } from "react";
import { errorMessage } from "@/shared/lib/api";
import { Button } from "@/shared/ui/Button";
import { Dialog } from "@/shared/ui/Dialog";
import { Field, Input, Select } from "@/shared/ui/Field";
import { Skeleton } from "@/shared/ui/Skeleton";
import { useToast } from "@/shared/toast/ToastProvider";
import { useCreateRequest, useTasks } from "../hooks";
import type { DatasetRequest, Quality } from "../types";

const dayStartUtc = (d: string) => `${d}T00:00:00Z`;
/** `recorded_before` is exclusive server-side, so an inclusive end date becomes the next midnight. */
const nextDayStartUtc = (d: string) => new Date(new Date(`${d}T00:00:00Z`).getTime() + 86_400_000).toISOString();

export function NewRequestDialog({ open, onClose, onCreated }: { open: boolean; onClose: () => void; onCreated: (r: DatasetRequest) => void }) {
  const tasks = useTasks();
  const create = useCreateRequest();
  const toast = useToast();

  const [title, setTitle] = useState("");
  const [task, setTask] = useState("");
  const [count, setCount] = useState("10");
  const [deadline, setDeadline] = useState("");
  const [notes, setNotes] = useState("");
  const [minQuality, setMinQuality] = useState<"" | Quality>("");
  const [from, setFrom] = useState("");
  const [to, setTo] = useState("");
  const [touched, setTouched] = useState(false);

  const available = useMemo(() => tasks.data?.find((t) => t.task_name === task)?.episodes, [tasks.data, task]);

  const errors = {
    title: title.trim() ? null : "Give the request a short title.",
    task: task ? null : "Choose which task the demonstrations should cover.",
    count: Number.isInteger(+count) && +count >= 1 && +count <= 100_000 ? null : "Enter a whole number between 1 and 100,000.",
    deadline: deadline ? null : "Choose a delivery deadline.",
    window: from && to && from > to ? "The end date must be on or after the start date." : null,
  };
  const valid = !Object.values(errors).some(Boolean);

  const reset = () => {
    setTitle(""); setTask(""); setCount("10"); setDeadline(""); setNotes(""); setMinQuality(""); setFrom(""); setTo(""); setTouched(false);
  };

  const submit = (e: FormEvent) => {
    e.preventDefault();
    setTouched(true);
    if (!valid) return;
    create.mutate(
      {
        title: title.trim(),
        task_name: task,
        episodes_requested: +count,
        deadline,
        notes: notes.trim() || null,
        min_quality: minQuality || null,
        recorded_after: from ? dayStartUtc(from) : null,
        recorded_before: to ? nextDayStartUtc(to) : null,
      },
      {
        onSuccess: (req) => {
          toast.success("Request submitted", `“${req.title}” is queued for an operator.`);
          reset();
          onCreated(req);
        },
        onError: (err) => toast.error("Couldn’t submit the request", errorMessage(err)),
      },
    );
  };

  return (
    <Dialog
      open={open}
      onClose={onClose}
      title="New dataset request"
      description="Describe the demonstrations you need. An operator picks matching episodes for you."
      footer={
        <>
          <Button variant="ghost" onClick={onClose} type="button">Cancel</Button>
          <Button variant="primary" type="submit" form="new-request" loading={create.isPending}>Submit request</Button>
        </>
      }
    >
      <form id="new-request" onSubmit={submit} noValidate className="space-y-4">
        <Field label="Title" error={touched ? errors.title : null}>
          {(id) => <Input id={id} data-autofocus value={title} maxLength={200} onChange={(e) => setTitle(e.target.value)} placeholder="e.g. Cup grasping, cluttered table" />}
        </Field>

        <Field label="Task" error={touched ? errors.task : null} hint={available != null ? `${available.toLocaleString()} episodes recorded for this task.` : undefined}>
          {(id) =>
            tasks.isLoading ? (
              <Skeleton className="h-10 w-full" />
            ) : (
              <Select id={id} value={task} onChange={(e) => setTask(e.target.value)}>
                <option value="">Select a task…</option>
                {tasks.data?.map((t) => (
                  <option key={t.task_name} value={t.task_name}>
                    {t.task_name} ({t.episodes.toLocaleString()})
                  </option>
                ))}
              </Select>
            )
          }
        </Field>

        <div className="grid gap-4 sm:grid-cols-2">
          <Field label="Episodes needed" error={touched ? errors.count : null}>
            {(id) => <Input id={id} type="number" inputMode="numeric" min={1} max={100000} value={count} onChange={(e) => setCount(e.target.value)} />}
          </Field>
          <Field label="Minimum quality" hint="“Usable” also accepts good.">
            {(id) => (
              <Select id={id} value={minQuality} onChange={(e) => setMinQuality(e.target.value as "" | Quality)}>
                <option value="">Any</option>
                <option value="usable">Usable or better</option>
                <option value="good">Good only</option>
              </Select>
            )}
          </Field>
        </div>
        <Field label="Delivery deadline" error={touched ? errors.deadline : null}>
          {(id) => <Input id={id} type="date" value={deadline} onChange={(e) => setDeadline(e.target.value)} />}
        </Field>
        <Field label="Notes" hint="Optional context for the operator.">
          {(id) => <textarea id={id} className="field min-h-24 w-full" maxLength={5000} value={notes} onChange={(e) => setNotes(e.target.value)} />}
        </Field>

        <div className="grid gap-4 sm:grid-cols-2">
          <Field label="Recorded from" hint="Optional">{(id) => <Input id={id} type="date" value={from} onChange={(e) => setFrom(e.target.value)} />}</Field>
          <Field label="Recorded until" hint="Optional, inclusive" error={touched ? errors.window : null}>
            {(id) => <Input id={id} type="date" value={to} onChange={(e) => setTo(e.target.value)} />}
          </Field>
        </div>
      </form>
    </Dialog>
  );
}
