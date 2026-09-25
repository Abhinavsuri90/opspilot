import { z } from "zod";

export const loginSchema = z.object({
  org_slug: z.string().min(1, "Enter your organization"),
  email: z.email("Enter a valid email"),
  password: z.string().min(1, "Enter your password"),
});
