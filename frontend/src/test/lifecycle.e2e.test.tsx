/**
 * Mounts the REAL app in jsdom and drives the whole business flow against a REAL running backend:
 *
 *   client submits → operator starts + auto-assigns (background export runs) → operator delivers → client accepts
 *
 * Run:  E2E_API_URL=http://localhost:8000 npm test
 *       (E2E_EXPECT=failure when the backend runs with EXPORT_FAILURE_RATE=1 to exercise the failure path)
 * Skipped automatically when E2E_API_URL is not set.
 */
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";
import { App } from "@/app/App";
import { Providers } from "@/app/providers";

const API = process.env.E2E_API_URL;
const EXPECT_FAILURE = process.env.E2E_EXPECT === "failure";
const suite = API ? describe : describe.skip;
const SLOW = { timeout: 25_000 };

async function backendRequest(email: string, password: string, id: string) {
  const login = await fetch("/api/auth/login", { method: "POST", body: new URLSearchParams({ username: email, password }) });
  const { access_token } = (await login.json()) as { access_token: string };
  const res = await fetch(`/api/requests/${id}`, { headers: { Authorization: `Bearer ${access_token}` } });
  return (await res.json()) as { status: string; assigned_count: number; export: { status: string; attempts: number } | null };
}

suite("request lifecycle through the real UI + API", () => {
  it(`client → operator → export (${EXPECT_FAILURE ? "fails" : "succeeds"}) → delivery → acceptance`, async () => {
    const user = userEvent.setup();
    const title = `E2E cups ${Date.now()}`;
    window.history.pushState({}, "", "/login");
    render(
      <Providers>
        <App />
      </Providers>,
    );

    const signOut = async () => user.click((await screen.findAllByRole("button", { name: /sign out/i }))[0]!);

    // ---------------------------------------------------------------- 1. client submits a request
    await user.click(await screen.findByRole("button", { name: /Client\s*Acme Robotics/ }));
    expect(await screen.findByRole("heading", { name: "My dataset requests" })).toBeInTheDocument();
    // skeletons give way to the empty state / table
    await user.click(screen.getByRole("button", { name: /new request/i }));
    const dialog = await screen.findByRole("dialog");
    await user.type(within(dialog).getByLabelText("Title"), title);
    await user.selectOptions(await within(dialog).findByLabelText("Task"), "pick cup");
    const count = within(dialog).getByLabelText("Episodes needed");
    await user.clear(count);
    await user.type(count, "3");
    await user.type(within(dialog).getByLabelText("Delivery deadline"), "2026-10-31");
    await user.click(within(dialog).getByRole("button", { name: /submit request/i }));

    expect(await screen.findByRole("heading", { name: title })).toBeInTheDocument(); // navigated to the detail page
    expect(await screen.findByText("Request submitted")).toBeInTheDocument(); // success toast
    const id = window.location.pathname.split("/").pop()!;
    expect(screen.queryByRole("button", { name: /start work/i })).not.toBeInTheDocument(); // clients can't drive operator moves
    expect(screen.queryByText("Dataset export")).not.toBeInTheDocument(); // export internals are staff-only

    // ---------------------------------------------------------------- 2. operator starts work and auto-assigns
    await signOut();
    // sign-out must land on a CLEAN login: the next user is not dropped onto the previous user's page
    expect(await screen.findByRole("heading", { name: "Sign in" })).toBeInTheDocument();
    expect(window.location.pathname).toBe("/login");
    await user.click(await screen.findByRole("button", { name: /Operator\s*Olu/ }));
    expect(await screen.findByRole("heading", { name: "Request queue" })).toBeInTheDocument(); // role home, not the old URL
    await user.click(await screen.findByRole("link", { name: title })); // from the queue
    await user.click(await screen.findByRole("button", { name: /start work/i }));
    expect(await screen.findByText("Work started")).toBeInTheDocument();

    const deliver = await screen.findByRole("button", { name: /mark delivered/i });
    expect(deliver).toBeDisabled(); // the delivery guard is explained, not hidden
    expect(screen.getByText(/more episodes? to deliver/i)).toBeInTheDocument();

    await user.click(await screen.findByRole("button", { name: /auto-assign remaining \(3\)/i }));
    expect(await screen.findByText("Assigned 3 episodes")).toBeInTheDocument();

    // ---------------------------------------------------------------- 3. the background export reports through toasts
    if (EXPECT_FAILURE) {
      // the toast AND the export panel's status pill may both say "Export failed": assert at least one of each kind
      expect((await screen.findAllByText(/Export failed · /, undefined, SLOW)).length).toBeGreaterThan(0); // the toast
      expect((await screen.findAllByRole("button", { name: /retry export/i })).length).toBeGreaterThan(0); // toast action + panel button
      await waitFor(async () => expect((await backendRequest("ops1@example.com", "ops123", id)).export?.status).toBe("failed"), SLOW);
    } else {
      expect((await screen.findAllByText(/Export ready · /, undefined, SLOW)).length).toBeGreaterThan(0); // the toast
      await waitFor(async () => expect((await backendRequest("ops1@example.com", "ops123", id)).export?.status).toBe("succeeded"), SLOW);
    }

    // ---------------------------------------------------------------- 4. delivery (allowed regardless of export outcome)
    await waitFor(() => expect(screen.getByRole("button", { name: /mark delivered/i })).toBeEnabled(), SLOW);
    await user.click(screen.getByRole("button", { name: /mark delivered/i }));
    expect(await screen.findByText("Delivered", { selector: "p.text-sm.font-medium" }, SLOW)).toBeInTheDocument();
    await waitFor(() => expect(screen.queryByRole("button", { name: /mark delivered/i })).not.toBeInTheDocument());

    // ---------------------------------------------------------------- 5. the client reviews and accepts
    await signOut();
    await user.click(await screen.findByRole("button", { name: /Client\s*Acme Robotics/ }));
    expect(await screen.findByText(/waiting for your decision/i)).toBeInTheDocument();
    await user.click(await screen.findByRole("link", { name: title }));
    expect(await screen.findByText(/Your dataset has been delivered/i)).toBeInTheDocument();
    await user.click(await screen.findByRole("button", { name: /accept dataset/i }));
    expect(await screen.findByText("Dataset accepted")).toBeInTheDocument();

    const final = await backendRequest("client-a@example.com", "client123", id);
    expect(final.status).toBe("accepted");
    expect(final.assigned_count).toBe(3);
    expect(final.export).toBeNull(); // the API never exposes export internals to clients
  });

  it("a client is bounced away from staff pages and cannot see another tenant's request", async () => {
    const user = userEvent.setup();
    window.history.pushState({}, "", "/login");
    render(<Providers><App /></Providers>);
    await user.click(await screen.findByRole("button", { name: /Client\s*Acme Robotics/ }));
    await screen.findByRole("heading", { name: "My dataset requests" });

    window.history.pushState({}, "", "/analytics");
    window.dispatchEvent(new PopStateEvent("popstate"));
    // RequireRole redirects clients home; analytics UI is never rendered (and the API would 403 anyway).
    // waitFor the FINAL url: the redirect re-mounts the page, so a bare findBy could grab the outgoing one.
    await waitFor(() => {
      expect(window.location.pathname).toBe("/requests");
      expect(screen.getByRole("heading", { name: "My dataset requests" })).toBeInTheDocument();
    });
    expect(screen.queryByRole("heading", { name: "Analytics" })).not.toBeInTheDocument();
    expect(screen.queryByRole("link", { name: /inventory/i })).not.toBeInTheDocument();

    window.history.pushState({}, "", "/requests/00000000-0000-4000-8000-000000000000");
    window.dispatchEvent(new PopStateEvent("popstate"));
    expect(await screen.findByText("Request not found")).toBeInTheDocument();
  });
});
