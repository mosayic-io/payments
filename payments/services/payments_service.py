import logging

from fastapi import HTTPException, status

from app.core.settings import get_settings
from app.payments.clients.stripe_client import StripeClient
from app.payments.schemas import (
    PaymentProvider,
    SubscriptionStatus,
    CheckoutSessionResponse,
    PortalSessionResponse,
    Product,
    ProductCreate,
    SubscriptionResponse,
)

logger = logging.getLogger(__name__)


class PaymentsService:
    """Unified payments service for Stripe and RevenueCat.

    Supabase is the source of truth for subscription state.
    Provider-specific logic is encapsulated in private methods.
    """

    def __init__(self, db_client, stripe_client: StripeClient | None):
        self.db = db_client
        self.stripe = stripe_client
        self.settings = get_settings()

    # -------------------------------------------------------------------------
    # Product Management
    # -------------------------------------------------------------------------

    async def create_product(self, product: ProductCreate) -> Product:
        """Create a product in the database, then optionally sync to Stripe."""
        row = product.model_dump(mode="json")

        try:
            response = await self.db.table("products").insert(row).execute()
            db_product = response.data[0]
        except Exception as e:
            logger.error("Failed to save product to database: %s", e)
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Failed to save product to database: {e}",
            )

        if self.stripe:
            try:
                stripe_product = self.stripe.create_product(
                    name=product.name,
                    description=product.description,
                    identifier=product.identifier,
                )
                stripe_price = self.stripe.create_price(
                    product_id=stripe_product["stripe_product_id"],
                    unit_amount=product.price_in_cents,
                    currency=product.currency,
                    billing_frequency=product.billing_frequency,
                    identifier=product.identifier,
                )
                stripe_ids = {
                    "stripe_product_id": stripe_product["stripe_product_id"],
                    "stripe_price_id": stripe_price["stripe_price_id"],
                }
                update_resp = await (
                    self.db.table("products")
                    .update(stripe_ids)
                    .eq("id", db_product["id"])
                    .execute()
                )
                db_product = update_resp.data[0]
            except Exception as e:
                logger.warning(
                    "Product saved to DB but Stripe sync failed: %s", e
                )

        return Product(**db_product)

    async def get_products(self) -> list[Product]:
        """List all active products."""
        response = await (
            self.db.table("products")
            .select("*")
            .eq("is_active", True)
            .order("sort_order")
            .execute()
        )
        return [Product(**row) for row in response.data]

    # -------------------------------------------------------------------------
    # Stripe Checkout & Portal
    # -------------------------------------------------------------------------

    async def create_checkout_session(
        self,
        user_id: str,
        user_email: str | None,
        product_identifier: str,
    ) -> CheckoutSessionResponse:
        """Create a Stripe Checkout session for a product."""
        if not self.stripe:
            raise HTTPException(status_code=status.HTTP_501_NOT_IMPLEMENTED, detail="Stripe is not configured")

        product = await self._get_product_by_identifier(product_identifier)

        if not product.stripe_price_id:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Product '{product_identifier}' does not have a Stripe price ID",
            )

        try:
            session = self.stripe.create_checkout_session(
                price_id=product.stripe_price_id,
                customer_email=user_email,
                user_id=user_id,
                product_identifier=product_identifier,
                success_url=self.settings.stripe_success_url,
                cancel_url=self.settings.stripe_cancel_url,
                trial_period_days=product.trial_period_days,
            )
            return CheckoutSessionResponse(checkout_url=session["checkout_url"])
        except Exception as e:
            logger.error("Failed to create checkout session: %s", e)
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Unable to create checkout session: {e}",
            )

    async def create_billing_portal(self, user_id: str) -> PortalSessionResponse:
        """Create a Stripe Billing Portal session for the user."""
        if not self.stripe:
            raise HTTPException(status_code=status.HTTP_501_NOT_IMPLEMENTED, detail="Stripe is not configured")

        response = await (
            self.db.table("subscriptions")
            .select("provider_customer_id")
            .eq("user_id", user_id)
            .eq("provider", PaymentProvider.STRIPE)
            .execute()
        )

        if not response.data or not response.data[0].get("provider_customer_id"):
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="No Stripe subscription found for user",
            )

        customer_id = response.data[0]["provider_customer_id"]
        session = self.stripe.create_billing_portal_session(
            customer_id=customer_id,
            return_url=self.settings.stripe_success_url,
        )
        return PortalSessionResponse(portal_url=session["portal_url"])

    # -------------------------------------------------------------------------
    # Unified Subscription Status
    # -------------------------------------------------------------------------

    async def get_subscription_status(self, user_id: str) -> SubscriptionResponse:
        """Get user's subscription status from Supabase (provider-agnostic)."""
        response = await (
            self.db.table("subscriptions")
            .select("*, products(identifier)")
            .eq("user_id", user_id)
            .in_("status", [
                SubscriptionStatus.ACTIVE,
                SubscriptionStatus.TRIALING,
                SubscriptionStatus.PAST_DUE,
                SubscriptionStatus.CANCELED,
            ])
            .limit(1)
            .execute()
        )

        if not response.data:
            return SubscriptionResponse(
                provider=PaymentProvider.STRIPE,
                status=SubscriptionStatus.NONE,
                entitlement="free",
            )

        sub = response.data[0]
        product_identifier = None
        if sub.get("products") and sub["products"].get("identifier"):
            product_identifier = sub["products"]["identifier"]

        return SubscriptionResponse(
            provider=sub["provider"],
            status=sub["status"],
            entitlement=sub["entitlement"],
            product_identifier=product_identifier,
            current_period_end=(
                sub["current_period_end"] if sub.get("current_period_end") else None
            ),
            cancel_at_period_end=sub.get("cancel_at_period_end", False),
        )

    # -------------------------------------------------------------------------
    # Internal helpers
    # -------------------------------------------------------------------------

    async def _get_product_by_identifier(self, identifier: str) -> Product:
        try:
            response = await (
                self.db.table("products")
                .select("*")
                .eq("identifier", identifier)
                .single()
                .execute()
            )
            return Product(**response.data)
        except Exception as e:
            logger.error("Product '%s' not found: %s", identifier, e)
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Product '{identifier}' not found",
            )
