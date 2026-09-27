import { describe, expect, it } from "vitest";
import { emailInboxBody, emailInboxFormFromResponse, emptyEmailInboxForm, inboxHealth, parseEmailInboxForm, type EmailInboxResponse } from "./email-inbox";

const imap = { ...emptyEmailInboxForm, address: " AP@Example.com ", host: "IMAP.example.com", port: "993", username: "ap@example.com", folder: "INBOX", password: "hunter2-secret", active: true };

const stored: EmailInboxResponse = {
  backend: "imap", address: "ap@example.com", config: { host: "imap.example.com", port: 143, username: "ap@example.com", folder: "Invoices" },
  has_credentials: true, active: false, version: 3, created_at: "2026-09-27T10:00:00Z", updated_at: "2026-09-27T10:00:00Z",
  last_polled_at: null, next_poll_at: null, last_error: null, last_test_at: null, last_test_ok: null, last_test_message: null,
  messages_processed: 0, documents_created: 0, poll_interval_seconds: 60,
};

describe("email inbox form", () => {
  it("accepts a complete IMAP configuration and normalizes the address and host", () => {
    const parsed = parseEmailInboxForm(imap, { hasCredentials: false });
    expect(parsed.ok).toBe(true);
    if (!parsed.ok) return;
    expect(emailInboxBody(parsed.value, 0)).toEqual({
      version: 0, backend: "imap", address: "ap@example.com", active: true,
      config: { host: "imap.example.com", port: 993, username: "ap@example.com", folder: "INBOX" },
      credentials: { password: "hunter2-secret" },
    });
  });

  it("reports the first problem per field", () => {
    const parsed = parseEmailInboxForm({ ...imap, address: "not-an-address", host: "-bad host-", port: "70000", username: " ", folder: 'Inv"oices' }, { hasCredentials: false });
    expect(parsed.ok).toBe(false);
    if (parsed.ok) return;
    expect(Object.keys(parsed.errors).sort()).toEqual(["address", "folder", "host", "port", "username"]);
    expect(parsed.errors.port).toBe("Enter a port between 1 and 65535.");
  });

  it("requires a password until one is stored, then keeps the stored one when blank", () => {
    const missing = parseEmailInboxForm({ ...imap, password: "" }, { hasCredentials: false });
    expect(missing.ok).toBe(false);
    if (!missing.ok) expect(missing.errors.password).toContain("Enter the mailbox password");
    const kept = parseEmailInboxForm({ ...imap, password: "" }, { hasCredentials: true });
    expect(kept.ok).toBe(true);
    if (kept.ok) expect(emailInboxBody(kept.value, 3).credentials).toBeNull();
  });

  it("needs nothing but the switch for the Mailpit backend", () => {
    const parsed = parseEmailInboxForm({ ...emptyEmailInboxForm, backend: "mailpit", active: false }, { hasCredentials: false });
    expect(parsed.ok).toBe(true);
    if (parsed.ok) expect(emailInboxBody(parsed.value, 0)).toEqual({ version: 0, backend: "mailpit", active: false, config: {}, credentials: null });
  });

  it("prefills the form from a stored inbox without the password", () => {
    expect(emailInboxFormFromResponse(stored)).toEqual({ backend: "imap", address: "ap@example.com", host: "imap.example.com", port: "143", username: "ap@example.com", folder: "Invoices", password: "", active: false });
    expect(emailInboxFormFromResponse(null)).toEqual(emptyEmailInboxForm);
    expect(emailInboxFormFromResponse({ ...stored, backend: "mailpit", config: {} }).backend).toBe("mailpit");
  });

  it("summarizes inbox health", () => {
    expect(inboxHealth({ active: false, last_error: "boom", last_polled_at: null })).toBe("inactive");
    expect(inboxHealth({ active: true, last_error: "Login failed", last_polled_at: "2026-09-27T10:00:00Z" })).toBe("error");
    expect(inboxHealth({ active: true, last_error: null, last_polled_at: "2026-09-27T10:00:00Z" })).toBe("healthy");
    expect(inboxHealth({ active: true, last_error: null, last_polled_at: null })).toBe("pending");
  });
});
