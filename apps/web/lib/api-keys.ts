// Display rules for organization API keys. The plaintext key exists in the
// browser exactly once, right after creation; everything else is metadata.

import { z } from "zod";
import type { components } from "@/lib/schema";

export type ApiKeyResponse = components["schemas"]["ApiKeyResponse"];
export type ApiKeyCreatedResponse = components["schemas"]["ApiKeyCreatedResponse"];

export const apiKeyNameSchema = z.string().trim().min(1, "Give the key a name, such as the system that will use it.").max(100, "Keep the name under 100 characters.");

export type ApiKeyState = "active" | "revoked";

export function apiKeyState(key: Pick<ApiKeyResponse, "revoked_at">): ApiKeyState {
  return key.revoked_at ? "revoked" : "active";
}

/** What a list row shows for the key itself: the prefix people can match against logs, never the secret. */
export function maskedKey(prefix: string): string {
  return `opk_${prefix}_${"•".repeat(12)}`;
}

/** "Never used" until the API records a request. */
export function lastUsedLabel(lastUsedAt: string | null, format: (value: string) => string): string {
  return lastUsedAt ? `Last used ${format(lastUsedAt)}` : "Never used";
}

/** Active keys first, then newest first, so the key someone just made is at the top of the live ones. */
export function sortApiKeys(keys: readonly ApiKeyResponse[]): ApiKeyResponse[] {
  return [...keys].sort((a, b) => Number(Boolean(a.revoked_at)) - Number(Boolean(b.revoked_at)) || b.created_at.localeCompare(a.created_at));
}

/** The upload call an integrator copies: a placeholder key built from the real prefix, never a secret. */
export function curlExample(origin: string, prefix: string): string {
  const base = origin.replace(/\/+$/, "");
  const placeholder = `opk_${prefix || "xxxxxxxx"}_<secret>`;
  return [
    `curl -X POST ${base}/api/v1/documents \\`,
    `  -H "Authorization: Bearer ${placeholder}" \\`,
    `  -F "file=@purchase-order.pdf"`,
  ].join("\n");
}

/** Only a key that was just created carries a plaintext value. */
export function isFreshKey(key: ApiKeyResponse | ApiKeyCreatedResponse): key is ApiKeyCreatedResponse {
  return "key" in key && typeof key.key === "string" && key.key.length > 0;
}
