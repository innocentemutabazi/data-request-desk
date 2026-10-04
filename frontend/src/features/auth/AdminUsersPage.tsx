import { useEffect, useState } from "react";
import { UserPlus } from "lucide-react";
import { api } from "@/shared/lib/api";
import { Button } from "@/shared/ui/Button";
import { Field, Input, Select } from "@/shared/ui/Field";
import type { User } from "./types";

export function AdminUsersPage() {
  const [users, setUsers] = useState<User[]>([]);
  const [email, setEmail] = useState("");
  const [name, setName] = useState("");
  const [password, setPassword] = useState("");
  const [role, setRole] = useState<User["role"]>("client");
  const load = () => void api<User[]>("/users").then(setUsers);
  useEffect(load, []);
  const create = async () => {
    await api<User>("/users", {
      method: "POST",
      json: { email, name, password, role },
    });
    setEmail("");
    setName("");
    setPassword("");
    load();
  };
  const toggle = async (user: User) => {
    await api<User>(`/users/${user.id}`, {
      method: "PATCH",
      json: { is_active: !user.is_active },
    });
    load();
  };
  const changeRole = async (user: User, next: User["role"]) => {
    await api<User>(`/users/${user.id}`, {
      method: "PATCH",
      json: { role: next },
    });
    load();
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
        <Button
          variant="primary"
          disabled={!name || !email || password.length < 8}
          onClick={() => void create()}
        >
          <UserPlus className="h-4 w-4" /> Create user
        </Button>
      </section>
      <section className="card overflow-hidden">
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
                  className="rounded-lg border border-line-strong bg-surface px-2 py-2 text-sm"
                >
                  <option value="client">Client</option>
                  <option value="operator">Operator</option>
                  <option value="admin">Admin</option>
                </select>
                <Button
                  size="sm"
                  variant={user.is_active ? "secondary" : "primary"}
                  onClick={() => void toggle(user)}
                >
                  {user.is_active ? "Deactivate" : "Activate"}
                </Button>
              </div>
            </div>
          ))}
        </div>
      </section>
    </div>
  );
}
