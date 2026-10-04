import { useState, type FormEvent } from "react";
import { Navigate, useNavigate } from "react-router-dom";
import { ArrowRight } from "lucide-react";
import { errorMessage } from "@/shared/lib/api";
import { Button } from "@/shared/ui/Button";
import { Field, Input } from "@/shared/ui/Field";
import { useAuth } from "./AuthProvider";
import { homePathFor } from "./types";

const DEMO = [
  { label: "Client", who: "Acme Robotics", email: "client-a@example.com", password: "client123" },
  { label: "Operator", who: "Olu", email: "ops1@example.com", password: "ops123" },
  { label: "Admin", who: "Ada", email: "admin@example.com", password: "admin123" },
];

export function LoginPage() {
  const { user, login } = useAuth();
  const navigate = useNavigate();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  if (user) return <Navigate to={homePathFor(user.role)} replace />;

  const submit = async (e?: FormEvent, creds = { email, password }) => {
    e?.preventDefault();
    setBusy(true);
    setError(null);
    try {
      const u = await login(creds.email, creds.password);
      navigate(homePathFor(u.role), { replace: true });
    } catch (err) {
      setError(errorMessage(err));
      setBusy(false);
    }
  };

  return (
    <main className="grid min-h-screen lg:grid-cols-[1.05fr_1fr]">
      {/* Brand panel: the product's own motif - a strip of recorded episodes filling up */}
      <section className="relative hidden overflow-hidden bg-ink p-12 text-white lg:flex lg:flex-col lg:justify-between">
        <div className="flex items-center gap-2.5 text-sm font-medium text-white/80">
          <span className="grid h-8 w-8 place-items-center rounded-lg bg-brand">
            <TapeGlyph />
          </span>
          Dataset Request Desk
        </div>
        <div>
          <div className="mb-8 flex h-24 items-end gap-1.5" aria-hidden="true">
            {Array.from({ length: 28 }, (_, i) => (
              <span
                key={i}
                className="w-full rounded-sm bg-brand animate-tape-fill"
                style={{ height: `${30 + ((i * 37) % 70)}%`, opacity: i < 19 ? 1 : 0.28, animationDelay: `${i * 28}ms` }}
              />
            ))}
          </div>
          <h1 className="max-w-md text-4xl font-semibold leading-[1.1]">Robot demonstrations, requested and delivered with a paper trail.</h1>
          <p className="mt-4 max-w-md text-white/65">Submit a dataset brief, watch episodes get assigned, accept what meets the bar.</p>
        </div>
        <p className="text-xs text-white/40">Every episode belongs to exactly one request at a time.</p>
      </section>

      <section className="flex items-center justify-center p-6 sm:p-12">
        <div className="w-full max-w-sm">
          <h2 className="text-2xl font-semibold">Sign in</h2>
          <p className="mt-1 text-sm text-ink-soft">Use your desk credentials.</p>

          <form onSubmit={submit} className="mt-8 space-y-4" noValidate>
            <Field label="Email">
              {(id) => <Input id={id} type="email" autoComplete="username" required autoFocus value={email} onChange={(e) => setEmail(e.target.value)} />}
            </Field>
            <Field label="Password" error={error}>
              {(id) => <Input id={id} type="password" autoComplete="current-password" required value={password} onChange={(e) => setPassword(e.target.value)} />}
            </Field>
            <Button type="submit" variant="primary" className="w-full" loading={busy} disabled={!email || !password}>
              Sign in
            </Button>
          </form>

          <div className="mt-10 border-t border-line pt-6">
            <p className="mb-3 text-xs font-medium text-ink-mute">Demo accounts (seeded)</p>
            <ul className="space-y-2">
              {DEMO.map((d) => (
                <li key={d.email}>
                  <button
                    type="button"
                    disabled={busy}
                    onClick={() => void submit(undefined, { email: d.email, password: d.password })}
                    className="group flex w-full items-center justify-between rounded-lg border border-line bg-surface px-3.5 py-2.5 text-left text-sm transition-colors hover:border-brand hover:bg-brand-tint disabled:opacity-60"
                  >
                    <span>
                      <span className="font-medium">{d.label}</span>
                      <span className="ml-2 text-ink-mute">{d.who}</span>
                    </span>
                    <ArrowRight className="h-4 w-4 text-ink-mute transition-transform group-hover:translate-x-0.5 group-hover:text-brand" />
                  </button>
                </li>
              ))}
            </ul>
          </div>
        </div>
      </section>
    </main>
  );
}

export function TapeGlyph() {
  return (
    <svg viewBox="0 0 32 32" className="h-5 w-5" aria-hidden="true">
      <g fill="#fff">
        <rect x="6" y="9" width="4" height="14" rx="1" />
        <rect x="12" y="9" width="4" height="14" rx="1" opacity=".75" />
        <rect x="18" y="9" width="4" height="14" rx="1" opacity=".5" />
        <rect x="24" y="9" width="2.5" height="14" rx="1" opacity=".3" />
      </g>
    </svg>
  );
}
