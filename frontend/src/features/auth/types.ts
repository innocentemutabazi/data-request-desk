export type Role = "admin" | "operator" | "client";

export interface User {
  id: string;
  email: string;
  name: string;
  role: Role;
  organisation: string | null;
  is_active: boolean;
}

export interface LoginResponse {
  access_token: string;
  token_type: "bearer";
  expires_in: number;
  user: User;
}

export const isStaff = (role: Role | undefined): boolean =>
  role === "admin" || role === "operator";
export const homePathFor = (role: Role): string =>
  role === "client" ? "/requests" : "/queue";
