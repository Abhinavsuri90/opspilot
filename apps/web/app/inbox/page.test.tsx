import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import InboxPage from "./page";

const { GET } = vi.hoisted(() => ({ GET: vi.fn() }));

vi.mock("@/lib/api", () => ({ api: { GET, POST: vi.fn() } }));
vi.mock("next/navigation", () => ({
  useRouter: () => ({ replace: vi.fn(), push: vi.fn(), prefetch: vi.fn() }),
  usePathname: () => "/inbox",
  useSearchParams: () => new URLSearchParams(),
}));

const session = { user_id: "user-a", email: "owner@example.com", org_id: "org-1", org_name: "Northwind", org_slug: "northwind", default_currency: "USD", role: "admin" };
const summary = { total_documents: 0, status_counts: {}, amounts_by_currency: [], excluded_amount_count: 0, categories: [], scope: "all_accessible_documents" };

function ok(data: unknown) {
  return { data, error: undefined, response: new Response(null, { status: 200 }) };
}

function renderInbox() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(<QueryClientProvider client={client}><InboxPage /></QueryClientProvider>);
}

beforeEach(() => {
  GET.mockReset();
  GET.mockImplementation(async (path: string) => {
    if (path === "/v1/auth/me") return ok(session);
    if (path === "/v1/categories") return ok([]);
    if (path === "/v1/workspace/summary") return ok(summary);
    if (path === "/v1/documents") return ok([]);
    return { data: undefined, error: { error: { code: "not_found" } }, response: new Response(null, { status: 404 }) };
  });
});

describe("inbox empty states", () => {
  it("invites the first upload when the workspace has no documents and no filters", async () => {
    renderInbox();

    expect(await screen.findByText("No documents yet.")).toBeInTheDocument();
    expect(screen.getByText(/Upload your first document/)).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Clear filters" })).not.toBeInTheDocument();
  });

  it("explains an empty filtered list and offers to clear the filters", async () => {
    renderInbox();
    await screen.findByText("No documents yet.");

    fireEvent.click(screen.getByRole("button", { name: "Needs review" }));

    expect(await screen.findByText("No documents match these filters.")).toBeInTheDocument();
    await waitFor(() => expect(GET).toHaveBeenCalledWith("/v1/documents", expect.objectContaining({
      params: { query: expect.objectContaining({ status: "needs_review" }) },
    })));
    expect(screen.queryByText("No documents yet.")).not.toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Clear filters" }));

    expect(await screen.findByText("No documents yet.")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "All" })).toHaveAttribute("aria-pressed", "true");
  });
});
