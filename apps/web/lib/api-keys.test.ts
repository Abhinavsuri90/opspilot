import { describe, expect, it } from "vitest";
import { apiKeyNameSchema, apiKeyState, curlExample, isFreshKey, lastUsedLabel, maskedKey, sortApiKeys, type ApiKeyResponse } from "./api-keys";

const key = (overrides: Partial<ApiKeyResponse>): ApiKeyResponse => ({
  id: "k1", name: "Warehouse", key_prefix: "ab12cd34", scopes: "documents:write", created_by_email: "admin@example.com",
  created_at: "2026-09-27T10:00:00Z", last_used_at: null, revoked_at: null, ...overrides,
});

describe("API key display", () => {
  it("distinguishes active from revoked keys", () => {
    expect(apiKeyState(key({}))).toBe("active");
    expect(apiKeyState(key({ revoked_at: "2026-09-27T11:00:00Z" }))).toBe("revoked");
  });

  it("masks everything after the prefix", () => {
    expect(maskedKey("ab12cd34")).toBe("opk_ab12cd34_••••••••••••");
    expect(maskedKey("ab12cd34")).not.toContain("secret");
  });

  it("reports when a key was last used", () => {
    expect(lastUsedLabel(null, () => "never called")).toBe("Never used");
    expect(lastUsedLabel("2026-09-27T10:00:00Z", value => `on ${value}`)).toBe("Last used on 2026-09-27T10:00:00Z");
  });

  it("lists active keys first, newest first", () => {
    const sorted = sortApiKeys([
      key({ id: "old", created_at: "2026-09-01T00:00:00Z" }),
      key({ id: "revoked", created_at: "2026-09-20T00:00:00Z", revoked_at: "2026-09-21T00:00:00Z" }),
      key({ id: "new", created_at: "2026-09-27T00:00:00Z" }),
    ]);
    expect(sorted.map(item => item.id)).toEqual(["new", "old", "revoked"]);
  });

  it("builds a curl example with a placeholder secret, never a real key", () => {
    const example = curlExample("https://app.example.com/", "ab12cd34");
    expect(example).toContain("https://app.example.com/api/v1/documents");
    expect(example).toContain("Authorization: Bearer opk_ab12cd34_<secret>");
    expect(example).toContain('-F "file=@purchase-order.pdf"');
    expect(curlExample("http://localhost:3300", "")).toContain("opk_xxxxxxxx_<secret>");
  });

  it("only treats a freshly created key as showing its plaintext", () => {
    expect(isFreshKey(key({}))).toBe(false);
    expect(isFreshKey({ ...key({}), key: "opk_ab12cd34_secretsecretsecretsecretsecret12" })).toBe(true);
    expect(isFreshKey({ ...key({}), key: "" })).toBe(false);
  });

  it("requires a short, non-empty name", () => {
    expect(apiKeyNameSchema.safeParse("  Warehouse  ").data).toBe("Warehouse");
    expect(apiKeyNameSchema.safeParse("   ").success).toBe(false);
    expect(apiKeyNameSchema.safeParse("x".repeat(101)).success).toBe(false);
  });
});
