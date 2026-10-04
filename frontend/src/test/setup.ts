import "@testing-library/jest-dom/vitest";
import { cleanup, configure } from "@testing-library/react";
import { afterEach } from "vitest";

configure({ asyncUtilTimeout: 10_000 }); // first login pays for an Argon2 verification

afterEach(() => {
  cleanup();
  sessionStorage.clear();
});

// The app calls relative `/api/*` (proxied by Vite / nginx). In tests there is no proxy, so point
// those calls straight at a running backend: E2E_API_URL=http://localhost:8000
const API = process.env.E2E_API_URL;
if (API) {
  const real = globalThis.fetch.bind(globalThis);
  globalThis.fetch = ((input: RequestInfo | URL, init?: RequestInit) => {
    let opts = init;
    // Test-env quirk only: vitest's jsdom environment swaps the global URLSearchParams, and Node's fetch
    // checks `instanceof` against the *current* global, so it no longer recognises ANY URLSearchParams
    // body. Serialise it ourselves (the same bytes + header a browser would send).
    const body = opts?.body as unknown;
    if (body && typeof body === "object" && body.constructor?.name === "URLSearchParams") {
      opts = { ...opts, body: String(body), headers: { ...(opts?.headers as Record<string, string>), "Content-Type": "application/x-www-form-urlencoded;charset=UTF-8" } };
    }
    return real(typeof input === "string" && input.startsWith("/api") ? API + input.slice(4) : input, opts);
  }) as typeof fetch;
}
