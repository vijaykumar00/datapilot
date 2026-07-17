# DataPilot Phase 4.3 Billing UI

Phase 4.3 adds the frontend billing and usage experience on top of the provider-neutral subscription foundation and Stripe adapter.

## Architecture

- Backend remains authoritative for plans, subscriptions, trials, usage, quotas, features, payment status, and portal availability.
- The browser uses `frontend/src/lib/billingClient.js` for all billing API calls.
- Stripe Checkout and Customer Portal URLs are created by backend endpoints only.
- The frontend never stores Stripe secret keys, webhook secrets, Stripe price IDs, or authoritative plan limits.

## Frontend State Mapping

`/billing/current` drives the workspace billing page:

- `subscription.plan_id` and `plan.name` display the current plan.
- `subscription.status` and `billing.payment_status` map to user-facing labels.
- `trial.active`, `trial.ends_at`, and `trial.expired` drive trial messaging.
- `subscription.current_period_end` and `subscription.renews_at` drive renewal and reset dates.
- `subscription.cancel_at_period_end` and `subscription.canceled_at` drive cancellation messaging.
- `usage`, `limits`, and `remaining_quota` drive quota meters.
- `billing.portal_available` controls Customer Portal actions.

## Checkout Flow

1. User selects an upgrade or plan action.
2. Frontend calls `POST /billing/checkout`.
3. Backend validates workspace membership, internal plan mapping, duplicate subscription rules, and Stripe configuration.
4. Frontend redirects only to the backend-returned Checkout URL after local URL safety validation.
5. On return, the UI shows a neutral processing state and refreshes subscription data.
6. Webhooks remain the source of truth; the frontend does not activate plans after redirect.

## Customer Portal Flow

1. User clicks a billing management action.
2. Frontend calls `POST /billing/portal`.
3. Backend creates the Stripe Billing Portal session for the workspace customer.
4. Frontend redirects only to the backend-returned portal URL.
5. Payment methods, invoices, cancellation, resume, upgrades, and downgrades stay in Stripe Portal.

## Usage And Quota Presentation

The billing page displays:

- AI prompts
- Analytics queries
- Uploads
- Datasets
- Reports
- Exports
- Storage
- Charts
- Workspace members
- API usage

Each row shows used amount, plan limit, remaining amount, percent consumed, and a text status for unlimited, normal, near-limit, or exhausted states.

## Feature-Gating UX

The reusable upgrade notice preserves the user's context and routes users toward checkout or the Customer Portal. Backend quota and entitlement checks remain mandatory; hiding or showing buttons is only a presentation layer.

## Error State Mapping

- Authentication required: prompt the user to sign in.
- Duplicate or existing subscription: show backend guidance and recommend portal management.
- Portal unavailable: disable portal actions and show a clear message.
- Checkout cancelled: show neutral cancellation messaging without changing subscription state.
- Webhook pending: show processing state and bounded refresh.
- Stripe outage or backend failure: show a non-sensitive billing service error.

## Security Boundaries

- No Stripe secret values are included in frontend source or build verification.
- No direct browser calls are made to Stripe APIs.
- Checkout and portal redirects come only from backend-generated URLs.
- Workspace context is supplied through authenticated headers.
- Plan limits and subscription status are never trusted from client input.

## Test Coverage

- Backend flaky query-history regression fixed by replacing timestamp-based message IDs with UUIDs.
- Backend discovery passed repeatedly after the fix.
- Frontend source tests cover billing client endpoints, pricing integration, checkout/portal safety, return-state messaging, quota UI, and secret scanning.
- Browser verification captures pricing and billing states under `frontend/test-results/phase-4-3/`.

## Remaining Work Before Phase 4.4

- Connect real production Stripe Product/Price IDs in deployment configuration.
- Configure Stripe Billing Portal actions in the Stripe dashboard.
- Run final billing QA against real Stripe test-mode sessions and webhooks.
- Add component-level React tests if the project adopts a React test runner later.
