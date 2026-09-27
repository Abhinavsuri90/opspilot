import { describe, expect, it } from "vitest";
import { buildPoliciesUpdate, effectivePolicy, policyDraftReducer, policyRows, type PoliciesResponse } from "./policies";

const server: PoliciesResponse = {
  version: 4,
  kill_switch: false,
  shadow_mode: false,
  daily_llm_spend_cap_cents: 100,
  policies: { post_webhook: "needs_approval" },
  defaults_from_config: { post_webhook: "auto", export_csv: "auto" },
  known_action_types: ["append_row", "create_record", "post_webhook", "export_csv"],
  updated_at: "2026-09-27T10:00:00Z",
  updated_by_email: "admin@example.com",
};

describe("effective policy", () => {
  it("prefers the organization override, then the workflow config, then needs_approval", () => {
    expect(effectivePolicy(server, "post_webhook")).toEqual({ mode: "needs_approval", source: "override" });
    expect(effectivePolicy(server, "export_csv")).toEqual({ mode: "auto", source: "config" });
    expect(effectivePolicy(server, "append_row")).toEqual({ mode: "needs_approval", source: "fallback" });
  });

  it("builds one stable row per known action type with the config default beside it", () => {
    const rows = policyRows(server, { export_csv: "forbidden" });
    expect(rows.map(row => row.actionType)).toEqual(server.known_action_types);
    expect(rows.find(row => row.actionType === "post_webhook")).toMatchObject({ effective: "needs_approval", configDefault: "auto", selected: "needs_approval", dirty: false });
    expect(rows.find(row => row.actionType === "export_csv")).toMatchObject({ effective: "auto", configDefault: "auto", selected: "forbidden", dirty: true });
    expect(rows.find(row => row.actionType === "append_row")).toMatchObject({ configDefault: null, source: "fallback" });
  });
});

describe("policy draft reducer", () => {
  it("keeps every choice that is not already the stored override, including pinning an implied mode", () => {
    let draft = policyDraftReducer({}, { type: "choose", actionType: "export_csv", mode: "forbidden" }, server);
    expect(draft).toEqual({ export_csv: "forbidden" });
    // "auto" is only implied by the workflow config; choosing it stores an explicit override.
    draft = policyDraftReducer(draft, { type: "choose", actionType: "export_csv", mode: "auto" }, server);
    expect(draft).toEqual({ export_csv: "auto" });
    // The fallback needs_approval is implied too, so an explicit choice pins it.
    draft = policyDraftReducer(draft, { type: "choose", actionType: "append_row", mode: "needs_approval" }, server);
    expect(draft).toEqual({ export_csv: "auto", append_row: "needs_approval" });
    // post_webhook already stores needs_approval, so choosing it again is not a change.
    draft = policyDraftReducer({ post_webhook: "auto" }, { type: "choose", actionType: "post_webhook", mode: "needs_approval" }, server);
    expect(draft).toEqual({});
    expect(policyDraftReducer({ post_webhook: "auto" }, { type: "discard" })).toEqual({});
    expect(policyRows(server, { append_row: "needs_approval" }).find(row => row.actionType === "append_row")).toMatchObject({ selected: "needs_approval", dirty: true });
  });

  it("drops choices a fresh server answer already reflects and keeps the rest", () => {
    const draft = { post_webhook: "auto", export_csv: "forbidden" } as const;
    const refreshed = { ...server, version: 5, policies: { post_webhook: "auto" } };
    expect(policyDraftReducer(draft, { type: "synced", server: refreshed })).toEqual({ export_csv: "forbidden" });
  });
});

describe("compare-and-set payload", () => {
  it("sends the rendered version and only what changed", () => {
    expect(buildPoliciesUpdate(server, { killSwitch: true })).toEqual({ version: 4, kill_switch: true });
    expect(buildPoliciesUpdate(server, { killSwitch: false, shadowMode: false })).toBeNull();
    expect(buildPoliciesUpdate(server, { shadowMode: true, policies: { post_webhook: "needs_approval", export_csv: "forbidden", append_row: "needs_approval", unknown_type: "auto" } })).toEqual({
      version: 4,
      shadow_mode: true,
      policies: { export_csv: "forbidden", append_row: "needs_approval" },
    });
    expect(buildPoliciesUpdate(server, { policies: {} })).toBeNull();
    expect(buildPoliciesUpdate(server, { dailySpendCapCents: 250 })).toEqual({ version: 4, daily_llm_spend_cap_cents: 250 });
    expect(buildPoliciesUpdate(server, { dailySpendCapCents: null })).toEqual({ version: 4, daily_llm_spend_cap_cents: null });
  });
});
