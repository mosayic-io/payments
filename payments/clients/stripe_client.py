from typing import Literal

import stripe as stripe_sdk
from stripe import SignatureVerificationError

from app.core.settings import get_settings
from app.payments.exceptions import PaymentError, WebhookVerificationError


class StripeClient:
    """Wrapper for the Stripe SDK."""

    def __init__(self):
        settings = get_settings()
        stripe_sdk.api_key = settings.stripe_secret_key

    def create_checkout_session(
        self,
        price_id: str,
        customer_email: str | None,
        user_id: str,
        product_identifier: str,
        success_url: str,
        cancel_url: str,
        trial_period_days: int | None = None,
    ) -> dict:
        subscription_data: dict = {}
        if trial_period_days:
            subscription_data["trial_period_days"] = trial_period_days

        params: dict = {
            "payment_method_types": ["card"],
            "line_items": [{"price": price_id, "quantity": 1}],
            "mode": "subscription",
            "subscription_data": subscription_data,
            "success_url": success_url,
            "cancel_url": cancel_url,
            "metadata": {
                "user_id": user_id,
                "product": product_identifier,
            },
        }
        if customer_email is not None:
            params["customer_email"] = customer_email

        session = stripe_sdk.checkout.Session.create(**params)
        return {"checkout_url": session.url, "session_id": session.id}

    def create_billing_portal_session(
        self, customer_id: str, return_url: str
    ) -> dict:
        try:
            session = stripe_sdk.billing_portal.Session.create(
                customer=customer_id,
                return_url=return_url,
            )
        except Exception as e:
            raise PaymentError(f"Failed to create billing portal session: {e}")
        return {"portal_url": session.url}

    def retrieve_subscription(self, subscription_id: str) -> dict:
        return stripe_sdk.Subscription.retrieve(subscription_id)

    def create_product(self, name: str, description: str, identifier: str) -> dict:
        stripe_product = stripe_sdk.Product.create(
            name=name,
            description=description,
            metadata={"identifier": identifier},
        )
        return {"stripe_product_id": stripe_product.id}

    def create_price(
        self,
        product_id: str,
        unit_amount: int,
        currency: str,
        billing_frequency: str,
        identifier: str,
    ) -> dict:
        interval_map: dict[str, Literal["day", "month", "week", "year"]] = {
            "monthly": "month",
            "yearly": "year",
            "quarterly": "month",
        }
        interval = interval_map.get(billing_frequency, "month")
        interval_count = 3 if billing_frequency == "quarterly" else 1

        stripe_price = stripe_sdk.Price.create(
            product=product_id,
            unit_amount=unit_amount,
            currency=currency,
            recurring={"interval": interval, "interval_count": interval_count},
            metadata={"identifier": identifier},
        )
        return {"stripe_price_id": stripe_price.id}

    def verify_webhook_signature(
        self, payload: bytes, sig_header: str, webhook_secret: str
    ) -> stripe_sdk.Event:
        try:
            event = stripe_sdk.Webhook.construct_event(
                payload, sig_header, webhook_secret
            )
            return event
        except ValueError:
            raise WebhookVerificationError("Invalid payload")
        except SignatureVerificationError:
            raise WebhookVerificationError("Invalid Stripe webhook signature")
