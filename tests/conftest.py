import pytest
import pytest_asyncio
from unittest.mock import AsyncMock, MagicMock

from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from app.payments import router as payments_router


@pytest.fixture
def mock_user():
    user = MagicMock()
    user.id = "test-user-123"
    user.email = "test@example.com"
    return user


@pytest.fixture
def mock_auth_dependency(mock_user):
    async def _get_user():
        return mock_user

    return _get_user


@pytest.fixture
def mock_db_client():
    client = MagicMock()
    client.table = MagicMock(return_value=client)
    client.select = MagicMock(return_value=client)
    client.insert = MagicMock(return_value=client)
    client.update = MagicMock(return_value=client)
    client.upsert = MagicMock(return_value=client)
    client.eq = MagicMock(return_value=client)
    client.in_ = MagicMock(return_value=client)
    client.single = MagicMock(return_value=client)
    client.order = MagicMock(return_value=client)
    client.limit = MagicMock(return_value=client)
    client.execute = AsyncMock(return_value=MagicMock(data=[]))
    return client


@pytest.fixture
def mock_db_dependency(mock_db_client):
    async def _get_db():
        return mock_db_client

    return _get_db


@pytest.fixture
def payments_app(mock_auth_dependency, mock_db_dependency):
    """Standalone FastAPI app with only the payments module mounted."""
    from app.core.auth import get_current_user
    from app.core.supabase_client import get_supabase_client

    app = FastAPI()
    app.include_router(payments_router)
    app.dependency_overrides[get_current_user] = mock_auth_dependency
    app.dependency_overrides[get_supabase_client] = mock_db_dependency
    return app


@pytest_asyncio.fixture
async def payments_client(payments_app):
    transport = ASGITransport(app=payments_app)
    async with AsyncClient(
        transport=transport, base_url="http://testserver"
    ) as client:
        yield client
