# ruff: noqa: B008

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends

from app.application.dto import Actor
from app.composition import Container
from app.domain.enums import UserRole
from app.interfaces.api.deps import get_container, require_roles
from app.interfaces.api.schemas import UserCreate, UserOut, UserUpdate

router = APIRouter(prefix="/users", tags=["users"])
_admin = require_roles(UserRole.ADMIN)


@router.get("", response_model=list[UserOut])
async def list_users(actor: Actor = Depends(_admin), c: Container = Depends(get_container)):
    return await c.users.list(actor)


@router.post("", response_model=UserOut, status_code=201)
async def create_user(body: UserCreate, actor: Actor = Depends(_admin), c: Container = Depends(get_container)):
    return await c.users.create(actor, **body.model_dump())


@router.patch("/{user_id}", response_model=UserOut)
async def update_user(
    user_id: uuid.UUID, body: UserUpdate, actor: Actor = Depends(_admin), c: Container = Depends(get_container)
):
    return await c.users.update(actor, user_id, **body.model_dump(exclude_unset=True))