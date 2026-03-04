-- ============================================================================
-- PAYMENTS TABLES
-- ============================================================================

-- Products: one row = one product concept, with IDs for both Stripe and RevenueCat
CREATE TABLE public.products (
    id uuid NOT NULL DEFAULT gen_random_uuid(),
    identifier text NOT NULL,
    name text NOT NULL,
    description text NOT NULL DEFAULT '',
    price_in_cents int NOT NULL,
    currency text NOT NULL DEFAULT 'usd',
    billing_frequency text NOT NULL,
    entitlement text NOT NULL,
    trial_period_days int,
    sort_order int NOT NULL DEFAULT 0,
    stripe_product_id text,
    stripe_price_id text,
    revenuecat_product_id text,
    is_active boolean NOT NULL DEFAULT true,
    created_at timestamptz DEFAULT CURRENT_TIMESTAMP,
    updated_at timestamptz DEFAULT CURRENT_TIMESTAMP
);

-- Subscriptions: unified across providers, Supabase is source of truth
CREATE TABLE public.subscriptions (
    id uuid NOT NULL DEFAULT gen_random_uuid(),
    user_id uuid NOT NULL,
    product_id uuid,
    provider text NOT NULL,
    status text NOT NULL DEFAULT 'active',
    entitlement text NOT NULL,
    provider_subscription_id text,
    provider_customer_id text,
    current_period_start timestamptz,
    current_period_end timestamptz,
    cancel_at_period_end boolean NOT NULL DEFAULT false,
    created_at timestamptz DEFAULT CURRENT_TIMESTAMP,
    updated_at timestamptz DEFAULT CURRENT_TIMESTAMP
);

-- Payment events: idempotency log for webhook processing
CREATE TABLE public.payment_events (
    id uuid NOT NULL DEFAULT gen_random_uuid(),
    provider text NOT NULL,
    event_type text NOT NULL,
    event_id text NOT NULL,
    user_id uuid,
    payload jsonb NOT NULL DEFAULT '{}',
    processed_at timestamptz DEFAULT CURRENT_TIMESTAMP
);

-- ============================================================================
-- PRIMARY KEYS
-- ============================================================================

CREATE UNIQUE INDEX products_pkey ON public.products USING btree (id);
ALTER TABLE public.products ADD CONSTRAINT products_pkey PRIMARY KEY USING INDEX products_pkey;

CREATE UNIQUE INDEX products_identifier_key ON public.products USING btree (identifier);
ALTER TABLE public.products
    ADD CONSTRAINT products_identifier_key
    UNIQUE USING INDEX products_identifier_key;

CREATE UNIQUE INDEX subscriptions_pkey ON public.subscriptions USING btree (id);
ALTER TABLE public.subscriptions ADD CONSTRAINT subscriptions_pkey PRIMARY KEY USING INDEX subscriptions_pkey;

CREATE UNIQUE INDEX subscriptions_user_provider_idx ON public.subscriptions USING btree (user_id, provider);
CREATE INDEX subscriptions_provider_sub_id_idx ON public.subscriptions USING btree (provider, provider_subscription_id);

ALTER TABLE public.subscriptions
    ADD CONSTRAINT subscriptions_user_id_fkey
    FOREIGN KEY (user_id)
    REFERENCES public.users(id)
    ON DELETE CASCADE;

ALTER TABLE public.subscriptions
    ADD CONSTRAINT subscriptions_product_id_fkey
    FOREIGN KEY (product_id)
    REFERENCES public.products(id);

CREATE UNIQUE INDEX payment_events_pkey ON public.payment_events USING btree (id);
ALTER TABLE public.payment_events ADD CONSTRAINT payment_events_pkey PRIMARY KEY USING INDEX payment_events_pkey;

CREATE UNIQUE INDEX payment_events_event_id_key ON public.payment_events USING btree (event_id);
ALTER TABLE public.payment_events
    ADD CONSTRAINT payment_events_event_id_key
    UNIQUE USING INDEX payment_events_event_id_key;

-- ============================================================================
-- ROW LEVEL SECURITY
-- ============================================================================

ALTER TABLE public.products ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.subscriptions ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.payment_events ENABLE ROW LEVEL SECURITY;

-- Products: authenticated users can read active products
CREATE POLICY "Authenticated users can view active products"
    ON public.products
    AS PERMISSIVE
    FOR SELECT
    TO authenticated
    USING (is_active = true);

-- Subscriptions: users can view their own
CREATE POLICY "Users can view their own subscriptions"
    ON public.subscriptions
    AS PERMISSIVE
    FOR SELECT
    TO authenticated
    USING (auth.uid() = user_id);

-- Payment events: no user access (service role only)

-- ============================================================================
-- TRIGGERS
-- ============================================================================

CREATE TRIGGER on_products_updated
    BEFORE UPDATE ON public.products
    FOR EACH ROW
    EXECUTE FUNCTION public.handle_updated_at();

CREATE TRIGGER on_subscriptions_updated
    BEFORE UPDATE ON public.subscriptions
    FOR EACH ROW
    EXECUTE FUNCTION public.handle_updated_at();
