from fastapi import APIRouter, Depends, Header, HTTPException, Request, status

from app.core.settings import get_settings
from app.core.supabase_client import get_supabase_client
from app.payments.clients.stripe_client import StripeClient
from app.payments.services.webhook_service import WebhookService

router = APIRouter(prefix="/webhooks", tags=["Payments - Webhooks"])


async def get_webhook_service(db_client=Depends(get_supabase_client)):
    settings = get_settings()
    stripe_client = StripeClient() if settings.stripe_secret_key else None
    return WebhookService(db_client, stripe_client)


@router.post("/stripe")
async def stripe_webhook(request: Request, stripe_signature: str = Header(alias="Stripe-Signature"), service: WebhookService = Depends(get_webhook_service)):
    payload = await request.body()
    return await service.handle_stripe_webhook(payload, stripe_signature)


@router.post("/revenuecat")
async def revenuecat_webhook(request: Request, authorization: str = Header(default=""), service: WebhookService = Depends(get_webhook_service)):
    settings = get_settings()
    if not authorization or authorization != settings.revenuecat_webhook_secret:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid webhook authorization",
        )
    payload = await request.json()
    return await service.handle_revenuecat_webhook(payload)
