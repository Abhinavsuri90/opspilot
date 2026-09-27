import type { components } from "@/lib/schema";

export type Workspace = components["schemas"]["WorkspaceResponse"];
export type Category = components["schemas"]["CategoryResponse"];
export type Collaborator = components["schemas"]["CollaboratorResponse"];
export type Decision = "approve" | "reject" | "reopen";

export type MetadataDraft = { version: number; categoryId: string; reviewerId: string; originalReviewerId: string; amount: string; currency: string };
export type SharingDraft = { version: number; visibility: "workspace" | "restricted"; userIds: string[] };

/** The slice of a TanStack query the option lists need: data, failure flag and a way to retry. */
export type OptionsQuery<T> = { data: T[] | undefined; isError: boolean; refetch: () => unknown };

export function metadataSnapshot(data: Workspace): MetadataDraft {
  return { version: data.version, categoryId: data.category_id ?? "", reviewerId: data.assigned_reviewer_id ?? "", originalReviewerId: data.assigned_reviewer_id ?? "", amount: data.verified_amount ?? "", currency: data.currency ?? "" };
}

export function sharingSnapshot(data: Workspace): SharingDraft {
  return { version: data.version, visibility: data.visibility === "restricted" ? "restricted" : "workspace", userIds: data.grants.map(grant => grant.user_id) };
}
