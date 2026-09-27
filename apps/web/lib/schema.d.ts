export interface paths {
    "/v1/organizations": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** Organizations */
        get: operations["organizations_v1_organizations_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/v1/auth/register-organization": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /** Register Organization */
        post: operations["register_organization_v1_auth_register_organization_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/v1/auth/join-organization": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /** Join Organization */
        post: operations["join_organization_v1_auth_join_organization_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/v1/organization/members": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** Organization Members */
        get: operations["organization_members_v1_organization_members_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/v1/organization/members/{user_id}/decision": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /** Decide Membership */
        post: operations["decide_membership_v1_organization_members__user_id__decision_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/v1/categories": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** Categories */
        get: operations["categories_v1_categories_get"];
        put?: never;
        /** Create Category */
        post: operations["create_category_v1_categories_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/v1/categories/{category_id}": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /** Update Category */
        post: operations["update_category_v1_categories__category_id__post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/v1/organization/collaborators": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** Collaborators */
        get: operations["collaborators_v1_organization_collaborators_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/v1/documents/{document_id}/workspace": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** Document Workspace */
        get: operations["document_workspace_v1_documents__document_id__workspace_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/v1/documents/{document_id}/metadata": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /** Update Metadata */
        post: operations["update_metadata_v1_documents__document_id__metadata_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/v1/documents/{document_id}/comments": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /** Add Comment */
        post: operations["add_comment_v1_documents__document_id__comments_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/v1/documents/{document_id}/review": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /** Review Invoice */
        post: operations["review_invoice_v1_documents__document_id__review_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/v1/documents/{document_id}/fields/{field_id}": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /** Correct Field */
        post: operations["correct_field_v1_documents__document_id__fields__field_id__post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/v1/review/queue": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** Review Queue */
        get: operations["review_queue_v1_review_queue_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/v1/documents/{document_id}/timeline": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** Document Timeline */
        get: operations["document_timeline_v1_documents__document_id__timeline_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/v1/documents/{document_id}/sharing": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /** Update Sharing */
        post: operations["update_sharing_v1_documents__document_id__sharing_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/v1/workspace/summary": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** Workspace Summary */
        get: operations["workspace_summary_v1_workspace_summary_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/v1/workspace/questions": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /** Workspace Question */
        post: operations["workspace_question_v1_workspace_questions_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/healthz": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** Healthz */
        get: operations["healthz_healthz_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/readyz": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** Readyz */
        get: operations["readyz_readyz_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/v1/auth/login": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /** Login */
        post: operations["login_v1_auth_login_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/v1/auth/logout": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /** Logout */
        post: operations["logout_v1_auth_logout_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/v1/auth/me": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** Me */
        get: operations["me_v1_auth_me_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/v1/documents": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** Documents */
        get: operations["documents_v1_documents_get"];
        put?: never;
        /** Upload Document */
        post: operations["upload_document_v1_documents_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/v1/documents/{document_id}": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** Document Detail */
        get: operations["document_detail_v1_documents__document_id__get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/v1/documents/{document_id}/retry": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /** Retry Document */
        post: operations["retry_document_v1_documents__document_id__retry_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/v1/documents/{document_id}/file": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** Document File */
        get: operations["document_file_v1_documents__document_id__file_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
}
export type webhooks = Record<string, never>;
export interface components {
    schemas: {
        /** Body_upload_document_v1_documents_post */
        Body_upload_document_v1_documents_post: {
            /** File */
            file: Blob;
        };
        /** Capabilities */
        Capabilities: {
            /** Can Edit */
            can_edit: boolean;
            /** Can Review */
            can_review: boolean;
            /** Can Share */
            can_share: boolean;
            /** Can Assign */
            can_assign: boolean;
            /** Can Comment */
            can_comment: boolean;
        };
        /** CategoryCount */
        CategoryCount: {
            /** Id */
            id: string | null;
            /** Name */
            name: string;
            /** Document Count */
            document_count: number;
            /** Status Counts */
            status_counts?: {
                [key: string]: number;
            };
            /** Amounts By Currency */
            amounts_by_currency?: components["schemas"]["CurrencyTotal"][];
            /**
             * Excluded Amount Count
             * @default 0
             */
            excluded_amount_count: number;
        };
        /** CategoryCreate */
        CategoryCreate: {
            /** Name */
            name: string;
            /**
             * Description
             * @default
             */
            description: string;
        };
        /** CategoryResponse */
        CategoryResponse: {
            /**
             * Id
             * Format: uuid
             */
            id: string;
            /** Name */
            name: string;
            /** Description */
            description: string;
            /** Active */
            active: boolean;
            /** Version */
            version: number;
        };
        /** CategoryUpdate */
        CategoryUpdate: {
            /** Version */
            version: number;
            /** Name */
            name?: string | null;
            /** Description */
            description?: string | null;
            /** Active */
            active?: boolean | null;
        };
        /** Citation */
        Citation: {
            /**
             * Document Id
             * Format: uuid
             */
            document_id: string;
            /** Filename */
            filename: string;
            /** Field */
            field: string;
            /** Value */
            value: string;
            /** Evidence */
            evidence: string;
            /** Page Number */
            page_number: number;
        };
        /** CollaboratorResponse */
        CollaboratorResponse: {
            /**
             * User Id
             * Format: uuid
             */
            user_id: string;
            /** Email */
            email: string;
            /** Role */
            role: string;
        };
        /** CommentCreate */
        CommentCreate: {
            /** Body */
            body: string;
        };
        /** CommentResponse */
        CommentResponse: {
            /**
             * Id
             * Format: uuid
             */
            id: string;
            /**
             * Author User Id
             * Format: uuid
             */
            author_user_id: string;
            /** Author Email */
            author_email: string;
            /** Body */
            body: string;
            /**
             * Created At
             * Format: date-time
             */
            created_at: string;
        };
        /** CurrencyTotal */
        CurrencyTotal: {
            /** Currency */
            currency: string;
            /** Total */
            total: string;
            /** Pending Review */
            pending_review: string;
            /** Approved */
            approved: string;
            /** Rejected */
            rejected: string;
        };
        /** DocumentDetail */
        DocumentDetail: {
            /**
             * Id
             * Format: uuid
             */
            id: string;
            /** Filename */
            filename: string;
            /** Status */
            status: string;
            /** Document Type */
            document_type: string;
            /** Size Bytes */
            size_bytes: number;
            /** Workflow Config Version */
            workflow_config_version: number;
            /** Failure Reason */
            failure_reason: string | null;
            /** Flagged Count */
            flagged_count: number;
            /**
             * Created At
             * Format: date-time
             */
            created_at: string;
            /** Provider */
            provider: string | null;
            /** Version */
            version: number;
            /** Fields */
            fields: components["schemas"]["FieldDetail"][];
            /** Rule Results */
            rule_results: components["schemas"]["RuleResultResponse"][];
            review_task: components["schemas"]["ReviewTaskResponse"] | null;
        };
        /** DocumentSummary */
        DocumentSummary: {
            /**
             * Id
             * Format: uuid
             */
            id: string;
            /** Filename */
            filename: string;
            /** Status */
            status: string;
            /** Document Type */
            document_type: string;
            /** Size Bytes */
            size_bytes: number;
            /** Workflow Config Version */
            workflow_config_version: number;
            /** Failure Reason */
            failure_reason: string | null;
            /** Flagged Count */
            flagged_count: number;
            /**
             * Created At
             * Format: date-time
             */
            created_at: string;
        };
        /** FieldCorrectionRequest */
        FieldCorrectionRequest: {
            /** Version */
            version: number;
            /**
             * Action
             * @enum {string}
             */
            action: "accept" | "edit";
            /** Value */
            value?: string | null;
        };
        /** FieldDetail */
        FieldDetail: {
            /**
             * Id
             * Format: uuid
             */
            id: string;
            /** Name */
            name: string;
            /** Label */
            label: string;
            /** Field Type */
            field_type: string;
            /** Required */
            required: boolean;
            /** Value */
            value: string;
            /** Current Value */
            current_value: string;
            /** Evidence */
            evidence: string;
            /** Page Number */
            page_number: number;
            /** Confidence */
            confidence: number;
            /** Threshold */
            threshold: number;
            /**
             * Status
             * @enum {string}
             */
            status: "auto" | "needs_review" | "corrected" | "approved";
            /** Signals */
            signals: {
                [key: string]: number | null;
            };
            /** Reasons */
            reasons: string[];
            /** Corrected By Email */
            corrected_by_email: string | null;
        };
        /** GrantResponse */
        GrantResponse: {
            /**
             * User Id
             * Format: uuid
             */
            user_id: string;
            /** Email */
            email: string;
        };
        /** HTTPValidationError */
        HTTPValidationError: {
            /** Detail */
            detail?: components["schemas"]["ValidationError"][];
        };
        /** JoinOrganizationRequest */
        JoinOrganizationRequest: {
            /**
             * Email
             * Format: email
             */
            email: string;
            /** Password */
            password: string;
            /** Org Slug */
            org_slug: string;
            /**
             * Requested Role
             * @default member
             * @enum {string}
             */
            requested_role: "member" | "reviewer";
        };
        /** JoinOrganizationResponse */
        JoinOrganizationResponse: {
            /**
             * Org Id
             * Format: uuid
             */
            org_id: string;
            /** Org Name */
            org_name: string;
            /**
             * Status
             * @default pending
             * @constant
             */
            status: "pending";
            /**
             * Message
             * @default Your request was submitted. An organization admin must approve your access.
             */
            message: string;
        };
        /** LoginRequest */
        LoginRequest: {
            /** Org Slug */
            org_slug: string;
            /**
             * Email
             * Format: email
             */
            email: string;
            /** Password */
            password: string;
        };
        /** MemberResponse */
        MemberResponse: {
            /**
             * Id
             * Format: uuid
             */
            id: string;
            /**
             * User Id
             * Format: uuid
             */
            user_id: string;
            /** Email */
            email: string;
            /** Role */
            role: string;
            /** Status */
            status: string;
            /** Requested Role */
            requested_role: string;
            /**
             * Created At
             * Format: date-time
             */
            created_at: string;
            /** Decided At */
            decided_at: string | null;
        };
        /** MembershipDecisionRequest */
        MembershipDecisionRequest: {
            /**
             * Decision
             * @enum {string}
             */
            decision: "approved" | "rejected" | "suspended";
            /** Role */
            role?: ("member" | "reviewer" | "viewer") | null;
        };
        /** MetadataUpdate */
        MetadataUpdate: {
            /** Version */
            version: number;
            /** Category Id */
            category_id?: string | null;
            /** Assigned Reviewer Id */
            assigned_reviewer_id?: string | null;
            /** Verified Amount */
            verified_amount?: number | string | null;
            /** Currency */
            currency?: string | null;
        };
        /** OrganizationResponse */
        OrganizationResponse: {
            /**
             * Id
             * Format: uuid
             */
            id: string;
            /** Slug */
            slug: string;
            /** Name */
            name: string;
        };
        /** QuestionRequest */
        QuestionRequest: {
            /** Question */
            question: string;
            /** Document Id */
            document_id?: string | null;
            /** Category Id */
            category_id?: string | null;
        };
        /** QuestionResponse */
        QuestionResponse: {
            /** Supported */
            supported: boolean;
            /** Answer */
            answer: string;
            /**
             * As Of
             * Format: date-time
             */
            as_of: string;
            /** Citations */
            citations?: components["schemas"]["Citation"][];
            summary?: components["schemas"]["WorkspaceSummary"] | null;
        };
        /** QueueItem */
        QueueItem: {
            /**
             * Document Id
             * Format: uuid
             */
            document_id: string;
            /** Filename */
            filename: string;
            /** Document Type */
            document_type: string;
            /** Vendor */
            vendor: string | null;
            /** Total */
            total: string | null;
            /** Currency */
            currency: string | null;
            /** Flagged Count */
            flagged_count: number;
            /** Opened At */
            opened_at: string | null;
            /** Due At */
            due_at: string | null;
            /** Overdue */
            overdue: boolean;
            /** Assigned Reviewer Id */
            assigned_reviewer_id: string | null;
            /** Assigned Reviewer Email */
            assigned_reviewer_email: string | null;
            /**
             * Created At
             * Format: date-time
             */
            created_at: string;
        };
        /** RegisterOrganizationRequest */
        RegisterOrganizationRequest: {
            /**
             * Email
             * Format: email
             */
            email: string;
            /** Password */
            password: string;
            /** Org Slug */
            org_slug: string;
            /** Org Name */
            org_name: string;
            /**
             * Default Currency
             * @default USD
             */
            default_currency: string;
        };
        /** ReviewRequest */
        ReviewRequest: {
            /** Version */
            version: number;
            /**
             * Decision
             * @enum {string}
             */
            decision: "approve" | "reject" | "reopen";
            /**
             * Comment
             * @default
             */
            comment: string;
        };
        /** ReviewResponse */
        ReviewResponse: {
            /**
             * Id
             * Format: uuid
             */
            id: string;
            /**
             * Actor User Id
             * Format: uuid
             */
            actor_user_id: string;
            /** Actor Email */
            actor_email: string;
            /** Decision */
            decision: string;
            /** Comment */
            comment: string;
            /**
             * Created At
             * Format: date-time
             */
            created_at: string;
        };
        /** ReviewTaskResponse */
        ReviewTaskResponse: {
            /**
             * Opened At
             * Format: date-time
             */
            opened_at: string;
            /**
             * Due At
             * Format: date-time
             */
            due_at: string;
            /** Sla Minutes */
            sla_minutes: number;
            /** Completed At */
            completed_at: string | null;
            /** Outcome */
            outcome: string | null;
            /** Overdue */
            overdue: boolean;
        };
        /** RuleResultResponse */
        RuleResultResponse: {
            /** Name */
            name: string;
            /** Expression */
            expression: string;
            /** Passed */
            passed: boolean | null;
            /** Message */
            message: string;
        };
        /** SessionResponse */
        SessionResponse: {
            /**
             * User Id
             * Format: uuid
             */
            user_id: string;
            /** Email */
            email: string;
            /**
             * Org Id
             * Format: uuid
             */
            org_id: string;
            /** Org Name */
            org_name: string;
            /** Org Slug */
            org_slug: string;
            /** Default Currency */
            default_currency: string;
            /** Role */
            role: string;
        };
        /** SharingUpdate */
        SharingUpdate: {
            /** Version */
            version: number;
            /**
             * Visibility
             * @enum {string}
             */
            visibility: "workspace" | "restricted";
            /** User Ids */
            user_ids?: string[];
        };
        /** TimelineEntry */
        TimelineEntry: {
            /**
             * At
             * Format: date-time
             */
            at: string;
            /**
             * Kind
             * @enum {string}
             */
            kind: "audit" | "extraction" | "correction" | "review" | "comment";
            /** Event Type */
            event_type: string;
            /** Actor Email */
            actor_email: string | null;
            /** Summary */
            summary: string;
            /** Detail */
            detail: {
                [key: string]: unknown;
            };
        };
        /** UploadResponse */
        UploadResponse: {
            /**
             * Id
             * Format: uuid
             */
            id: string;
            /** Filename */
            filename: string;
            /** Status */
            status: string;
            /** Document Type */
            document_type: string;
            /** Size Bytes */
            size_bytes: number;
            /** Workflow Config Version */
            workflow_config_version: number;
            /** Failure Reason */
            failure_reason: string | null;
            /** Flagged Count */
            flagged_count: number;
            /**
             * Created At
             * Format: date-time
             */
            created_at: string;
            /** Duplicate */
            duplicate: boolean;
        };
        /** ValidationError */
        ValidationError: {
            /** Location */
            loc: (string | number)[];
            /** Message */
            msg: string;
            /** Error Type */
            type: string;
            /** Input */
            input?: unknown;
            /** Context */
            ctx?: Record<string, never>;
        };
        /** WorkspaceResponse */
        WorkspaceResponse: {
            /**
             * Document Id
             * Format: uuid
             */
            document_id: string;
            /** Version */
            version: number;
            /** Category Id */
            category_id: string | null;
            /** Assigned Reviewer Id */
            assigned_reviewer_id: string | null;
            /** Verified Amount */
            verified_amount: string | null;
            /** Currency */
            currency: string | null;
            /** Verified Source */
            verified_source: ("reviewer" | "derived") | null;
            /** Visibility */
            visibility: string;
            /** Comments */
            comments: components["schemas"]["CommentResponse"][];
            /** Grants */
            grants: components["schemas"]["GrantResponse"][];
            /** Reviews */
            reviews: components["schemas"]["ReviewResponse"][];
            capabilities: components["schemas"]["Capabilities"];
        };
        /** WorkspaceSummary */
        WorkspaceSummary: {
            /** Total Documents */
            total_documents: number;
            /** Status Counts */
            status_counts: {
                [key: string]: number;
            };
            /** Amounts By Currency */
            amounts_by_currency: components["schemas"]["CurrencyTotal"][];
            /** Excluded Amount Count */
            excluded_amount_count: number;
            /** Categories */
            categories: components["schemas"]["CategoryCount"][];
            /**
             * Scope
             * @default all_accessible_documents
             * @constant
             */
            scope: "all_accessible_documents";
        };
    };
    responses: never;
    parameters: never;
    requestBodies: never;
    headers: never;
    pathItems: never;
}
export type $defs = Record<string, never>;
export interface operations {
    organizations_v1_organizations_get: {
        parameters: {
            query?: {
                search?: string;
            };
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["OrganizationResponse"][];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    register_organization_v1_auth_register_organization_post: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["RegisterOrganizationRequest"];
            };
        };
        responses: {
            /** @description Successful Response */
            201: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["SessionResponse"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    join_organization_v1_auth_join_organization_post: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["JoinOrganizationRequest"];
            };
        };
        responses: {
            /** @description Successful Response */
            201: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["JoinOrganizationResponse"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    organization_members_v1_organization_members_get: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: {
                opspilot_session?: string | null;
            };
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["MemberResponse"][];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    decide_membership_v1_organization_members__user_id__decision_post: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                user_id: string;
            };
            cookie?: {
                opspilot_session?: string | null;
            };
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["MembershipDecisionRequest"];
            };
        };
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["MemberResponse"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    categories_v1_categories_get: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: {
                opspilot_session?: string | null;
            };
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["CategoryResponse"][];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    create_category_v1_categories_post: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: {
                opspilot_session?: string | null;
            };
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["CategoryCreate"];
            };
        };
        responses: {
            /** @description Successful Response */
            201: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["CategoryResponse"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    update_category_v1_categories__category_id__post: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                category_id: string;
            };
            cookie?: {
                opspilot_session?: string | null;
            };
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["CategoryUpdate"];
            };
        };
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["CategoryResponse"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    collaborators_v1_organization_collaborators_get: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: {
                opspilot_session?: string | null;
            };
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["CollaboratorResponse"][];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    document_workspace_v1_documents__document_id__workspace_get: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                document_id: string;
            };
            cookie?: {
                opspilot_session?: string | null;
            };
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["WorkspaceResponse"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    update_metadata_v1_documents__document_id__metadata_post: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                document_id: string;
            };
            cookie?: {
                opspilot_session?: string | null;
            };
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["MetadataUpdate"];
            };
        };
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["WorkspaceResponse"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    add_comment_v1_documents__document_id__comments_post: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                document_id: string;
            };
            cookie?: {
                opspilot_session?: string | null;
            };
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["CommentCreate"];
            };
        };
        responses: {
            /** @description Successful Response */
            201: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["WorkspaceResponse"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    review_invoice_v1_documents__document_id__review_post: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                document_id: string;
            };
            cookie?: {
                opspilot_session?: string | null;
            };
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["ReviewRequest"];
            };
        };
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["WorkspaceResponse"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    correct_field_v1_documents__document_id__fields__field_id__post: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                document_id: string;
                field_id: string;
            };
            cookie?: {
                opspilot_session?: string | null;
            };
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["FieldCorrectionRequest"];
            };
        };
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["DocumentDetail"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    review_queue_v1_review_queue_get: {
        parameters: {
            query?: {
                document_type?: string | null;
                vendor?: string | null;
                max_age_hours?: number | null;
                assigned?: "me" | "unassigned" | "all";
                offset?: number;
                limit?: number;
            };
            header?: never;
            path?: never;
            cookie?: {
                opspilot_session?: string | null;
            };
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["QueueItem"][];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    document_timeline_v1_documents__document_id__timeline_get: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                document_id: string;
            };
            cookie?: {
                opspilot_session?: string | null;
            };
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["TimelineEntry"][];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    update_sharing_v1_documents__document_id__sharing_post: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                document_id: string;
            };
            cookie?: {
                opspilot_session?: string | null;
            };
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["SharingUpdate"];
            };
        };
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["WorkspaceResponse"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    workspace_summary_v1_workspace_summary_get: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: {
                opspilot_session?: string | null;
            };
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["WorkspaceSummary"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    workspace_question_v1_workspace_questions_post: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: {
                opspilot_session?: string | null;
            };
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["QuestionRequest"];
            };
        };
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["QuestionResponse"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    healthz_healthz_get: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": {
                        [key: string]: string;
                    };
                };
            };
        };
    };
    readyz_readyz_get: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": {
                        [key: string]: string;
                    };
                };
            };
        };
    };
    login_v1_auth_login_post: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["LoginRequest"];
            };
        };
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["SessionResponse"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    logout_v1_auth_logout_post: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            204: {
                headers: {
                    [name: string]: unknown;
                };
                content?: never;
            };
        };
    };
    me_v1_auth_me_get: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: {
                opspilot_session?: string | null;
            };
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["SessionResponse"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    documents_v1_documents_get: {
        parameters: {
            query?: {
                offset?: number;
                limit?: number;
                category_id?: string | null;
                q?: string | null;
                status?: string | null;
            };
            header?: never;
            path?: never;
            cookie?: {
                opspilot_session?: string | null;
            };
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["DocumentSummary"][];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    upload_document_v1_documents_post: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: {
                opspilot_session?: string | null;
            };
        };
        requestBody: {
            content: {
                "multipart/form-data": components["schemas"]["Body_upload_document_v1_documents_post"];
            };
        };
        responses: {
            /** @description Successful Response */
            202: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["UploadResponse"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    document_detail_v1_documents__document_id__get: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                document_id: string;
            };
            cookie?: {
                opspilot_session?: string | null;
            };
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["DocumentDetail"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    retry_document_v1_documents__document_id__retry_post: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                document_id: string;
            };
            cookie?: {
                opspilot_session?: string | null;
            };
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            202: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["DocumentSummary"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    document_file_v1_documents__document_id__file_get: {
        parameters: {
            query?: {
                download?: boolean;
            };
            header?: never;
            path: {
                document_id: string;
            };
            cookie?: {
                opspilot_session?: string | null;
            };
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content?: never;
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
}
