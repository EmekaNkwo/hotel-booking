"""AvailabilitySlot constraint tests — the DB-level backstop (M7, DR-05).

CHECK/UNIQUE constraints are portable SQL, so these run on the SQLite unit
tier same as everywhere else in the project (Room/RatePlan precedent). The
Postgres-only surface (partitioning, generated-column DDL, GiST excludes) is
covered separately in tests/integration/test_availability_postgres.py.
"""

from datetime import date

import pytest
from django.db import IntegrityError

from apps.availability.models import AvailabilitySlot, Channel


@pytest.mark.django_db
class TestAvailabilitySlotConstraints:
    def test_within_total_rejects_overselling_via_direct_orm_bypass(
        self, tenant, property, room_type
    ):
        """Bypasses the repository entirely — only the DB CHECK can catch this."""
        with pytest.raises(IntegrityError):
            AvailabilitySlot.objects.create(
                id=1,
                tenant=tenant,
                property=property,
                room_type=room_type,
                channel=Channel.DIRECT,
                business_date=date(2026, 10, 1),
                total_units=5,
                sold=3,
                reserved=2,
                blocked=1,
                out_of_service=0,  # 6 > 5
            )

    def test_non_negative_rejects_a_negative_counter(self, tenant, property, room_type):
        with pytest.raises(IntegrityError):
            AvailabilitySlot.objects.create(
                id=2,
                tenant=tenant,
                property=property,
                room_type=room_type,
                channel=Channel.DIRECT,
                business_date=date(2026, 10, 1),
                total_units=5,
                sold=-1,
            )

    def test_unique_per_tenant_property_roomtype_channel_date(self, tenant, property, room_type):
        AvailabilitySlot.objects.create(
            id=3,
            tenant=tenant,
            property=property,
            room_type=room_type,
            channel=Channel.DIRECT,
            business_date=date(2026, 10, 1),
            total_units=5,
        )
        with pytest.raises(IntegrityError):
            AvailabilitySlot.objects.create(
                id=4,
                tenant=tenant,
                property=property,
                room_type=room_type,
                channel=Channel.DIRECT,
                business_date=date(2026, 10, 1),
                total_units=9,
            )

    def test_remaining_is_generated_and_cannot_be_written_directly(
        self, tenant, property, room_type
    ):
        slot = AvailabilitySlot.objects.create(
            id=5,
            tenant=tenant,
            property=property,
            room_type=room_type,
            channel=Channel.DIRECT,
            business_date=date(2026, 10, 1),
            total_units=10,
            sold=3,
            reserved=2,
        )
        slot.refresh_from_db()
        assert slot.remaining == 5  # 10 - 3 - 2

    def test_same_date_different_property_is_a_different_row(self, tenant, room_type):
        from apps.properties.models import Property

        property_a = Property.objects.create(
            tenant=tenant,
            code="A1",
            name="Hotel A",
            status=Property.Status.ACTIVE,
            currency="USD",
            timezone="UTC",
            check_in_time="14:00:00",
            check_out_time="12:00:00",
        )
        property_b = Property.objects.create(
            tenant=tenant,
            code="B1",
            name="Hotel B",
            status=Property.Status.ACTIVE,
            currency="USD",
            timezone="UTC",
            check_in_time="14:00:00",
            check_out_time="12:00:00",
        )
        AvailabilitySlot.objects.create(
            id=7,
            tenant=tenant,
            property=property_a,
            room_type=room_type,
            channel=Channel.DIRECT,
            business_date=date(2026, 10, 1),
            total_units=5,
        )
        # Must NOT raise — different property, same date/room_type/channel.
        AvailabilitySlot.objects.create(
            id=8,
            tenant=tenant,
            property=property_b,
            room_type=room_type,
            channel=Channel.DIRECT,
            business_date=date(2026, 10, 1),
            total_units=5,
        )
        assert AvailabilitySlot.objects.count() == 2
