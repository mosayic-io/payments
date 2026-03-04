import pytest
from unittest.mock import MagicMock

from app.payments.services.webhook_service import WebhookService


@pytest.fixture
def mock_stripe_client():
    return MagicMock()


@pytest.fixture
def service(mock_db_client, mock_stripe_client):
    return WebhookService(mock_db_client, mock_stripe_client)


@pytest.mark.asyncio
async def test_stripe_webhook_checkout_completed(
    service, mock_db_client, mock_stripe_client
):
    mock_event = {
        "id": "evt_test_123",
        "type": "checkout.session.completed",
        "data": {
            "object": {
                "metadata": {"user_id": "user-123", "product": "pro_monthly"},
                "subscription": "sub_test_123",
                "customer": "cus_test_123",
            }
        },
    }

    mock_stripe_client.verify_webhook_signature.return_value = mock_event
    mock_stripe_client.retrieve_subscription.return_value = {
        "current_period_end": 1743465600
    }

    product_response = MagicMock(
        data={"id": "prod-uuid", "entitlement": "pro", "identifier": "pro_monthly"}
    )
    mock_db_client.execute.side_effect = [
        MagicMock(data=[]),  # duplicate check
        product_response,  # product lookup
        MagicMock(data=[]),  # upsert subscription
        MagicMock(data=[]),  # log event
    ]

    result = await service.handle_stripe_webhook(b"payload", "sig_header")
    assert result["status"] == "ok"


@pytest.mark.asyncio
async def test_stripe_webhook_duplicate_event(
    service, mock_db_client, mock_stripe_client
):
    mock_event = {
        "id": "evt_test_dup",
        "type": "checkout.session.completed",
        "data": {"object": {}},
    }

    mock_stripe_client.verify_webhook_signature.return_value = mock_event

    mock_db_client.execute.return_value = MagicMock(data=[{"id": "existing"}])

    result = await service.handle_stripe_webhook(b"payload", "sig_header")
    assert result["status"] == "already_processed"


@pytest.mark.asyncio
async def test_revenuecat_webhook_initial_purchase(service, mock_db_client):
    payload = {
        "event": {
            "id": "rc_evt_123",
            "type": "INITIAL_PURCHASE",
            "app_user_id": "user-456",
            "product_id": "com.app.pro_monthly",
            "original_transaction_id": "tx_123",
            "expiration_at_ms": 1743465600000,
        }
    }

    mock_db_client.execute.side_effect = [
        MagicMock(data=[]),  # duplicate check
        MagicMock(
            data={"id": "prod-uuid", "entitlement": "pro"}
        ),  # product lookup
        MagicMock(data=[]),  # upsert subscription
        MagicMock(data=[]),  # log event
    ]

    result = await service.handle_revenuecat_webhook(payload)
    assert result["status"] == "ok"


@pytest.mark.asyncio
async def test_revenuecat_webhook_cancellation(service, mock_db_client):
    payload = {
        "event": {
            "id": "rc_evt_cancel",
            "type": "CANCELLATION",
            "app_user_id": "user-456",
            "product_id": "com.app.pro_monthly",
            "original_transaction_id": "tx_123",
            "expiration_at_ms": 1743465600000,
        }
    }

    mock_db_client.execute.side_effect = [
        MagicMock(data=[]),  # duplicate check
        MagicMock(data=[]),  # update subscription
        MagicMock(data=[]),  # log event
    ]

    result = await service.handle_revenuecat_webhook(payload)
    assert result["status"] == "ok"
