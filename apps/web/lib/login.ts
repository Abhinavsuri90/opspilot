import { z } from "zod";

export const loginSchema = z.object({
  org_slug: z.string().trim().toLowerCase().min(1, "Enter your organization"),
  email: z.string().trim().toLowerCase().pipe(z.email("Enter a valid email")),
  password: z.string().min(1, "Enter your password"),
});
