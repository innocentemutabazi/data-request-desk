import { api } from "@/shared/lib/api";
import type { LoginResponse, User } from "./types";

export const login = (email: string, password: string) =>
  api<LoginResponse>("/auth/login", { method: "POST", form: new URLSearchParams({ username: email, password }) });

export const fetchMe = () => api<User>("/auth/me");
