import logging
from datetime import datetime, timezone

from fastapi import HTTPException, status

from app.core.settings import get_settings
from app.payments.clients.stripe_client import StripeClient
from app.payments.schemas import PaymentProvider, SubscriptionStatus

logger = logging.getLogger(__name__)


class WebhookService:
    """Handles webhook events from Stripe and RevenueCat.

    Both providers converge on shared internal methods that write to the same
    Supabase tables.
    """

    def __init__(self, db_client, stripe_client: StripeClient | None):
        self.db = db_client
        self.settings = get_settings()
        self.stripe = stripe_client

    # -------------------------------------------------------------------------
    # Stripe Webhooks
    # -------------------------------------------------------------------------

    async def handle_stripe_webhook(self, payload: bytes, signature: str) -> dict:
        """Process a Stripe webhook event."""
        if not self.stripe:
            raise HTTPException(status_code=status.HTTP_501_NOT_IMPLEMENTED, detail="Stripe is not configured")

        event = self.stripe.verify_webhook_signature(
            payload, signature, self.settings.stripe_webhook_secret
        )

        event_type = event["type"]
        data = event["data"]["object"]

        handler_map = {
            "checkout.session.completed": self._handle_stripe_checkout_completed,
            "customer.subscription.updated": self._handle_stripe_subscription_updated,
            "customer.subscription.deleted": self._handle_stripe_subscription_deleted,
            "invoice.payment_failed": self._handle_stripe_payment_failed,
        }

        handler = handler_map.get(event_type)
        if handler:
            await handler(data)

        return {"status": "ok"}

    async def _handle_stripe_checkout_completed(self, session: dict) -> None:
        user_id = session.get("metadata", {}).get("user_id")
        product_identifier = session.get("metadata", {}).get("product")

        if not user_id or not product_identifier:
            logger.error("Missing user_id or product in checkout metadata")
            return

        product = await self._get_product_by_identifier(product_identifier)
        if not product:
            logger.error("Product '%s' not found for checkout", product_identifier)
            return

        subscription_id = session.get("subscription", "")
        period_end = None
        if subscription_id and self.stripe:
            try:
                stripe_sub = self.stripe.retrieve_subscription(subscription_id)
                period_end = datetime.fromtimestamp(
                    stripe_sub.get("current_period_end", 0), tz=timezone.utc
                ).isoformat()
            except Exception:
                logger.warning("Could not retrieve Stripe subscription details")

        await self._create_subscription(
            user_id=user_id,
            product_id=product["id"],
            provider=PaymentProvider.STRIPE,
            provider_subscription_id=subscription_id,
            provider_customer_id=session.get("customer", ""),
            entitlement=product["entitlement"],
            current_period_end=period_end,
        )

    async def _handle_stripe_subscription_updated(self, subscription: dict) -> None:
        provider_sub_id = subscription.get("id", "")
        if not provider_sub_id:
            return

        updates: dict = {
            "status": self._map_stripe_status(subscription.get("status", "")),
            "cancel_at_period_end": subscription.get("cancel_at_period_end", False),
        }

        if subscription.get("current_period_end"):
            updates["current_period_end"] = datetime.fromtimestamp(
                subscription["current_period_end"], tz=timezone.utc
            ).isoformat()

        await self._update_subscription(
            provider=PaymentProvider.STRIPE,
            provider_subscription_id=provider_sub_id,
            updates=updates,
        )

    async def _handle_stripe_subscription_deleted(self, subscription: dict) -> None:
        provider_sub_id = subscription.get("id", "")
        if provider_sub_id:
            await self._cancel_subscription(
                provider=PaymentProvider.STRIPE,
                provider_subscription_id=provider_sub_id,
            )

    async def _handle_stripe_payment_failed(self, invoice: dict) -> None:
        provider_sub_id = invoice.get("subscription", "")
        if provider_sub_id:
            await self._update_subscription(
                provider=PaymentProvider.STRIPE,
                provider_subscription_id=provider_sub_id,
                updates={"status": SubscriptionStatus.PAST_DUE},
            )

    # -------------------------------------------------------------------------
    # RevenueCat Webhooks
    # -------------------------------------------------------------------------

    async def handle_revenuecat_webhook(self, payload: dict) -> dict:
        """Process a RevenueCat webhook event."""
        event = payload.get("event", {})
        event_type = event.get("type", "")

        app_user_id = event.get("app_user_id", "")
        product_id_rc = event.get("product_id", "")

        handler_map = {
            "INITIAL_PURCHASE": self._handle_rc_initial_purchase,
            "RENEWAL": self._handle_rc_renewal,
            "CANCELLATION": self._handle_rc_cancellation,
            "EXPIRATION": self._handle_rc_expiration,
            "BILLING_ISSUE_DETECTED": self._handle_rc_billing_issue,
            "PRODUCT_CHANGE": self._handle_rc_product_change,
        }

        handler = handler_map.get(event_type)
        if handler:
            await handler(
                app_user_id=app_user_id,
                product_id_rc=product_id_rc,
                event=event,
            )

        return {"status": "ok"}

    async def _handle_rc_initial_purchase(
        self, app_user_id: str, product_id_rc: str, event: dict
    ) -> None:
        product = await self._get_product_by_rc_id(product_id_rc)
        if not product:
            logger.error(
                "Product with revenuecat_product_id '%s' not found", product_id_rc
            )
            return

        expiration = event.get("expiration_at_ms")
        period_end = None
        if expiration:
            period_end = datetime.fromtimestamp(
                expiration / 1000, tz=timezone.utc
            ).isoformat()

        await self._create_subscription(
            user_id=app_user_id,
            product_id=product["id"],
            provider=PaymentProvider.REVENUECAT,
            provider_subscription_id=event.get("original_transaction_id", ""),
            provider_customer_id=app_user_id,
            entitlement=product["entitlement"],
            current_period_end=period_end,
        )

    async def _handle_rc_renewal(
        self, app_user_id: str, product_id_rc: str, event: dict
    ) -> None:
        expiration = event.get("expiration_at_ms")
        period_end = None
        if expiration:
            period_end = datetime.fromtimestamp(
                expiration / 1000, tz=timezone.utc
            ).isoformat()

        updates: dict = {"status": SubscriptionStatus.ACTIVE}
        if period_end:
            updates["current_period_end"] = period_end

        original_tx = event.get("original_transaction_id", "")
        if original_tx:
            await self._update_subscription(
                provider=PaymentProvider.REVENUECAT,
                provider_subscription_id=original_tx,
                updates=updates,
            )

    async def _handle_rc_cancellation(
        self, app_user_id: str, product_id_rc: str, event: dict
    ) -> None:
        original_tx = event.get("original_transaction_id", "")
        if original_tx:
            expiration = event.get("expiration_at_ms")
            updates: dict = {
                "status": SubscriptionStatus.CANCELED,
                "cancel_at_period_end": True,
            }
            if expiration:
                updates["current_period_end"] = datetime.fromtimestamp(
                    expiration / 1000, tz=timezone.utc
                ).isoformat()
            await self._update_subscription(
                provider=PaymentProvider.REVENUECAT,
                provider_subscription_id=original_tx,
                updates=updates,
            )

    async def _handle_rc_expiration(
        self, app_user_id: str, product_id_rc: str, event: dict
    ) -> None:
        original_tx = event.get("original_transaction_id", "")
        if original_tx:
            await self._cancel_subscription(
                provider=PaymentProvider.REVENUECAT,
                provider_subscription_id=original_tx,
            )

    async def _handle_rc_billing_issue(
        self, app_user_id: str, product_id_rc: str, event: dict
    ) -> None:
        original_tx = event.get("original_transaction_id", "")
        if original_tx:
            await self._update_subscription(
                provider=PaymentProvider.REVENUECAT,
                provider_subscription_id=original_tx,
                updates={"status": SubscriptionStatus.PAST_DUE},
            )

    async def _handle_rc_product_change(
        self, app_user_id: str, product_id_rc: str, event: dict
    ) -> None:
        new_product_id = event.get("new_product_id", product_id_rc)
        product = await self._get_product_by_rc_id(new_product_id)
        if not product:
            return

        original_tx = event.get("original_transaction_id", "")
        if original_tx:
            await self._update_subscription(
                provider=PaymentProvider.REVENUECAT,
                provider_subscription_id=original_tx,
                updates={
                    "product_id": product["id"],
                    "entitlement": product["entitlement"],
                },
            )

    # -------------------------------------------------------------------------
    # Shared Internal Methods
    # -------------------------------------------------------------------------

    async def _create_subscription(
        self,
        user_id: str,
        product_id: str | None,
        provider: str,
        provider_subscription_id: str,
        provider_customer_id: str,
        entitlement: str,
        current_period_end: str | None = None,
    ) -> None:
        row = {
            "user_id": user_id,
            "product_id": product_id,
            "provider": provider,
            "provider_subscription_id": provider_subscription_id,
            "provider_customer_id": provider_customer_id,
            "entitlement": entitlement,
            "status": SubscriptionStatus.ACTIVE,
            "current_period_end": current_period_end,
        }
        try:
            await self.db.table("subscriptions").upsert(
                row, on_conflict="user_id,provider"
            ).execute()
            logger.info(
                "Created/updated subscription for user %s via %s", user_id, provider
            )
        except Exception as e:
            logger.error("Failed to create subscription: %s", e)
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Failed to save subscription: {e}",
            )

    async def _update_subscription(
        self,
        provider: str,
        provider_subscription_id: str,
        updates: dict,
    ) -> None:
        try:
            await self.db.table("subscriptions").update(updates).eq(
                "provider", provider
            ).eq("provider_subscription_id", provider_subscription_id).execute()
            logger.info(
                "Updated %s subscription %s", provider, provider_subscription_id
            )
        except Exception as e:
            logger.error("Failed to update subscription: %s", e)
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Failed to update subscription: {e}",
            )

    async def _cancel_subscription(
        self, provider: str, provider_subscription_id: str
    ) -> None:
        await self._update_subscription(
            provider=provider,
            provider_subscription_id=provider_subscription_id,
            updates={"status": SubscriptionStatus.EXPIRED},
        )

    # -------------------------------------------------------------------------
    # Helpers
    # -------------------------------------------------------------------------

    async def _get_product_by_identifier(self, identifier: str) -> dict | None:
        try:
            response = await (
                self.db.table("products")
                .select("*")
                .eq("identifier", identifier)
                .single()
                .execute()
            )
            return response.data
        except Exception:
            return None

    async def _get_product_by_rc_id(self, revenuecat_product_id: str) -> dict | None:
        try:
            response = await (
                self.db.table("products")
                .select("*")
                .eq("revenuecat_product_id", revenuecat_product_id)
                .single()
                .execute()
            )
            return response.data
        except Exception:
            return None

    @staticmethod
    def _map_stripe_status(stripe_status: str) -> str:
        mapping = {
            "active": SubscriptionStatus.ACTIVE,
            "past_due": SubscriptionStatus.PAST_DUE,
            "canceled": SubscriptionStatus.CANCELED,
            "unpaid": SubscriptionStatus.PAST_DUE,
            "trialing": SubscriptionStatus.TRIALING,
            "incomplete": SubscriptionStatus.PAST_DUE,
            "incomplete_expired": SubscriptionStatus.EXPIRED,
        }
        return mapping.get(stripe_status, SubscriptionStatus.ACTIVE)
