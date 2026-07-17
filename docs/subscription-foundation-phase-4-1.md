# DataPilot Phase 4.1 Subscription Foundation

## Verdict

Phase 4.1 establishes a provider-neutral subscription foundation. Stripe, checkout, customer portal, webhooks, invoices, and payment state are intentionally out of scope for this phase.

## Current Domain Audit

- Authentication is JWT based with `Authorization: Bearer` headers and optional `X-Workspace-ID`.
- Workspaces are owned by users through `Workspace.owner_id` and membership is enforced by `WorkspaceMember` roles.
- Guests remain separate through `GuestSession` and keep guest-only usage counters.
- Existing usage enforcement is called through `CallerContext.check_limit()` and `CallerContext.increment_usage()`.
- Existing workspace plan hints live on `Workspace.plan_tier`; Phase 4.1 adds `workspace_subscriptions` as the durable subscription state.
- Existing analytics usage lives in `usage_stats`; Phase 4.1 keeps compatibility and adds append-only `usage_records` for foundation-level tracking.

## Data Model

- `plans`: commercial plan metadata, pricing placeholders, public/admin flags, trial duration, and legacy limit columns.
- `features`: central feature registry.
- `plan_features`: plan-to-feature enablement matrix.
- `plan_limits`: plan-to-metric limit matrix.
- `workspace_subscriptions`: current workspace subscription, status, previous/pending plan, renewal, cancellation, trial, and grace-period dates.
- `usage_records`: append-only usage events for metrics that are not covered by legacy counters.
- `quotas`: reserved materialized quota table for durable quota snapshots.
- `trials`: trial lifecycle records.
- `subscription_history`: status and plan history for upgrades, cancellations, promotional grants, and future provider events.

## Plans

Seeded plans are:

- Free: limited evaluation plan.
- Pro: individual paid-tier foundation.
- Team: collaborative paid-tier foundation.
- Enterprise: inactive/public-placeholder custom plan.

The old `business` plan ID is treated as a historical alias if it exists and is disabled by the seeder.

## Feature Flags

Feature checks are centralized in `core.subscriptions.can_use_feature()`.

Supported keys:

- `can_export_pdf`
- `can_forecast`
- `can_generate_report`
- `can_use_multiple_datasets`
- `can_invite_members`
- `can_use_custom_api_key`
- `can_schedule_reports`
- `can_access_priority_support`

## Quota System

Quota enforcement is centralized in `core.subscriptions.enforce_quota()`. Existing analytics endpoints continue to call `caller.check_limit()` and therefore use the new layer without route-level duplicate logic.

Tracked metrics include uploads, datasets, reports, AI prompts, storage, exports, workspace count, member count, charts, API usage, and legacy query counts.

## Trial System

New workspaces receive a subscription record and a 14-day trial when subscription state is first requested. Trial status is refreshed by date rules and exposed to the frontend through the subscription summary endpoint.

## API

Provider-neutral endpoints:

- `GET /billing/current`
- `GET /billing/plans`
- `GET /billing/usage`
- `GET /billing/quota`
- `GET /billing/limits`
- `GET /billing/features`
- `GET /billing/features/{feature_key}`
- `GET /billing/status`
- `GET /billing/trial`
- `POST /billing/admin/plans/seed`
- `POST /billing/admin/plans/{plan_id}`
- `PATCH /billing/admin/plans/{plan_id}/disable`
- `POST /billing/admin/subscriptions/grant`

Payment endpoints are intentionally absent.

## Remaining Work Before Stripe

- Map provider products/prices onto existing `plans`.
- Add checkout creation as a thin adapter that calls `grant_subscription()` or a future provider-event transition.
- Add webhook ingestion that writes `subscription_history` and updates `workspace_subscriptions`.
- Add invoice/customer portal UI in Phase 4.2.
- Add operational reconciliation jobs for provider state.
