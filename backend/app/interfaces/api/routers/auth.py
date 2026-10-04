from __future__ import annotations

from fastapi import APIRouter, Depends
from fastapi.security import OAuth2PasswordRequestForm

from app.application.dto import Actor
from app.composition import Container
from app.interfaces.api.deps import current_actor, get_container
from app.interfaces.api.schemas import LoginOut, UserOut

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/login", response_model=LoginOut)
async def login(form: OAuth2PasswordRequestForm = Depends(), c: Container = Depends(get_container)) -> LoginOut:
    """OAuth2 password flow (form-encoded `username` = email). Same error for unknown user and bad password."""
    user, token = await c.auth.login(form.username, form.password)
    return LoginOut(access_token=token, expires_in=c.auth.expires_in_seconds, user=UserOut.model_validate(user))


@router.get("/me", response_model=UserOut)
async def me(actor: Actor = Depends(current_actor), c: Container = Depends(get_container)) -> UserOut:
    return UserOut.model_validate(await c.auth.get_user(actor))
