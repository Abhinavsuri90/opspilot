import type { components } from "@/lib/schema";

export type PoliciesResponse = components["schemas"]["PoliciesResponse"];
export type PoliciesUpdate = components["schemas"]["PoliciesUpdate"];
export type PolicyMode = "auto" | "needs_approval" | "forbidden";

export const POLICY_MODES: readonly PolicyMode[] = ["auto", "needs_approval", "forbidden"];
/** What the worker applies when neither an override nor the workflow config names a mode. */
export const FALLBACK_MODE: PolicyMode = "needs_approval";
export const POLICIES_QUERY_KEY = "policies";

export const policyModeDescriptions: Record<PolicyMode, string> = {
  auto: "Executes as soon as the document is approved.",
  needs_approval: "Waits in Pending approvals until a reviewer or administrator approves it.",
  forbidden: "Recorded but never executed.",
};

export function isPolicyMode(value: unknown): value is PolicyMode {
  return typeof value === "string" && (POLICY_MODES as readonly string[]).includes(value);
}

export type PolicySource = "override" | "config" | "fallback";

/** The mode the worker would apply right now for an action type, and where it comes from. */
export function effectivePolicy(server: Pick<PoliciesResponse, "policies" | "defaults_from_config">, actionType: string): { mode: PolicyMode; source: PolicySource } {
  const override = server.policies[actionType];
  if (isPolicyMode(override)) return { mode: override, source: "override" };
  const fromConfig = server.defaults_from_config[actionType];
  if (isPolicyMode(fromConfig)) return { mode: fromConfig, source: "config" };
  return { mode: FALLBACK_MODE, source: "fallback" };
}

export type PolicyDraft = Record<string, PolicyMode>;

export type PolicyRow = {
  actionType: string;
  /** What is saved on the server today. */
  effective: PolicyMode;
  source: PolicySource;
  /** What the workflow config says, shown beside the control so an override is visibly an override. */
  configDefault: PolicyMode | null;
  /** What the select shows: the unsaved choice, else the effective mode. */
  selected: PolicyMode;
  dirty: boolean;
};

/** One row per known action type, always in the API's order so the table is stable across refreshes. */
export function policyRows(server: PoliciesResponse, draft: PolicyDraft): PolicyRow[] {
  return server.known_action_types.map(actionType => {
    const { mode, source } = effectivePolicy(server, actionType);
    const configDefault = server.defaults_from_config[actionType];
    const selected = draft[actionType] ?? mode;
    return { actionType, effective: mode, source, configDefault: isPolicyMode(configDefault) ? configDefault : null, selected, dirty: actionType in draft };
  });
}

/** True when the organization already stores exactly this override. */
export function isSavedOverride(server: Pick<PoliciesResponse, "policies">, actionType: string, mode: PolicyMode): boolean {
  return server.policies[actionType] === mode;
}

export type PolicyDraftAction =
  | { type: "choose"; actionType: string; mode: PolicyMode }
  | { type: "discard" }
  | { type: "synced"; server: PoliciesResponse };

/**
 * Unsaved per-type choices. The table edits the organization's overrides, so a
 * choice counts as a change unless that exact override is already stored: picking
 * the mode the workflow config or the fallback already implies pins it explicitly,
 * which survives later config edits. Choosing the stored override again removes the
 * entry, so `dirty` rows are exactly the ones a save would send. A fresh server
 * answer drops choices it already reflects (someone else, or a previous save).
 */
export function policyDraftReducer(draft: PolicyDraft, action: PolicyDraftAction, server?: PoliciesResponse): PolicyDraft {
  switch (action.type) {
    case "choose": {
      const next = { ...draft };
      if (server && isSavedOverride(server, action.actionType, action.mode)) delete next[action.actionType];
      else next[action.actionType] = action.mode;
      return next;
    }
    case "discard":
      return {};
    case "synced": {
      const next: PolicyDraft = {};
      for (const [actionType, mode] of Object.entries(draft)) {
        if (!isSavedOverride(action.server, actionType, mode)) next[actionType] = mode;
      }
      return next;
    }
  }
}

export type PolicyChanges = { killSwitch?: boolean; shadowMode?: boolean; policies?: PolicyDraft };

/**
 * The compare-and-set body for one save: the version the screen was rendered
 * from plus only the switches that differ from it and the overrides not already
 * stored. Nothing to send yields null so the caller can skip the request.
 */
export function buildPoliciesUpdate(server: PoliciesResponse, changes: PolicyChanges): PoliciesUpdate | null {
  const body: PoliciesUpdate = { version: server.version };
  let changed = false;
  if (changes.killSwitch !== undefined && changes.killSwitch !== server.kill_switch) { body.kill_switch = changes.killSwitch; changed = true; }
  if (changes.shadowMode !== undefined && changes.shadowMode !== server.shadow_mode) { body.shadow_mode = changes.shadowMode; changed = true; }
  if (changes.policies) {
    const policies: Record<string, PolicyMode> = {};
    for (const [actionType, mode] of Object.entries(changes.policies)) {
      if (!server.known_action_types.includes(actionType)) continue;
      if (!isSavedOverride(server, actionType, mode)) policies[actionType] = mode;
    }
    if (Object.keys(policies).length > 0) { body.policies = policies; changed = true; }
  }
  return changed ? body : null;
}
