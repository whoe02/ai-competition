"""Account identity mutations; balances remain derived and untouchable."""

from __future__ import annotations

import uuid
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from kira.db.models import Account, User
from kira.money import Money

KINDS = ("bank", "ewallet", "cash")


class AccountNotFound(Exception):
    pass


class InvalidAccount(Exception):
    pass


@dataclass(frozen=True, slots=True)
class AccountView:
    id: uuid.UUID
    name: str
    kind: str


def _view(account: Account) -> AccountView:
    return AccountView(account.id, account.name, account.kind)


async def create_account(session: AsyncSession, user: User, *, name: str, kind: str) -> AccountView:
    if not name.strip() or kind not in KINDS:
        raise InvalidAccount("an account needs a name and a known kind")
    account = Account(
        user_id=user.id,
        name=name.strip(),
        kind=kind,
        # Creating an account must not create money. Balance import remains a
        # user-owned setup operation outside the Butler boundary.
        opening_balance=Money.zero(user.currency),
    )
    session.add(account)
    await session.flush()
    return _view(account)


async def update_account(
    session: AsyncSession,
    user: User,
    account_id: uuid.UUID,
    *,
    name: str | None = None,
    kind: str | None = None,
) -> AccountView:
    account = (
        await session.execute(
            select(Account).where(Account.id == account_id, Account.user_id == user.id)
        )
    ).scalar_one_or_none()
    if account is None:
        raise AccountNotFound(str(account_id))
    if name is not None:
        if not name.strip():
            raise InvalidAccount("account name cannot be blank")
        account.name = name.strip()
    if kind is not None:
        if kind not in KINDS:
            raise InvalidAccount("unknown account kind")
        account.kind = kind
    await session.flush()
    return _view(account)
