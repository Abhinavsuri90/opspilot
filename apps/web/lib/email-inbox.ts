// The email inbox form: the values an administrator types, the checks the API
// would make anyway (so mistakes show inline), and the request body to send.

import { z } from "zod";
import type { components } from "@/lib/schema";

export type EmailInboxResponse = components["schemas"]["EmailInboxResponse"];
export type EmailInboxUpdate = components["schemas"]["EmailInboxUpdate"];
export type EmailInboxBackend = EmailInboxUpdate["backend"];

export const EMAIL_BACKENDS: readonly EmailInboxBackend[] = ["imap", "mailpit"];

export const backendLabels: Record<EmailInboxBackend, string> = {
  imap: "IMAP mailbox",
  mailpit: "Mailpit (development)",
};

export const backendDescriptions: Record<EmailInboxBackend, string> = {
  imap: "Polls a real mailbox over IMAP with TLS. Every PDF attachment on an unread message becomes a document.",
  mailpit: "Uses the local Mailpit test server; messages sent to this workspace's address are picked up. Only the API in development accepts it.",
};

export function isEmailBackend(value: unknown): value is EmailInboxBackend {
  return typeof value === "string" && (EMAIL_BACKENDS as readonly string[]).includes(value);
}

export type EmailInboxFormValues = {
  backend: EmailInboxBackend;
  address: string;
  host: string;
  port: string;
  username: string;
  folder: string;
  password: string;
  active: boolean;
};

export type EmailInboxFieldErrors = Partial<Record<keyof EmailInboxFormValues, string>>;

export const emptyEmailInboxForm: EmailInboxFormValues = { backend: "imap", address: "", host: "", port: "993", username: "", folder: "INBOX", password: "", active: true };

const HOSTNAME = /^(?=.{1,253}$)(?!-)[a-z0-9-]{1,63}(?<!-)(?:\.(?!-)[a-z0-9-]{1,63}(?<!-))*$/i;

const imapSchema = z.object({
  backend: z.literal("imap"),
  address: z.string().trim().toLowerCase().min(1, "Enter the mailbox address, such as ap@example.com.").max(320, "The address is too long.").refine(value => value.includes("@"), "Enter the mailbox address, such as ap@example.com."),
  host: z.string().trim().toLowerCase().min(1, "Enter the IMAP host, such as imap.example.com.").refine(value => HOSTNAME.test(value), "Enter a host name such as imap.example.com."),
  port: z.string().trim().refine(value => /^\d+$/.test(value) && Number(value) >= 1 && Number(value) <= 65535, "Enter a port between 1 and 65535."),
  username: z.string().trim().min(1, "Enter the mailbox user name.").max(320, "The user name is too long."),
  folder: z.string().trim().min(1, "Enter the folder to poll, usually INBOX.").max(200, "The folder name is too long.").refine(value => ![...value].some(char => char.charCodeAt(0) < 32 || char === '"' || char === "\\"), "The folder name contains characters IMAP cannot quote."),
  password: z.string(),
  active: z.boolean(),
});

const mailpitSchema = z.object({
  backend: z.literal("mailpit"),
  active: z.boolean(),
});

export const emailInboxSchema = z.discriminatedUnion("backend", [imapSchema, mailpitSchema]);

export type ParsedEmailInbox = z.output<typeof emailInboxSchema>;

/**
 * Validate the form. A password is required the first time an IMAP inbox is
 * saved and whenever no credentials are stored; afterwards leaving it blank
 * keeps the stored one.
 */
export function parseEmailInboxForm(values: EmailInboxFormValues, options: { hasCredentials: boolean }): { ok: true; value: ParsedEmailInbox } | { ok: false; errors: EmailInboxFieldErrors } {
  const result = emailInboxSchema.safeParse(values);
  if (!result.success) {
    const errors: EmailInboxFieldErrors = {};
    for (const issue of result.error.issues) {
      const field = issue.path[0];
      if (typeof field === "string" && !(field in errors)) errors[field as keyof EmailInboxFormValues] = issue.message;
    }
    return { ok: false, errors };
  }
  if (result.data.backend === "imap" && !result.data.password && !options.hasCredentials) {
    return { ok: false, errors: { password: "Enter the mailbox password. It is stored encrypted and never shown again." } };
  }
  return { ok: true, value: result.data };
}

/** The request body for a save: version 0 creates the inbox, the current version replaces it. */
export function emailInboxBody(parsed: ParsedEmailInbox, version: number): EmailInboxUpdate {
  if (parsed.backend === "mailpit") return { version, backend: "mailpit", active: parsed.active, config: {}, credentials: null };
  return {
    version,
    backend: "imap",
    address: parsed.address,
    config: { host: parsed.host, port: Number(parsed.port), username: parsed.username, folder: parsed.folder },
    // Blank means keep what is stored; the API only replaces credentials it receives.
    credentials: parsed.password ? { password: parsed.password } : null,
    active: parsed.active,
  };
}

/** Form values from a stored inbox; the password is never returned by the API, so it starts blank. */
export function emailInboxFormFromResponse(inbox: EmailInboxResponse | null): EmailInboxFormValues {
  if (!inbox) return emptyEmailInboxForm;
  const backend = isEmailBackend(inbox.backend) ? inbox.backend : "imap";
  const config = inbox.config;
  const text = (key: string, fallback: string) => { const value = config[key]; return typeof value === "string" || typeof value === "number" ? String(value) : fallback; };
  return {
    backend,
    address: inbox.address ?? "",
    host: text("host", ""),
    port: text("port", "993"),
    username: text("username", ""),
    folder: text("folder", "INBOX"),
    password: "",
    active: inbox.active,
  };
}

export type InboxHealth = "inactive" | "error" | "healthy" | "pending";

/** How the status panel summarizes the inbox: paused, failing, polling fine, or not polled yet. */
export function inboxHealth(inbox: Pick<EmailInboxResponse, "active" | "last_error" | "last_polled_at">): InboxHealth {
  if (!inbox.active) return "inactive";
  if (inbox.last_error) return "error";
  if (inbox.last_polled_at) return "healthy";
  return "pending";
}
