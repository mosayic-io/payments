import pytest


WEBHOOK_SERVICE_PATH = "app.payments.routes.webhooks_router.WebhookService"


@pytest.mark.asyncio
async def test_stripe_webhook_missing_signature(payments_client):
    response = await payments_client.post(
        "/payments/webhooks/stripe",
        content=b'{"type": "test"}',
    )
    # Missing Stripe-Signature header should return 422
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_revenuecat_webhook_invalid_auth(payments_client):
    response = await payments_client.post(
        "/payments/webhooks/revenuecat",
        json={"event": {"type": "TEST"}},
        headers={"Authorization": "wrong_secret"},
    )
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_revenuecat_webhook_no_auth_header(payments_client):
    response = await payments_client.post(
        "/payments/webhooks/revenuecat",
        json={"event": {"type": "TEST"}},
    )
    assert response.status_code == 401
