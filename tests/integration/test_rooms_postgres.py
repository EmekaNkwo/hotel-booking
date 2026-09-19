"""Postgres integration tests — ``RoomQuery.with_attributes()`` (M3).

``with_attributes()`` filters ``RoomType.attributes`` (a ``JSONField``) with
Django's ``__contains`` lookup, which needs native JSON containment support
(``@>`` in Postgres) — SQLite does not implement it at all (Django raises
``NotSupportedError`` there, it does not silently degrade), so this cannot
be a ``tests/unit`` case the way the rest of ``RoomQuery`` is. This was
previously (incorrectly) asserted under ``tests/unit/rooms/test_models.py``,
which fails there not because of a product defect but because the unit tier
deliberately runs on SQLite for speed — this test belongs here instead,
mirroring ``tests/integration/test_guests_postgres.py`` and
``test_rls.py``: skipped (not failed) when collected under SQLite unit
settings.
"""

import pytest
from django.db import connection

from apps.properties.models import Property
from apps.rooms.models import Room, RoomQuery, RoomType
from apps.tenants.models import Tenant

pytestmark = pytest.mark.skipif(
    connection.vendor != "postgresql", reason="JSONField __contains needs native JSON containment"
)


@pytest.fixture
def tenant(db):
    return Tenant.objects.create(code="acme", name="Acme Hotels", base_currency="NGN")


@pytest.fixture
def property(tenant):
    return Property.objects.create(
        tenant=tenant,
        code="TEST001",
        name="Test Hotel",
        status=Property.Status.ACTIVE,
        currency="USD",
        timezone="UTC",
        check_in_time="14:00:00",
        check_out_time="12:00:00",
    )


@pytest.mark.django_db
class TestRoomQueryWithAttributes:
    def test_with_attributes_filters_by_room_type_attributes(self, tenant, property):
        room_type_with_view = RoomType.objects.create(
            tenant=tenant,
            code="DELUXE",
            name="Deluxe Room",
            status=RoomType.Status.ACTIVE,
            max_occupancy=2,
            attributes={"view": "ocean", "balcony": True},
        )
        room_type_without_view = RoomType.objects.create(
            tenant=tenant,
            code="STD",
            name="Standard Room",
            status=RoomType.Status.ACTIVE,
            max_occupancy=2,
            attributes={"view": "street"},
        )
        room = Room.objects.create(
            tenant=tenant, property=property, room_type=room_type_with_view, code="201",
        )
        other_room = Room.objects.create(
            tenant=tenant, property=property, room_type=room_type_without_view, code="202",
        )

        rooms = RoomQuery.with_attributes({"view": "ocean"})
        assert room in rooms
        assert other_room not in rooms
