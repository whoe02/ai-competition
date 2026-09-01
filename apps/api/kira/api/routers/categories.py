"""The category vocabulary, as a list a client can offer.

The slugs live in `kira.categories` because the filter chips, the ledger and the
readers all draw on the same list. A client that has to guess would send "Makan"
where the ledger holds "food", and no filter can put those back together — so the
list is published rather than duplicated.
"""

from __future__ import annotations

from fastapi import APIRouter

from kira.api.deps import CurrentUser
from kira.api.schemas import CategoryResponse
from kira.categories import CATEGORIES

router = APIRouter(prefix="/v1/categories", tags=["categories"])


@router.get("", response_model=list[CategoryResponse])
async def list_categories(user: CurrentUser) -> list[CategoryResponse]:
    return [CategoryResponse(slug=item.slug, label=item.label) for item in CATEGORIES]
