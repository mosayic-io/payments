from fastapi import HTTPException, status


class PaymentError(HTTPException):
    def __init__(self, detail: str, status_code: int = status.HTTP_400_BAD_REQUEST):
        super().__init__(status_code=status_code, detail=detail)


class WebhookVerificationError(HTTPException):
    def __init__(self, detail: str = "Invalid webhook signature"):
        super().__init__(status_code=status.HTTP_400_BAD_REQUEST, detail=detail)
