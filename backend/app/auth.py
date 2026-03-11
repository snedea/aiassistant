from __future__ import annotations
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from app.config import get_settings

_bearer_scheme = HTTPBearer(auto_error=False)


async def require_auth(credentials: HTTPAuthorizationCredentials | None = Depends(_bearer_scheme)) -> None:
    settings = get_settings()
    if not settings.api_key:
        return None
    if credentials is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Missing authentication token", headers={"WWW-Authenticate": "Bearer"})
    if credentials.credentials != settings.api_key:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid authentication token", headers={"WWW-Authenticate": "Bearer"})
    return None
