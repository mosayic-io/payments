from enum import StrEnum

from pydantic import BaseModel


# --- Enums ---

class PaymentProvider(StrEnum):
    STRIPE = "stripe"
    REVENUECAT = "revenuecat"


class SubscriptionStatus(StrEnum):
    ACTIVE = "active"
    CANCELED = "canceled"
    PAST_DUE = "past_due"
    EXPIRED = "expired"
    TRIALING = "trialing"
    NONE = "none"


# --- Product schemas ---

class ProductCreate(BaseModel):
    identifier: str
    name: str
    description: str = ""
    price_in_cents: int
    currency: str = "usd"
    billing_frequency: str
    entitlement: str
    trial_period_days: int | None = None
    sort_order: int = 0
    revenuecat_product_id: str | None = None


class Product(BaseModel):
    id: str
    identifier: str
    name: str
    description: str
    price_in_cents: int
    currency: str
    billing_frequency: str
    entitlement: str
    trial_period_days: int | None = None
    sort_order: int = 0
    stripe_product_id: str | None = None
    stripe_price_id: str | None = None
    revenuecat_product_id: str | None = None
    is_active: bool = True


# --- Subscription schemas ---

class SubscriptionResponse(BaseModel):
    provider: PaymentProvider
    status: SubscriptionStatus
    entitlement: str
    product_identifier: str | None = None
    current_period_end: str | None = None
    cancel_at_period_end: bool = False


# --- Checkout / Portal schemas ---

class CheckoutRequest(BaseModel):
    product_identifier: str


class CheckoutSessionResponse(BaseModel):
    checkout_url: str


class PortalSessionResponse(BaseModel):
    portal_url: str
