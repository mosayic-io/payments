from fastapi import APIRouter

from app.payments.routes.payments_router import router as payments_router
from app.payments.routes.webhooks_router import router as webhooks_router

router = APIRouter(prefix="/payments")
router.include_router(payments_router)
router.include_router(webhooks_router)
