"""Registration, login, refresh-token rotation, and logout."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request, Response, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from kira.api.deps import UNAUTHORISED, CurrentUser, SessionDep
from kira.api.schemas import (
    FinancialProfileUpdateRequest,
    LoginRequest,
    RegisterRequest,
    TokenResponse,
    UserResponse,
)
from kira.config import get_settings
from kira.db.models import User
from kira.money import Money
from kira.services.auth import (
    REFRESH_COOKIE,
    AuthError,
    create_access_token,
    hash_password,
    issue_refresh_token,
    revoke_refresh_token,
    rotate_refresh_token,
    verify_password,
)
from kira.services.clock import today_for

router = APIRouter(prefix="/v1/auth", tags=["auth"])


def _set_refresh_cookie(response: Response, raw: str) -> None:
    settings = get_settings()
    response.set_cookie(
        REFRESH_COOKIE,
        raw,
        httponly=True,
        samesite="lax",
        secure=False,
        max_age=settings.refresh_token_ttl_days * 24 * 60 * 60,
        path="/v1/auth",
    )


@router.post("/register", status_code=status.HTTP_201_CREATED, response_model=TokenResponse)
async def register(body: RegisterRequest, response: Response, session: SessionDep) -> TokenResponse:
    today = today_for()
    user = User(
        email=str(body.email).lower(),
        password_hash=hash_password(body.password),
        display_name=body.display_name,
        buffer=Money(0),
        next_payday=today,
        cycle_start=today,
        cycle_days=30,
    )
    session.add(user)
    try:
        await session.flush()
    except IntegrityError as exc:
        await session.rollback()
        raise HTTPException(status.HTTP_409_CONFLICT, "That email is already registered") from exc

    raw = await issue_refresh_token(session, user)
    await session.commit()
    _set_refresh_cookie(response, raw)
    return TokenResponse(access_token=create_access_token(user.id))


@router.post("/login", response_model=TokenResponse)
async def login(body: LoginRequest, response: Response, session: SessionDep) -> TokenResponse:
    user = (
        await session.execute(select(User).where(User.email == str(body.email).lower()))
    ).scalar_one_or_none()
    ok = verify_password(body.password, user.password_hash) if user else False
    if not user or not ok:
        raise UNAUTHORISED
    raw = await issue_refresh_token(session, user)
    await session.commit()
    _set_refresh_cookie(response, raw)
    return TokenResponse(access_token=create_access_token(user.id))


@router.post("/refresh", response_model=TokenResponse)
async def refresh(request: Request, response: Response, session: SessionDep) -> TokenResponse:
    raw = request.cookies.get(REFRESH_COOKIE)
    if not raw:
        raise UNAUTHORISED
    try:
        user, replacement = await rotate_refresh_token(session, raw)
    except AuthError as exc:
        raise UNAUTHORISED from exc
    _set_refresh_cookie(response, replacement)
    return TokenResponse(access_token=create_access_token(user.id))


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
async def logout(request: Request, response: Response, session: SessionDep) -> None:
    raw = request.cookies.get(REFRESH_COOKIE)
    if raw:
        await revoke_refresh_token(session, raw)
    response.delete_cookie(REFRESH_COOKIE, path="/v1/auth")


@router.get("/me", response_model=UserResponse)
async def me(user: CurrentUser) -> UserResponse:
    return UserResponse(
        id=user.id,
        email=user.email,
        display_name=user.display_name,
        currency=user.currency,
        buffer_sen=user.buffer.sen,
        next_payday=user.next_payday,
        cycle_start=user.cycle_start,
        cycle_days=user.cycle_days,
        monthly_income_sen=user.monthly_income.sen,
    )


@router.patch("/me", response_model=UserResponse)
async def update_financial_profile(
    body: FinancialProfileUpdateRequest, user: CurrentUser, session: SessionDep
) -> UserResponse:
    """Update the recurring income forecast; it never creates cash by itself."""
    if body.monthly_income_sen is not None:
        user.monthly_income = Money(body.monthly_income_sen, user.currency)
    if body.next_payday is not None:
        user.next_payday = body.next_payday
    await session.commit()
    return await me(user)
