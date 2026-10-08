import pytest
from pydantic import ValidationError

from ultimate_guillotine.cli.archive import Ruling


@pytest.mark.parametrize(
    "obsolete_field",
    [
        {"substitutions": {1: 2}},
        {"reviewed_trade_codes": ["T-2026-001"]},
    ],
)
def test_rulings_cannot_replace_gulag_qualifiers(obsolete_field):
    with pytest.raises(ValidationError):
        Ruling(
            week=2,
            actor="Commissioner",
            reason="Invalid attempt to change the pairing",
            **obsolete_field,
        )
