import uuid

import pytest
from pydantic import ValidationError

from firewatch.api.routers.inspections import InspectionCreate, same_request
from firewatch.db.models import Inspection


def payload(**changes):
    return {
        "id": str(uuid.uuid4()),
        "event_id": "bs-FE17518",
        "purpose": "damage",
        "note": "  Проверить лесополосу  ",
        "site": [43.1, 48.2],
        "access": None,
    } | changes


def test_coordinates_and_trim():
    value = InspectionCreate(**payload())
    assert value.site == (43.1, 48.2)
    assert value.note == "Проверить лесополосу"


@pytest.mark.parametrize(
    "changes",
    [
        {"site": [181, 48]},
        {"site": [43, 86]},
        {"site": [43]},
        {"site": [float("nan"), 48]},
        {"access": [43, float("inf")]},
        {"purpose": "dispatch"},
        {"note": "a" * 1001},
        {"event_id": ""},
        {"unexpected": True},
        {"id": "not-a-uuid"},
    ],
)
def test_invalid_requests(changes):
    with pytest.raises(ValidationError):
        InspectionCreate(**payload(**changes))


def test_idempotency_requires_the_same_content():
    value = InspectionCreate(**payload())
    row = Inspection(**value.model_dump(mode="json"), share_token="example", snapshot={})
    assert same_request(row, value)
    assert not same_request(row, value.model_copy(update={"note": "changed"}))
    assert not same_request(row, value.model_copy(update={"access": (43.2, 48.3)}))
