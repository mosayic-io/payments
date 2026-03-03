from fastapi import APIRouter, Depends
from supabase_auth.types import User

from app.core.auth import get_current_user
from app.core.settings import get_settings
from app.core.supabase_client import get_supabase_client
from app.payments.clients.stripe_client import StripeClient
from app.payments.services.payments_service import PaymentsService
from app.payments.schemas import (
    CheckoutRequest,
    CheckoutSessionResponse,
    PortalSessionResponse,
    Product,
    ProductCreate,
    SubscriptionResponse,
)

router = APIRouter(tags=["Payments"])


async def get_payments_service(db_client=Depends(get_supabase_client)):
    settings = get_settings()
    stripe_client = StripeClient() if settings.stripe_secret_key else None
    return PaymentsService(db_client, stripe_client)


@router.post("/products", response_model=Product)
async def create_product(product: ProductCreate, user: User = Depends(get_current_user), service: PaymentsService = Depends(get_payments_service)):
    return await service.create_product(product)


@router.get("/products", response_model=list[Product])
async def list_products(user: User = Depends(get_current_user), service: PaymentsService = Depends(get_payments_service)):
    return await service.get_products()


@router.post("/checkout", response_model=CheckoutSessionResponse)
async def create_checkout(request: CheckoutRequest, user: User = Depends(get_current_user), service: PaymentsService = Depends(get_payments_service)):
    return await service.create_checkout_session(
        user_id=str(user.id),
        user_email=user.email,
        product_identifier=request.product_identifier,
    )


@router.post("/billing-portal", response_model=PortalSessionResponse)
async def create_billing_portal(user: User = Depends(get_current_user), service: PaymentsService = Depends(get_payments_service)):
    return await service.create_billing_portal(user_id=str(user.id))


@router.get("/subscription", response_model=SubscriptionResponse)
async def get_subscription(user: User = Depends(get_current_user), service: PaymentsService = Depends(get_payments_service)):
    return await service.get_subscription_status(user_id=str(user.id))
