import { z } from "zod";

export const ORGANIZATION_TEMPLATES = ["invoice", "logistics"] as const;
export type OrganizationTemplate = (typeof ORGANIZATION_TEMPLATES)[number];

/** The starting workflow an organization is created with; the API stores the matching configuration as version 1. */
export const templateOptions: { value: OrganizationTemplate; label: string; description: string }[] = [
  { value: "invoice", label: "Invoices", description: "Vendor invoices: vendor, invoice number, dates, totals and currency, with arithmetic checks." },
  { value: "logistics", label: "Logistics: purchase orders and delivery notes", description: "Purchase orders and delivery notes: buyer, supplier, PO and delivery note numbers, dates, packages and totals." },
];

export const SLUG_PATTERN = /^[a-z0-9](?:[a-z0-9-]{0,78}[a-z0-9])?$/;
export const PASSWORD_MESSAGE = "Use a password with 12–128 characters, including a letter and a number.";

const orgSlug = z.string().trim().toLowerCase().regex(SLUG_PATTERN, "Use 1–80 letters, numbers, or hyphens for the workspace ID. Start and end with a letter or number.");
const email = z.string().trim().toLowerCase().pipe(z.email("Enter a valid email address."));
const password = z.string()
  .min(12, PASSWORD_MESSAGE)
  .max(128, PASSWORD_MESSAGE)
  .refine(value => /\p{L}/u.test(value) && /\p{Nd}/u.test(value), PASSWORD_MESSAGE);
const confirmation = z.string();

// Field order matters: the form reports the first issue, so the organization
// fields are checked before the credentials, and the password match last.
export const registrationSchema = z.discriminatedUnion("mode", [
  z.object({
    mode: z.literal("create"),
    org_name: z.string().trim().min(2, "Enter an organization name with at least 2 characters."),
    org_slug: orgSlug,
    default_currency: z.string().trim().toUpperCase().length(3, "Choose a default currency."),
    template: z.enum(ORGANIZATION_TEMPLATES, { message: "Choose the documents your workspace starts with." }).default("invoice"),
    email,
    password,
    confirmation,
  }),
  z.object({
    mode: z.literal("join"),
    org_slug: orgSlug,
    requested_role: z.enum(["member", "reviewer"]),
    email,
    password,
    confirmation,
  }),
]).refine(values => values.password === values.confirmation, { message: "The passwords do not match.", path: ["confirmation"] });

export type RegistrationInput = z.input<typeof registrationSchema>;
export type Registration = z.output<typeof registrationSchema>;

export function firstIssueMessage(error: z.ZodError, fallback = "Check the form and try again."): string {
  return error.issues[0]?.message ?? fallback;
}
