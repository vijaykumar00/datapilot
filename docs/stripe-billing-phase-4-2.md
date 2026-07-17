# DataPilot Phase 4.2 Stripe Billing Adapter

## Architecture

Stripe is implemented as an adapter over the provider-neutral subscription domain from Phase 4.1.

- Internal source of truth: `plans`, `plan_limits`, `plan_features`, `workspace_subscriptions`, `trials`, `usage_records`, and `subscription_history`.
- Stripe adapter state: `billing_customers`, `subscriptions`, `webhook_events`, and `subscription_events`.
- Provider synchronization entrypoints live in `core.subscriptions`.
- Stripe-specific API calls, price mapping, webhook verification, and event translation live in `core.stripe_billing`.

Stripe IDs are never used as plan/business logic. They are mapped from environment variables to internal `plan_id` values.

## Environment Variables

Required in production when `STRIPE_BILLING_ENABLED=true`:

- `STRIPE_SECRET_KEY`
- `STRIPE_PUBLISHABLE_KEY`
- `STRIPE_WEBHOOK_SECRET`
- `STRIPE_ENVIRONMENT=test|live`
- `STRIPE_PRICE_PRO_MONTHLY`
- `STRIPE_PRICE_PRO_ANNUAL`
- `STRIPE_PRICE_TEAM_MONTHLY`
- `STRIPE_PRICE_TEAM_ANNUAL`

Optional product IDs for reporting:

- `STRIPE_PRODUCT_PRO`
- `STRIPE_PRODUCT_TEAM`

## Plan Mapping

The mapping layer reads:

- `STRIPE_PRICE_{PLAN_ID}_{INTERVAL}`
- `STRIPE_PRODUCT_{PLAN_ID}`

Examples:

- Internal `pro` monthly maps to `STRIPE_PRICE_PRO_MONTHLY`.
- Internal `team` annual maps to `STRIPE_PRICE_TEAM_ANNUAL`.

The endpoint `GET /billing/stripe/plan-mapping` reports which mappings are configured.

## Checkout Flow

1. Authenticated workspace member calls `POST /billing/checkout`.
2. Backend validates the internal `plan_id`.
3. Backend resolves the Stripe Price ID from the mapping layer.
4. Backend creates or reuses a Stripe Customer for the workspace.
5. Backend creates a Stripe Checkout Session in subscription mode.
6. Stripe redirects back to success/cancel URLs.
7. `checkout.session.completed` webhook synchronizes `workspace_subscriptions`.

Duplicate active subscriptions are blocked. Existing active subscriptions with a different plan are directed to the Customer Portal to avoid duplicate Stripe subscriptions.

## Customer Portal

`POST /billing/portal` creates a Stripe Billing Portal session for the workspace customer. The Portal is the only billing UI for payment method updates, cancellation, resume, invoices, upgrades, and downgrades. Available actions are controlled by Stripe Billing Portal configuration.

## Webhook Flow

`POST /billing/webhook` uses the raw request body and `Stripe-Signature` header for signature verification. The handler supports:

- `checkout.session.completed`
- `customer.subscription.created`
- `customer.subscription.updated`
- `customer.subscription.deleted`
- `invoice.paid`
- `invoice.payment_failed`
- `invoice.finalized`

`webhook_events` is the idempotency guard. Processed events are ignored on retry. Unprocessed records can be retried.

## Subscription Lifecycle

Stripe subscription events are translated into:

- `workspace_subscriptions.status`
- `workspace_subscriptions.plan_id`
- renewal and period dates
- trial dates and trial conversion
- cancellation state
- payment status in subscription metadata
- `subscription_history` entries

No Stripe webhook directly updates the provider-neutral tables outside `core.subscriptions`.

## Deployment Steps

1. Create Stripe Products and recurring Prices for Pro and Team plans.
2. Set Stripe environment variables in the backend runtime.
3. Configure the Stripe webhook endpoint to point at `/billing/webhook`.
4. Enable the supported webhook event types.
5. Configure the Stripe Billing Portal with allowed plan changes, payment method updates, cancellation/resume, and invoice access.
6. Run database migrations and backend tests.
