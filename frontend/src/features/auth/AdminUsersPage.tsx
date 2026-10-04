import { useCallback, useEffect, useState } from "react";
import { UserPlus } from "lucide-react";
import { api, errorMessage } from "@/shared/lib/api";
import { Button } from "@/shared/ui/Button";
import { ErrorState } from "@/shared/ui/EmptyState";
import { Field, Input, Select } from "@/shared/ui/Field";
import { useToast } from "@/shared/toast/ToastProvider";
import type { User } from "./types";

export function AdminUsersPage() {
  const [users, setUsers] = useState<User[]>([]);
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [savingId, setSavingId] = useState<string | null>(null);
  const [creating, setCreating] = useState(false);
  const [email, setEmail] = useState("");
  const [name, setName] = useState("");
  const [password, setPassword] = useState("");
  const [role, setRole] = useState<User["role"]>("client");
  const toast = useToast();

  const load = useCallback(async () => {
    setLoading(true);
    setLoadError(null);
    try {
      setUsers(await api<User[]>("/users"));
    } catch (error) {
      setLoadError(errorMessage(error));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  const create = async () => {
    setCreating(true);
    try {
      await api<User>("/users", {
        method: "POST",
        json: { email, name, password, role },
      });
      setEmail("");
      setName("");
      setPassword("");
      toast.success("User created", `${name.trim()} can now sign in.`);
      await load();
    } catch (error) {
      toast.error("Couldn’t create user", errorMessage(error));
    } finally {
      setCreating(false);
    }
  };

  const updateUser = async (user: User, body: { role?: User["role"]; is_active?: boolean }) => {
    setSavingId(user.id);
    try {
      await api<User>(`/users/${user.id}`, { method: "PATCH", json: body });
      toast.success("User updated", `${user.email} access has been updated.`);
      await load();
    } catch (error) {
      toast.error("Couldn’t update user", errorMessage(error));
    } finally {
      setSavingId(null);
    }
  };

  const toggle = async (user: User) => {
    await updateUser(user, { is_active: !user.is_active });
  };

  const changeRole = async (user: User, next: User["role"]) => {
    await updateUser(user, { role: next });
  };

  return (
    <div className="space-y-6">
      <header>
        <h1 className="text-2xl font-semibold">User administration</h1>
        <p className="mt-1 text-sm text-ink-soft">
          Manage access and desk roles.
        </p>
      </header>
      <section className="card space-y-4 p-5">
        <h2 className="font-semibold">Create user</h2>
        <div className="grid gap-3 sm:grid-cols-2">
          <Field label="Name">
            {(id) => (
              <Input
                id={id}
                value={name}
                onChange={(e) => setName(e.target.value)}
              />
            )}
          </Field>
          <Field label="Email">
            {(id) => (
              <Input
                id={id}
                type="email"
                value={email}
                onChange={(e) => setEmail(e.target.value)}
              />
            )}
          </Field>
          <Field label="Temporary password">
            {(id) => (
              <Input
                id={id}
                type="password"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
              />
            )}
          </Field>
          <Field label="Role">
            {(id) => (
              <Select
                id={id}
                value={role}
                onChange={(e) => setRole(e.target.value as User["role"])}
              >
                <option value="client">Client</option>
                <option value="operator">Operator</option>
                <option value="admin">Admin</option>
              </Select>
            )}
          </Field>
        </div>
        <Button variant="primary" disabled={!name || !email || password.length < 8 || creating} loading={creating} onClick={() => void create()}>
          <UserPlus className="h-4 w-4" /> Create user
        </Button>
      </section>
      <section className="card overflow-hidden">
        {loadError ? (
          <ErrorState message={loadError} onRetry={() => void load()} />
        ) : loading ? (
          <p className="px-5 py-8 text-sm text-ink-soft" role="status">Loading users…</p>
        ) : users.length === 0 ? (
          <p className="px-5 py-8 text-sm text-ink-soft">No users found.</p>
        ) : (
          <div className="divide-y divide-line">
            {users.map((user) => (
            <div
              key={user.id}
              className="flex flex-wrap items-center justify-between gap-3 px-5 py-4"
            >
              <div>
                <p className="font-medium">{user.name}</p>
                <p className="text-sm text-ink-soft">{user.email}</p>
              </div>
              <div className="flex items-center gap-3">
                <select
                  aria-label={`Role for ${user.email}`}
                  value={user.role}
                  onChange={(e) =>
                    void changeRole(user, e.target.value as User["role"])
                  }
                  disabled={savingId === user.id}
                  className="rounded-lg border border-line-strong bg-surface px-2 py-2 text-sm"
                >
                  <option value="client">Client</option>
                  <option value="operator">Operator</option>
                  <option value="admin">Admin</option>
                </select>
                <Button
                  size="sm"
                  variant={user.is_active ? "secondary" : "primary"}
                  loading={savingId === user.id}
                  disabled={savingId === user.id}
                  onClick={() => void toggle(user)}
                >
                  {user.is_active ? "Deactivate" : "Activate"}
                </Button>
              </div>
              </div>
            ))}
          </div>
        )}
      </section>
    </div>
  );
}
