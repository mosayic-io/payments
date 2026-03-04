import pytest
from unittest.mock import MagicMock, AsyncMock

from app.payments.services.payments_service import PaymentsService
from app.payments.schemas import PaymentProvider, ProductCreate, SubscriptionStatus


@pytest.fixture
def mock_stripe_client():
    return MagicMock()


@pytest.fixture
def service(mock_db_client, mock_stripe_client):
    return PaymentsService(mock_db_client, mock_stripe_client)


@pytest.mark.asyncio
async def test_get_products_returns_list(service, mock_db_client):
    mock_db_client.execute.return_value = MagicMock(
        data=[
            {
                "id": "prod-1",
                "identifier": "pro_monthly",
                "name": "Pro Monthly",
                "description": "Monthly pro plan",
                "price_in_cents": 999,
                "currency": "usd",
                "billing_frequency": "monthly",
                "entitlement": "pro",
                "sort_order": 0,
                "is_active": True,
            }
        ]
    )

    products = await service.get_products()
    assert len(products) == 1
    assert products[0].identifier == "pro_monthly"


@pytest.mark.asyncio
async def test_get_subscription_status_no_subscription(service, mock_db_client):
    mock_db_client.execute.return_value = MagicMock(data=[])

    result = await service.get_subscription_status("user-123")
    assert result.status == SubscriptionStatus.NONE
    assert result.entitlement == "free"


@pytest.mark.asyncio
async def test_get_subscription_status_active(service, mock_db_client):
    mock_db_client.execute.return_value = MagicMock(
        data=[
            {
                "provider": "stripe",
                "status": "active",
                "entitlement": "pro",
                "current_period_end": "2026-04-01T00:00:00+00:00",
                "cancel_at_period_end": False,
                "products": {"identifier": "pro_monthly"},
            }
        ]
    )

    result = await service.get_subscription_status("user-123")
    assert result.status == SubscriptionStatus.ACTIVE
    assert result.entitlement == "pro"
    assert result.provider == PaymentProvider.STRIPE
    assert result.product_identifier == "pro_monthly"


@pytest.mark.asyncio
async def test_create_checkout_session(service, mock_db_client, mock_stripe_client):
    mock_db_client.execute.return_value = MagicMock(
        data={
            "id": "prod-1",
            "identifier": "pro_monthly",
            "name": "Pro Monthly",
            "description": "",
            "price_in_cents": 999,
            "currency": "usd",
            "billing_frequency": "monthly",
            "entitlement": "pro",
            "stripe_price_id": "price_test_123",
            "stripe_product_id": "prod_test_123",
            "sort_order": 0,
            "is_active": True,
        }
    )

    mock_stripe_client.create_checkout_session.return_value = {
        "checkout_url": "https://checkout.stripe.com/test",
        "session_id": "cs_test",
    }

    result = await service.create_checkout_session(
        user_id="user-123",
        user_email="test@example.com",
        product_identifier="pro_monthly",
    )
    assert result.checkout_url == "https://checkout.stripe.com/test"


SAMPLE_PRODUCT_INPUT = ProductCreate(
    identifier="pro_monthly",
    name="Pro Monthly",
    description="Monthly pro plan",
    price_in_cents=999,
    billing_frequency="monthly",
    entitlement="pro",
)

SAMPLE_DB_ROW = {
    "id": "prod-1",
    "identifier": "pro_monthly",
    "name": "Pro Monthly",
    "description": "Monthly pro plan",
    "price_in_cents": 999,
    "currency": "usd",
    "billing_frequency": "monthly",
    "entitlement": "pro",
    "trial_period_days": None,
    "sort_order": 0,
    "revenuecat_product_id": None,
    "stripe_product_id": None,
    "stripe_price_id": None,
    "is_active": True,
}


@pytest.mark.asyncio
async def test_create_product_with_stripe(service, mock_db_client, mock_stripe_client):
    """Product is saved to DB first, then synced to Stripe, then DB updated."""
    row_after_insert = {**SAMPLE_DB_ROW}
    row_after_update = {
        **SAMPLE_DB_ROW,
        "stripe_product_id": "prod_stripe_1",
        "stripe_price_id": "price_stripe_1",
    }

    mock_db_client.execute = AsyncMock(
        side_effect=[
            MagicMock(data=[row_after_insert]),   # insert
            MagicMock(data=[row_after_update]),    # update with Stripe IDs
        ]
    )

    mock_stripe_client.create_product.return_value = {
        "stripe_product_id": "prod_stripe_1",
    }
    mock_stripe_client.create_price.return_value = {
        "stripe_price_id": "price_stripe_1",
    }

    result = await service.create_product(SAMPLE_PRODUCT_INPUT)

    assert result.id == "prod-1"
    assert result.stripe_product_id == "prod_stripe_1"
    assert result.stripe_price_id == "price_stripe_1"
    assert mock_db_client.execute.call_count == 2


@pytest.mark.asyncio
async def test_create_product_without_stripe(service, mock_db_client, mock_stripe_client):
    """Product is saved to DB without Stripe sync when no key is configured."""
    mock_db_client.execute = AsyncMock(
        return_value=MagicMock(data=[SAMPLE_DB_ROW])
    )

    service.stripe = None
    result = await service.create_product(SAMPLE_PRODUCT_INPUT)

    assert result.id == "prod-1"
    assert result.stripe_product_id is None
    assert result.stripe_price_id is None
    mock_stripe_client.create_product.assert_not_called()
    mock_stripe_client.create_price.assert_not_called()
