import { api } from "@/lib/api";
import { apiErrorMessage } from "@/lib/errors";
import type { Decision, MetadataDraft, SharingDraft, Workspace } from "./types";

// Each kind of save carries exactly the data it needs, so no branch has to
// assume a field that another branch provided. The review decision carries its
// own version: the split view takes it from the freshest DocumentDetail.
export type SaveInput =
  | { action: "metadata"; metadata: MetadataDraft }
  | { action: "comments"; body: string }
  | { action: "review"; decision: Decision; comment: string; version: number }
  | { action: "sharing"; sharing: SharingDraft };

export type SaveResponse = { data?: Workspace; error?: unknown; response: Response };

export function saveMessage(error: unknown, status: number): string {
  if (status === 409) return "This invoice changed or the action is unavailable. Refresh the invoice and try again.";
  return apiErrorMessage(error, status, "Could not save this change. Please try again.");
}

export function sendSave(documentId: string, current: Workspace, input: SaveInput): Promise<SaveResponse> {
  const params = { path: { document_id: documentId } };
  switch (input.action) {
    case "metadata": {
      const { metadata } = input;
      return api.POST("/v1/documents/{document_id}/metadata", { params, body: {
        version: metadata.version,
        category_id: metadata.categoryId || null,
        verified_amount: metadata.amount || null,
        currency: metadata.currency.toUpperCase() || null,
        ...(current.capabilities.can_assign && metadata.reviewerId !== metadata.originalReviewerId ? { assigned_reviewer_id: metadata.reviewerId || null } : {}),
      } });
    }
    case "comments":
      return api.POST("/v1/documents/{document_id}/comments", { params, body: { body: input.body } });
    case "review":
      return api.POST("/v1/documents/{document_id}/review", { params, body: { version: input.version, decision: input.decision, comment: input.comment } });
    case "sharing":
      return api.POST("/v1/documents/{document_id}/sharing", { params, body: { version: input.sharing.version, visibility: input.sharing.visibility, user_ids: input.sharing.userIds } });
  }
}
