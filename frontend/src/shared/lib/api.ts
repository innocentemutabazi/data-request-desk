/** Thin fetch wrapper: bearer auth, one error shape, cursor-page helpers. */

export interface ApiErrorBody {
  error: { code: string; message: string; details?: Record<string, unknown> };
}

export class ApiError extends Error {
  constructor(
    public status: number,
    public code: string,
    message: string,
    public details: Record<string, unknown> = {},
  ) {
    super(message);
  }
}

export interface Page<T> {
  items: T[];
  next_cursor: string | null;
}

const BASE = "/api";
const TOKEN_KEY = "desk.token";

// sessionStorage: survives reloads, dies with the tab. (An httpOnly cookie would be stronger
// against XSS; see NOTES.md for the trade-off.)
export const tokenStore = {
  get: () => sessionStorage.getItem(TOKEN_KEY),
  set: (t: string) => sessionStorage.setItem(TOKEN_KEY, t),
  clear: () => sessionStorage.removeItem(TOKEN_KEY),
};

let onUnauthorized: (() => void) | null = null;
export const setUnauthorizedHandler = (fn: (() => void) | null) => {
  onUnauthorized = fn;
};

type Query = Record<
  string,
  string | number | boolean | undefined | null | (string | number)[]
>;

function toQuery(q?: Query): string {
  if (!q) return "";
  const p = new URLSearchParams();
  for (const [k, v] of Object.entries(q)) {
    if (v === undefined || v === null || v === "") continue;
    if (Array.isArray(v)) v.forEach((x) => p.append(k, String(x)));
    else p.append(k, String(v));
  }
  const s = p.toString();
  return s ? `?${s}` : "";
}

interface Options {
  method?: "GET" | "POST" | "PATCH";
  query?: Query;
  json?: unknown;
  form?: FormData | URLSearchParams;
  signal?: AbortSignal;
}

export async function api<T>(path: string, opts: Options = {}): Promise<T> {
  const headers: Record<string, string> = { Accept: "application/json" };
  const token = tokenStore.get();
  if (token) headers.Authorization = `Bearer ${token}`;

  let body: BodyInit | undefined;
  if (opts.json !== undefined) {
    headers["Content-Type"] = "application/json";
    body = JSON.stringify(opts.json);
  } else if (opts.form) {
    body = opts.form; // the browser sets the multipart / urlencoded content-type itself
  }

  let res: Response;
  try {
    res = await fetch(`${BASE}${path}${toQuery(opts.query)}`, {
      method: opts.method ?? "GET",
      headers,
      body,
      signal: opts.signal,
    });
  } catch (e) {
    if ((e as Error).name === "AbortError") throw e;
    throw new ApiError(
      0,
      "network_error",
      "Cannot reach the server. Check your connection and try again.",
    );
  }

  if (res.status === 204) return undefined as T;
  const data: unknown = await res.json().catch(() => null);
  if (!res.ok) {
    const err = (data as ApiErrorBody | null)?.error;
    // A rejected token (not a failed login attempt) means the session is over.
    if (res.status === 401 && token && path !== "/auth/login")
      onUnauthorized?.();
    throw new ApiError(
      res.status,
      err?.code ?? "http_error",
      err?.message ?? `Request failed (${res.status})`,
      err?.details ?? {},
    );
  }
  return data as T;
}

export const errorMessage = (e: unknown): string =>
  e instanceof ApiError
    ? e.message
    : e instanceof Error
      ? e.message
      : "Something went wrong.";
