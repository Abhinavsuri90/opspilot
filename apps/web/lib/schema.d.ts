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
    "/v1/actions": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** List Actions */
        get: operations["list_actions_v1_actions_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/v1/actions/summary": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /**
         * Actions Summary
         * @description Counts by status over the caller's visible documents; declared before /{action_id}.
         */
        get: operations["actions_summary_v1_actions_summary_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/v1/actions/{action_id}": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** Action Detail */
        get: operations["action_detail_v1_actions__action_id__get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/v1/actions/{action_id}/decision": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /** Decide Action */
        post: operations["decide_action_v1_actions__action_id__decision_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/v1/actions/{action_id}/retry": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /** Retry Action */
        post: operations["retry_action_v1_actions__action_id__retry_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/v1/exports": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** List Exports */
        get: operations["list_exports_v1_exports_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/v1/exports/{connector_id}/{month}.csv": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** Download Export */
        get: operations["download_export_v1_exports__connector_id___month__csv_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/v1/settings/policies": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** Read Policies */
        get: operations["read_policies_v1_settings_policies_get"];
        put?: never;
        /** Update Policies */
        post: operations["update_policies_v1_settings_policies_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/v1/settings/connectors": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** List Connectors */
        get: operations["list_connectors_v1_settings_connectors_get"];
        put?: never;
        /** Create Connector */
        post: operations["create_connector_v1_settings_connectors_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/v1/settings/connectors/{connector_id}": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /** Update Connector */
        post: operations["update_connector_v1_settings_connectors__connector_id__post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/v1/settings/connectors/{connector_id}/test": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /** Test Connector */
        post: operations["test_connector_v1_settings_connectors__connector_id__test_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/v1/settings/workflow": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** Read Workflow */
        get: operations["read_workflow_v1_settings_workflow_get"];
        put?: never;
        /** Update Workflow */
        post: operations["update_workflow_v1_settings_workflow_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/v1/settings/api-keys": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** List Api Keys */
        get: operations["list_api_keys_v1_settings_api_keys_get"];
        put?: never;
        /** Create Api Key */
        post: operations["create_api_key_v1_settings_api_keys_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/v1/settings/api-keys/{key_id}/revoke": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /** Revoke Api Key */
        post: operations["revoke_api_key_v1_settings_api_keys__key_id__revoke_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/v1/settings/email-inbox": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** Read Email Inbox */
        get: operations["read_email_inbox_v1_settings_email_inbox_get"];
        put?: never;
        /** Save Email Inbox */
        post: operations["save_email_inbox_v1_settings_email_inbox_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/v1/settings/email-inbox/test": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /** Test Email Inbox */
        post: operations["test_email_inbox_v1_settings_email_inbox_test_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/v1/metrics/overview": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /**
         * Metrics Overview
         * @description KPIs over the documents the caller may see.
         *
         *     ``days`` counts back from today's UTC date and every ``series`` point is a UTC calendar
         *     day; ``cost_per_document`` is null until LLM calls are metered.
         */
        get: operations["metrics_overview_v1_metrics_overview_get"];
        put?: never;
        post?: never;
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
        /** ActionDecisionRequest */
        ActionDecisionRequest: {
            /** Version */
            version: number;
            /**
             * Decision
             * @enum {string}
             */
            decision: "approve" | "reject";
            /**
             * Comment
             * @default
             */
            comment: string;
        };
        /** ActionDetail */
        ActionDetail: {
            /**
             * Id
             * Format: uuid
             */
            id: string;
            /**
             * Document Id
             * Format: uuid
             */
            document_id: string;
            /** Filename */
            filename: string;
            /** Destination */
            destination: string;
            /** Action Type */
            action_type: string;
            /** Connector Id */
            connector_id: string | null;
            /** Connector Name */
            connector_name: string | null;
            /** Status */
            status: string;
            /** Policy Mode */
            policy_mode: string;
            preview: components["schemas"]["DiffResponse"];
            /** Attempts */
            attempts: number;
            /** Next Attempt At */
            next_attempt_at: string | null;
            /** Error */
            error: string | null;
            /**
             * Proposed At
             * Format: date-time
             */
            proposed_at: string;
            /** Decided By Email */
            decided_by_email: string | null;
            /** Decided At */
            decided_at: string | null;
            /** Decision Comment */
            decision_comment: string;
            /** Executed At */
            executed_at: string | null;
            /** Version */
            version: number;
            /** Payload */
            payload: {
                [key: string]: string;
            };
            /** Result */
            result: {
                [key: string]: unknown;
            } | null;
            /** Attempt Log */
            attempt_log: components["schemas"]["AttemptResponse"][];
        };
        /** ActionRetryRequest */
        ActionRetryRequest: {
            /** Version */
            version: number;
        };
        /** ActionSummary */
        ActionSummary: {
            /**
             * Id
             * Format: uuid
             */
            id: string;
            /**
             * Document Id
             * Format: uuid
             */
            document_id: string;
            /** Filename */
            filename: string;
            /** Destination */
            destination: string;
            /** Action Type */
            action_type: string;
            /** Connector Id */
            connector_id: string | null;
            /** Connector Name */
            connector_name: string | null;
            /** Status */
            status: string;
            /** Policy Mode */
            policy_mode: string;
            preview: components["schemas"]["DiffResponse"];
            /** Attempts */
            attempts: number;
            /** Next Attempt At */
            next_attempt_at: string | null;
            /** Error */
            error: string | null;
            /**
             * Proposed At
             * Format: date-time
             */
            proposed_at: string;
            /** Decided By Email */
            decided_by_email: string | null;
            /** Decided At */
            decided_at: string | null;
            /** Decision Comment */
            decision_comment: string;
            /** Executed At */
            executed_at: string | null;
            /** Version */
            version: number;
        };
        /** ActionsSummary */
        ActionsSummary: {
            /** Counts */
            counts: {
                [key: string]: number;
            };
            /** Pending Approvals */
            pending_approvals: number;
            /** Dead Letters */
            dead_letters: number;
            /** Failed */
            failed: number;
        };
        /** ApiKeyCreate */
        ApiKeyCreate: {
            /** Name */
            name: string;
        };
        /** ApiKeyCreatedResponse */
        ApiKeyCreatedResponse: {
            /**
             * Id
             * Format: uuid
             */
            id: string;
            /** Name */
            name: string;
            /** Key Prefix */
            key_prefix: string;
            /** Scopes */
            scopes: string;
            /** Created By Email */
            created_by_email: string | null;
            /**
             * Created At
             * Format: date-time
             */
            created_at: string;
            /** Last Used At */
            last_used_at: string | null;
            /** Revoked At */
            revoked_at: string | null;
            /** Key */
            key: string;
        };
        /** ApiKeyResponse */
        ApiKeyResponse: {
            /**
             * Id
             * Format: uuid
             */
            id: string;
            /** Name */
            name: string;
            /** Key Prefix */
            key_prefix: string;
            /** Scopes */
            scopes: string;
            /** Created By Email */
            created_by_email: string | null;
            /**
             * Created At
             * Format: date-time
             */
            created_at: string;
            /** Last Used At */
            last_used_at: string | null;
            /** Revoked At */
            revoked_at: string | null;
        };
        /** AttemptResponse */
        AttemptResponse: {
            /** Attempt */
            attempt: number;
            /**
             * Started At
             * Format: date-time
             */
            started_at: string;
            /**
             * Finished At
             * Format: date-time
             */
            finished_at: string;
            /** Ok */
            ok: boolean;
            /** Response Summary */
            response_summary: string | null;
            /** Error */
            error: string | null;
        };
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
        /** ConnectionTestResponse */
        ConnectionTestResponse: {
            /** Ok */
            ok: boolean;
            /** Message */
            message: string;
            /**
             * Tested At
             * Format: date-time
             */
            tested_at: string;
        };
        /** ConnectorCreate */
        ConnectorCreate: {
            /** Name */
            name: string;
            /**
             * Connector Type
             * @enum {string}
             */
            connector_type: "webhook" | "csv_export" | "postgres_table" | "google_sheets";
            /** Config */
            config?: {
                [key: string]: unknown;
            };
            /** Credentials */
            credentials?: {
                [key: string]: unknown;
            } | null;
        };
        /** ConnectorResponse */
        ConnectorResponse: {
            /**
             * Id
             * Format: uuid
             */
            id: string;
            /** Name */
            name: string;
            /** Connector Type */
            connector_type: string;
            /** Config */
            config: {
                [key: string]: unknown;
            };
            /** Has Credentials */
            has_credentials: boolean;
            /** Active */
            active: boolean;
            /** Version */
            version: number;
            /**
             * Created At
             * Format: date-time
             */
            created_at: string;
            /**
             * Updated At
             * Format: date-time
             */
            updated_at: string;
            /** Last Test At */
            last_test_at: string | null;
            /** Last Test Ok */
            last_test_ok: boolean | null;
            /** Last Test Message */
            last_test_message: string | null;
            /** Capabilities */
            capabilities: {
                [key: string]: unknown;
            };
        };
        /** ConnectorUpdate */
        ConnectorUpdate: {
            /** Version */
            version: number;
            /** Name */
            name?: string | null;
            /** Config */
            config?: {
                [key: string]: unknown;
            } | null;
            /** Credentials */
            credentials?: {
                [key: string]: unknown;
            } | null;
            /** Active */
            active?: boolean | null;
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
        /** DiffResponse */
        DiffResponse: {
            /** Kind */
            kind: string;
            /** Title */
            title: string;
            /** Before */
            before: {
                [key: string]: unknown;
            } | null;
            /** After */
            after: {
                [key: string]: unknown;
            };
            /** Lines */
            lines: string[];
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
            /** Source */
            source: string;
            /** Source Ref */
            source_ref: string | null;
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
            /** Context Text */
            context_text: string | null;
            /** Near Duplicates */
            near_duplicates: components["schemas"]["NearDuplicateRef"][];
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
            /** Source */
            source: string;
            /** Source Ref */
            source_ref: string | null;
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
        /** EmailInboxResponse */
        EmailInboxResponse: {
            /** Backend */
            backend: string;
            /** Address */
            address: string;
            /** Config */
            config: {
                [key: string]: unknown;
            };
            /** Has Credentials */
            has_credentials: boolean;
            /** Active */
            active: boolean;
            /** Version */
            version: number;
            /**
             * Created At
             * Format: date-time
             */
            created_at: string;
            /**
             * Updated At
             * Format: date-time
             */
            updated_at: string;
            /** Last Polled At */
            last_polled_at: string | null;
            /** Next Poll At */
            next_poll_at: string | null;
            /** Last Error */
            last_error: string | null;
            /** Last Test At */
            last_test_at: string | null;
            /** Last Test Ok */
            last_test_ok: boolean | null;
            /** Last Test Message */
            last_test_message: string | null;
            /** Messages Processed */
            messages_processed: number;
            /** Documents Created */
            documents_created: number;
            /** Poll Interval Seconds */
            poll_interval_seconds: number;
        };
        /** EmailInboxUpdate */
        EmailInboxUpdate: {
            /** Version */
            version: number;
            /**
             * Backend
             * @enum {string}
             */
            backend: "imap" | "mailpit";
            /** Address */
            address?: string | null;
            /** Config */
            config?: {
                [key: string]: unknown;
            };
            /** Credentials */
            credentials?: {
                [key: string]: unknown;
            } | null;
            /**
             * Active
             * @default true
             */
            active: boolean;
        };
        /** ExportMonth */
        ExportMonth: {
            /**
             * Connector Id
             * Format: uuid
             */
            connector_id: string;
            /** Month */
            month: string;
            /** Path */
            path: string;
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
        /** InboxTestResponse */
        InboxTestResponse: {
            /** Ok */
            ok: boolean;
            /** Message */
            message: string;
            /**
             * Tested At
             * Format: date-time
             */
            tested_at: string;
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
        /** MetricsOverview */
        MetricsOverview: {
            range: components["schemas"]["MetricsRange"];
            /** Documents Processed */
            documents_processed: number;
            /** Auto Approve Rate */
            auto_approve_rate: number | null;
            /** Field Accuracy */
            field_accuracy: number | null;
            /** Median Time To Complete Minutes */
            median_time_to_complete_minutes: number | null;
            /** Review Queue Depth */
            review_queue_depth: number;
            /** Cost Per Document */
            cost_per_document: number | null;
            /** Hours Saved */
            hours_saved: number;
            /** Baseline Minutes */
            baseline_minutes: number;
            /** Series */
            series: components["schemas"]["SeriesPoint"][];
        };
        /** MetricsRange */
        MetricsRange: {
            /** Days */
            days: number;
            /**
             * Start
             * Format: date
             */
            start: string;
            /**
             * End
             * Format: date
             */
            end: string;
            /** Document Type */
            document_type: string | null;
        };
        /** NearDuplicateRef */
        NearDuplicateRef: {
            /**
             * Document Id
             * Format: uuid
             */
            document_id: string;
            /** Filename */
            filename: string;
            /** Document Type */
            document_type: string;
            /** Status */
            status: string;
            /**
             * Created At
             * Format: date-time
             */
            created_at: string;
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
        /** PoliciesResponse */
        PoliciesResponse: {
            /** Version */
            version: number;
            /** Kill Switch */
            kill_switch: boolean;
            /** Shadow Mode */
            shadow_mode: boolean;
            /** Policies */
            policies: {
                [key: string]: string;
            };
            /** Defaults From Config */
            defaults_from_config: {
                [key: string]: string;
            };
            /** Known Action Types */
            known_action_types: string[];
            /**
             * Updated At
             * Format: date-time
             */
            updated_at: string;
            /** Updated By Email */
            updated_by_email: string | null;
        };
        /** PoliciesUpdate */
        PoliciesUpdate: {
            /** Version */
            version: number;
            /** Kill Switch */
            kill_switch?: boolean | null;
            /** Shadow Mode */
            shadow_mode?: boolean | null;
            /** Policies */
            policies?: {
                [key: string]: "auto" | "needs_approval" | "forbidden";
            } | null;
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
            /**
             * Template
             * @default invoice
             * @enum {string}
             */
            template: "invoice" | "logistics";
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
        /** SeriesPoint */
        SeriesPoint: {
            /**
             * Day
             * Format: date
             */
            day: string;
            /** Documents */
            documents: number;
            /** Auto Approved */
            auto_approved: number;
            /** Needs Review */
            needs_review: number;
            /** Corrected Fields */
            corrected_fields: number;
            /** Total Fields */
            total_fields: number;
            /** Completed */
            completed: number;
            /** Review Minutes */
            review_minutes: number;
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
            kind: "audit" | "extraction" | "correction" | "review" | "comment" | "action";
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
            /** Source */
            source: string;
            /** Source Ref */
            source_ref: string | null;
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
        /** WorkflowResponse */
        WorkflowResponse: {
            /** Version */
            version: number;
            /** Config */
            config: {
                [key: string]: unknown;
            };
            /** Yaml */
            yaml: string;
            /**
             * Created At
             * Format: date-time
             */
            created_at: string;
        };
        /** WorkflowUpdate */
        WorkflowUpdate: {
            /** Base Version */
            base_version: number;
            /** Config */
            config?: {
                [key: string]: unknown;
            } | null;
            /** Yaml */
            yaml?: string | null;
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
            header?: {
                authorization?: string | null;
            };
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
            header?: {
                authorization?: string | null;
            };
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
            header?: {
                authorization?: string | null;
            };
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
            header?: {
                authorization?: string | null;
            };
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
            header?: {
                authorization?: string | null;
            };
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
            header?: {
                authorization?: string | null;
            };
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
            header?: {
                authorization?: string | null;
            };
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
            header?: {
                authorization?: string | null;
            };
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
            header?: {
                authorization?: string | null;
            };
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
            header?: {
                authorization?: string | null;
            };
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
            header?: {
                authorization?: string | null;
            };
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
            header?: {
                authorization?: string | null;
            };
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
            header?: {
                authorization?: string | null;
            };
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
            header?: {
                authorization?: string | null;
            };
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
            header?: {
                authorization?: string | null;
            };
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
            header?: {
                authorization?: string | null;
            };
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
    list_actions_v1_actions_get: {
        parameters: {
            query?: {
                status?: string | null;
                document_id?: string | null;
                offset?: number;
                limit?: number;
            };
            header?: {
                authorization?: string | null;
            };
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
                    "application/json": components["schemas"]["ActionSummary"][];
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
    actions_summary_v1_actions_summary_get: {
        parameters: {
            query?: never;
            header?: {
                authorization?: string | null;
            };
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
                    "application/json": components["schemas"]["ActionsSummary"];
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
    action_detail_v1_actions__action_id__get: {
        parameters: {
            query?: never;
            header?: {
                authorization?: string | null;
            };
            path: {
                action_id: string;
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
                    "application/json": components["schemas"]["ActionDetail"];
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
    decide_action_v1_actions__action_id__decision_post: {
        parameters: {
            query?: never;
            header?: {
                authorization?: string | null;
            };
            path: {
                action_id: string;
            };
            cookie?: {
                opspilot_session?: string | null;
            };
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["ActionDecisionRequest"];
            };
        };
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ActionDetail"];
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
    retry_action_v1_actions__action_id__retry_post: {
        parameters: {
            query?: never;
            header?: {
                authorization?: string | null;
            };
            path: {
                action_id: string;
            };
            cookie?: {
                opspilot_session?: string | null;
            };
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["ActionRetryRequest"];
            };
        };
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ActionDetail"];
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
    list_exports_v1_exports_get: {
        parameters: {
            query: {
                connector_id: string;
            };
            header?: {
                authorization?: string | null;
            };
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
                    "application/json": components["schemas"]["ExportMonth"][];
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
    download_export_v1_exports__connector_id___month__csv_get: {
        parameters: {
            query?: never;
            header?: {
                authorization?: string | null;
            };
            path: {
                connector_id: string;
                month: string;
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
    read_policies_v1_settings_policies_get: {
        parameters: {
            query?: never;
            header?: {
                authorization?: string | null;
            };
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
                    "application/json": components["schemas"]["PoliciesResponse"];
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
    update_policies_v1_settings_policies_post: {
        parameters: {
            query?: never;
            header?: {
                authorization?: string | null;
            };
            path?: never;
            cookie?: {
                opspilot_session?: string | null;
            };
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["PoliciesUpdate"];
            };
        };
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["PoliciesResponse"];
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
    list_connectors_v1_settings_connectors_get: {
        parameters: {
            query?: never;
            header?: {
                authorization?: string | null;
            };
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
                    "application/json": components["schemas"]["ConnectorResponse"][];
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
    create_connector_v1_settings_connectors_post: {
        parameters: {
            query?: never;
            header?: {
                authorization?: string | null;
            };
            path?: never;
            cookie?: {
                opspilot_session?: string | null;
            };
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["ConnectorCreate"];
            };
        };
        responses: {
            /** @description Successful Response */
            201: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ConnectorResponse"];
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
    update_connector_v1_settings_connectors__connector_id__post: {
        parameters: {
            query?: never;
            header?: {
                authorization?: string | null;
            };
            path: {
                connector_id: string;
            };
            cookie?: {
                opspilot_session?: string | null;
            };
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["ConnectorUpdate"];
            };
        };
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ConnectorResponse"];
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
    test_connector_v1_settings_connectors__connector_id__test_post: {
        parameters: {
            query?: never;
            header?: {
                authorization?: string | null;
            };
            path: {
                connector_id: string;
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
                    "application/json": components["schemas"]["ConnectionTestResponse"];
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
    read_workflow_v1_settings_workflow_get: {
        parameters: {
            query?: never;
            header?: {
                authorization?: string | null;
            };
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
                    "application/json": components["schemas"]["WorkflowResponse"];
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
    update_workflow_v1_settings_workflow_post: {
        parameters: {
            query?: never;
            header?: {
                authorization?: string | null;
            };
            path?: never;
            cookie?: {
                opspilot_session?: string | null;
            };
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["WorkflowUpdate"];
            };
        };
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["WorkflowResponse"];
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
    list_api_keys_v1_settings_api_keys_get: {
        parameters: {
            query?: never;
            header?: {
                authorization?: string | null;
            };
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
                    "application/json": components["schemas"]["ApiKeyResponse"][];
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
    create_api_key_v1_settings_api_keys_post: {
        parameters: {
            query?: never;
            header?: {
                authorization?: string | null;
            };
            path?: never;
            cookie?: {
                opspilot_session?: string | null;
            };
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["ApiKeyCreate"];
            };
        };
        responses: {
            /** @description Successful Response */
            201: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ApiKeyCreatedResponse"];
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
    revoke_api_key_v1_settings_api_keys__key_id__revoke_post: {
        parameters: {
            query?: never;
            header?: {
                authorization?: string | null;
            };
            path: {
                key_id: string;
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
                    "application/json": components["schemas"]["ApiKeyResponse"];
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
    read_email_inbox_v1_settings_email_inbox_get: {
        parameters: {
            query?: never;
            header?: {
                authorization?: string | null;
            };
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
                    "application/json": components["schemas"]["EmailInboxResponse"] | null;
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
    save_email_inbox_v1_settings_email_inbox_post: {
        parameters: {
            query?: never;
            header?: {
                authorization?: string | null;
            };
            path?: never;
            cookie?: {
                opspilot_session?: string | null;
            };
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["EmailInboxUpdate"];
            };
        };
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["EmailInboxResponse"];
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
    test_email_inbox_v1_settings_email_inbox_test_post: {
        parameters: {
            query?: never;
            header?: {
                authorization?: string | null;
            };
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
                    "application/json": components["schemas"]["InboxTestResponse"];
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
    metrics_overview_v1_metrics_overview_get: {
        parameters: {
            query?: {
                days?: number;
                document_type?: string | null;
            };
            header?: {
                authorization?: string | null;
            };
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
                    "application/json": components["schemas"]["MetricsOverview"];
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
            header?: {
                authorization?: string | null;
            };
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
                document_type?: string | null;
                source?: string | null;
            };
            header?: {
                authorization?: string | null;
            };
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
            header?: {
                authorization?: string | null;
            };
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
            header?: {
                authorization?: string | null;
            };
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
            header?: {
                authorization?: string | null;
            };
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
            header?: {
                authorization?: string | null;
            };
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
