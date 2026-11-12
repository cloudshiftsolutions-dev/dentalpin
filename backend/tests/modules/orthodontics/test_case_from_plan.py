"""Which orthodontic catalog items open a case, and with which appliance (no DB)."""

import pytest

from app.modules.orthodontics.events import appliance_for
from app.modules.orthodontics.schemas import ApplianceType


@pytest.mark.parametrize(
    ("code", "appliance"),
    [
        ("ORTO-METAL", "brackets_metal"),
        ("ORTO-CERAM", "brackets_esthetic"),
        ("ORTO-INV-FULL", "aligners"),
        ("ORTO-ATTACH", "aligners"),
        ("ORTO-PALATAL-EXP", "functional"),
        ("ORTO-RET-REM", "retention"),
        ("CLINIC-CUSTOM-BRACES", "brackets_metal"),
    ],
)
def test_case_starting_items_map_to_an_appliance(code: str, appliance: str) -> None:
    assert appliance_for(code) == appliance
    assert appliance in ApplianceType.__args__


@pytest.mark.parametrize("code", ["ORTO-REVIEW", "ORTO-SEPARATOR", "ORTO-TAD", "ORTO-BRACK-DEBOND"])
def test_support_items_never_open_a_case(code: str) -> None:
    assert appliance_for(code) is None
