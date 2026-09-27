import { QueryClient, useQuery } from "@tanstack/react-query";
import { act, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { unauthorizedError } from "@/lib/errors";
import { hardNavigate } from "@/lib/navigation";
import { Providers, SESSION_CHANGE_KEY, SESSION_LOST_EVENT } from "./providers";

vi.mock("@/lib/navigation", () => ({ hardNavigate: vi.fn() }));

type Actor = { user_id: string; org_id: string; role: string };
const alice: Actor = { user_id: "user-a", org_id: "org-1", role: "admin" };
const bob: Actor = { user_id: "user-b", org_id: "org-1", role: "member" };

function createClient() {
  return new QueryClient({ defaultOptions: { queries: { retry: false } } });
}

function SessionProbe({ queryFn }: { queryFn: () => Promise<Actor> }) {
  const session = useQuery({ queryKey: ["session"], queryFn, staleTime: 5_000 });
  return <output>{session.data?.user_id ?? session.error?.message ?? "pending"}</output>;
}

function visit(path: string) {
  window.history.pushState({}, "", path);
}

async function otherTabChangedSession() {
  await act(async () => {
    window.dispatchEvent(new StorageEvent("storage", { key: SESSION_CHANGE_KEY }));
  });
}

beforeEach(() => visit("/dashboard"));
afterEach(() => vi.mocked(hardNavigate).mockClear());

describe("Providers", () => {
  it("purges every non-session query when the signed-in actor changes", () => {
    const client = createClient();
    render(<Providers client={client}><div /></Providers>);

    client.setQueryData(["session"], alice);
    client.setQueryData(["documents", "org-1"], [{ id: "d1" }]);
    client.setQueryData(["session"], { ...alice });
    expect(client.getQueryData(["documents", "org-1"])).toBeDefined();

    client.setQueryData(["session"], bob);
    expect(client.getQueryData(["documents", "org-1"])).toBeUndefined();
    expect(client.getQueryData(["session"])).toEqual(bob);
  });

  it("re-checks the session when another tab signs in and stays put while it is still valid", async () => {
    const client = createClient();
    const queryFn = vi.fn().mockResolvedValue(alice);
    render(<Providers client={client}><SessionProbe queryFn={queryFn} /></Providers>);
    await screen.findByText("user-a");
    client.setQueryData(["documents", "org-1"], [{ id: "d1" }]);

    await otherTabChangedSession();

    await waitFor(() => expect(queryFn).toHaveBeenCalledTimes(2));
    expect(hardNavigate).not.toHaveBeenCalled();
    expect(client.getQueryData(["documents", "org-1"])).toBeDefined();
  });

  it("ignores storage events for other keys", async () => {
    const client = createClient();
    const queryFn = vi.fn().mockResolvedValue(alice);
    render(<Providers client={client}><SessionProbe queryFn={queryFn} /></Providers>);
    await screen.findByText("user-a");

    await act(async () => {
      window.dispatchEvent(new StorageEvent("storage", { key: "unrelated" }));
    });

    expect(queryFn).toHaveBeenCalledTimes(1);
    expect(hardNavigate).not.toHaveBeenCalled();
  });

  it("switches tenant data when another tab signed into a different account", async () => {
    const client = createClient();
    const queryFn = vi.fn().mockResolvedValueOnce(alice).mockResolvedValue(bob);
    render(<Providers client={client}><SessionProbe queryFn={queryFn} /></Providers>);
    await screen.findByText("user-a");
    client.setQueryData(["documents", "org-1"], [{ id: "d1" }]);

    await otherTabChangedSession();

    await screen.findByText("user-b");
    expect(client.getQueryData(["documents", "org-1"])).toBeUndefined();
    expect(hardNavigate).not.toHaveBeenCalled();
  });

  it("sends the tab to sign in only when the re-checked session is rejected", async () => {
    const client = createClient();
    const queryFn = vi.fn().mockResolvedValueOnce(alice).mockRejectedValue(unauthorizedError());
    render(<Providers client={client}><SessionProbe queryFn={queryFn} /></Providers>);
    await screen.findByText("user-a");

    await otherTabChangedSession();

    await waitFor(() => expect(hardNavigate).toHaveBeenCalledWith("/login"));
  });

  it("clears the cache and leaves a protected page on session-lost, but never a public page", () => {
    const client = createClient();
    render(<Providers client={client}><div /></Providers>);
    client.setQueryData(["documents"], []);

    visit("/login");
    act(() => { window.dispatchEvent(new Event(SESSION_LOST_EVENT)); });
    expect(hardNavigate).not.toHaveBeenCalled();
    expect(client.getQueryData(["documents"])).toBeDefined();

    visit("/inbox");
    act(() => { window.dispatchEvent(new Event(SESSION_LOST_EVENT)); });
    expect(hardNavigate).toHaveBeenCalledWith("/login");
    expect(client.getQueryData(["documents"])).toBeUndefined();
  });
});
