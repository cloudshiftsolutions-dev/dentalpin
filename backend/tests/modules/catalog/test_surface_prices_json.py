"""Surface-wise prices must be storable in the JSONB column (DENTALPIN-65)."""

import json
from decimal import Decimal

from app.modules.catalog.pricing import _resolve_surface_tier_price
from app.modules.catalog.schemas import CatalogItemUpdate
from app.modules.catalog.service import _jsonable_surface_prices


def test_surface_prices_from_the_form_become_json_storable() -> None:
    payload = CatalogItemUpdate(surface_prices={"1": 600, "2": "900.50", "3": 1200})
    data = payload.model_dump(exclude_unset=True)
    assert isinstance(data["surface_prices"]["1"], Decimal)

    _jsonable_surface_prices(data)

    assert data["surface_prices"] == {"1": "600", "2": "900.50", "3": "1200"}
    json.dumps(data["surface_prices"])


def test_stored_string_tiers_still_price_correctly() -> None:
    tiers = {"1": "600", "2": "900.50", "3": "1200"}
    assert _resolve_surface_tier_price(tiers, 2, Decimal("0")) == Decimal("900.50")
    assert _resolve_surface_tier_price(tiers, 5, Decimal("0")) == Decimal("1200")


def test_missing_prices_are_left_alone() -> None:
    data: dict = {"default_price": Decimal("10")}
    _jsonable_surface_prices(data)
    assert "surface_prices" not in data
