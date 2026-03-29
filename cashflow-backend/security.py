import hmac
from typing import Optional

from fastapi import HTTPException, Security, status
from fastapi.security import APIKeyHeader, HTTPAuthorizationCredentials, HTTPBearer

from config import settings


api_key_header = APIKeyHeader(name="X-API-Key", auto_error=False)
bearer_scheme = HTTPBearer(auto_error=False)


def _extract_key(
    x_api_key: Optional[str],
    bearer: Optional[HTTPAuthorizationCredentials],
) -> Optional[str]:
    if x_api_key:
        return x_api_key.strip()
    if bearer and bearer.scheme.lower() == "bearer":
        return bearer.credentials.strip()
    return None


async def require_api_key(
    x_api_key: Optional[str] = Security(api_key_header),
    bearer: Optional[HTTPAuthorizationCredentials] = Security(bearer_scheme),
) -> None:
    """
    Protect API routes with either:
    - X-API-Key: <key>
    - Authorization: Bearer <key>
    """
    if not settings.AUTH_REQUIRED:
        return

    if not settings.API_KEY:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Server auth misconfiguration.",
        )

    supplied_key = _extract_key(x_api_key, bearer)
    if not supplied_key or not hmac.compare_digest(supplied_key, settings.API_KEY):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Unauthorized.",
            headers={"WWW-Authenticate": "Bearer"},
        )
