import { forwardRef, useId, type InputHTMLAttributes, type ReactNode, type SelectHTMLAttributes } from "react";
import { cn } from "@/shared/lib/cn";

const CONTROL =
  "h-10 w-full rounded-lg border border-line-strong bg-surface px-3 text-sm placeholder:text-ink-mute " +
  "focus:border-brand focus:outline-none focus:ring-2 focus:ring-brand/20 disabled:bg-sunken";

export function Field({ label, hint, error, children }: { label: string; hint?: string; error?: string | null; children: (id: string) => ReactNode }) {
  const id = useId();
  return (
    <div>
      <label htmlFor={id} className="mb-1.5 block text-sm font-medium">
        {label}
      </label>
      {children(id)}
      {error ? (
        <p role="alert" className="mt-1.5 text-[13px] text-st-rejected">
          {error}
        </p>
      ) : (
        hint && <p className="mt-1.5 text-[13px] text-ink-mute">{hint}</p>
      )}
    </div>
  );
}

export const Input = forwardRef<HTMLInputElement, InputHTMLAttributes<HTMLInputElement>>(function Input({ className, ...p }, ref) {
  return <input ref={ref} className={cn(CONTROL, className)} {...p} />;
});

export const Select = forwardRef<HTMLSelectElement, SelectHTMLAttributes<HTMLSelectElement>>(function Select({ className, children, ...p }, ref) {
  return (
    <select ref={ref} className={cn(CONTROL, "pr-8", className)} {...p}>
      {children}
    </select>
  );
});
