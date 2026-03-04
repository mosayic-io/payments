# Payments Module

Unified payment system supporting **Stripe** (web) and **RevenueCat** (mobile). Both providers converge on the same Supabase tables, so the rest of the app never needs to know which provider a subscription came from.

## Core Principle

**Supabase is the single source of truth for subscription state.** Provider APIs (Stripe, RevenueCat) are only called for actions (creating checkouts, managing billing portals). Reading subscription status always goes through Supabase, never live provider APIs.

Data flows **into** Supabase via webhooks from each provider. Data flows **out** of Supabase via the `/subscription` endpoint.

## Directory Structure

```
payments/
    __init__.py              # Mounts both routers under /payments
    schemas.py               # Pydantic models and enums (shared across all files)
    exceptions.py            # PaymentError, WebhookVerificationError
    clients/
        __init__.py
        stripe_client.py     # Thin wrapper around the Stripe SDK
    routes/
        __init__.py
        payments_router.py   # User-facing endpoints (products, checkout, subscription)
        webhooks_router.py   # Webhook endpoints (Stripe, RevenueCat)
    services/
        __init__.py
        payments_service.py  # Business logic for user-facing operations
        webhook_service.py   # Business logic for processing webhook events
    tests/
        __init__.py
        conftest.py          # Shared fixtures (mock_db_client, payments_client)
        test_payments_service.py
        test_webhook_service.py
        test_webhooks_router.py
20260101120000_add_payments_tables.sql  # Supabase migration for payments tables
```

## Database

Tables are defined in the Supabase migration file `20260101120000_add_payments_tables.sql` at the project root. The payments module depends on two tables:

- **products** — catalog of purchasable plans. Each row has an `identifier` (e.g. `"pro_monthly"`), pricing info, an `entitlement` string, and optional provider-specific IDs (`stripe_product_id`, `stripe_price_id`, `revenuecat_product_id`).
- **subscriptions** — one row per user per provider. Stores `status`, `entitlement`, `provider_subscription_id`, `provider_customer_id`, `current_period_end`, and `cancel_at_period_end`. Upserted on conflict of `(user_id, provider)`.


## Endpoints

All endpoints are mounted under `/payments`. User-facing endpoints require authentication (`get_current_user` dependency).

### User-facing (`payments_router.py`)

| Method | Path | Description |
|--------|------|-------------|
| POST | `/products` | Create a product in Supabase, optionally sync to Stripe |
| GET | `/products` | List all active products |
| POST | `/checkout` | Create a Stripe Checkout session for a product |
| POST | `/billing-portal` | Create a Stripe Billing Portal session |
| GET | `/subscription` | Get the user's subscription status from Supabase |

### Webhooks (`webhooks_router.py`)

| Method | Path | Auth | Description |
|--------|------|------|-------------|
| POST | `/webhooks/stripe` | `Stripe-Signature` header verified against `STRIPE_WEBHOOK_SECRET` | Receives Stripe events |
| POST | `/webhooks/revenuecat` | `Authorization` header matched against `REVENUECAT_WEBHOOK_SECRET` | Receives RevenueCat events |

## Data Flow

### Stripe (web subscriptions)

```
1. Client calls POST /checkout with a product_identifier
2. PaymentsService looks up the product, creates a Stripe Checkout session
3. User completes payment on Stripe's hosted page
4. Stripe sends checkout.session.completed webhook
5. WebhookService reads metadata (user_id, product), upserts into subscriptions table
6. Subsequent subscription changes arrive via customer.subscription.updated/deleted webhooks
```

### RevenueCat (mobile subscriptions)

```
1. Mobile app handles purchase through App Store / Google Play via RevenueCat SDK
2. RevenueCat sends webhook (INITIAL_PURCHASE, RENEWAL, CANCELLATION, etc.)
3. WebhookService looks up the product by revenuecat_product_id, upserts into subscriptions table
```

### Reading subscription status (both providers)

```
1. Client calls GET /subscription
2. PaymentsService queries the subscriptions table (filtered to active/trialing/past_due/canceled)
3. Returns provider, status, entitlement, product_identifier, period end, cancel_at_period_end
4. If no subscription exists, returns status="none", entitlement="free"
```

## Webhook Events Handled

### Stripe

| Event | Handler | Effect |
|-------|---------|--------|
| `checkout.session.completed` | `_handle_stripe_checkout_completed` | Creates/upserts subscription row |
| `customer.subscription.updated` | `_handle_stripe_subscription_updated` | Updates status, period end, cancel flag |
| `customer.subscription.deleted` | `_handle_stripe_subscription_deleted` | Sets status to `expired` |
| `invoice.payment_failed` | `_handle_stripe_payment_failed` | Sets status to `past_due` |

### RevenueCat

| Event | Handler | Effect |
|-------|---------|--------|
| `INITIAL_PURCHASE` | `_handle_rc_initial_purchase` | Creates/upserts subscription row |
| `RENEWAL` | `_handle_rc_renewal` | Sets status to `active`, updates period end |
| `CANCELLATION` | `_handle_rc_cancellation` | Sets status to `canceled`, sets cancel flag |
| `EXPIRATION` | `_handle_rc_expiration` | Sets status to `expired` |
| `BILLING_ISSUE_DETECTED` | `_handle_rc_billing_issue` | Sets status to `past_due` |
| `PRODUCT_CHANGE` | `_handle_rc_product_change` | Updates product and entitlement |

## Environment Variables

Loaded from `.env`:

| Variable | Required | Purpose |
|----------|----------|---------|
| `STRIPE_SECRET_KEY` | For Stripe | Stripe API authentication |
| `STRIPE_WEBHOOK_SECRET` | For Stripe | Verifying Stripe webhook signatures |
| `STRIPE_SUCCESS_URL` | For Stripe | Redirect URL after successful checkout |
| `STRIPE_CANCEL_URL` | For Stripe | Redirect URL after canceled checkout |
| `REVENUECAT_WEBHOOK_SECRET` | For RevenueCat | Verifying RevenueCat webhook auth header |

Both providers are optional. If `STRIPE_SECRET_KEY` is empty, the Stripe client is not instantiated and Stripe-specific endpoints return 501.

## Testing

```bash
uv run pytest payments/tests/ -v
```

Tests use `unittest.mock` to mock the Supabase client and Stripe client. The mock Supabase client is configured in `tests/conftest.py` to support the chained query builder pattern (`.table().select().eq().execute()`).

### Local Stripe webhook testing

```bash
stripe listen --forward-to localhost:8080/payments/webhooks/stripe
```

Use the `whsec_...` signing secret printed by `stripe listen` as your `STRIPE_WEBHOOK_SECRET` in `.env`. This is different from any webhook secret configured in the Stripe dashboard.
