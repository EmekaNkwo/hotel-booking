"""ReservationService unit tests (M8).

Unit tier: SQLite. Pessimistic locking is exercised structurally (the code
path runs) but the REAL concurrency proof is Postgres-only
(tests/integration/test_reservations_postgres.py).
"""

from datetime import timedelta

import pytest
from django.utils import timezone

from apps.availability.exceptions import InsufficientAvailability
from apps.availability.models import AvailabilitySlot
from apps.availability.services import AvailabilityService
from apps.reservations.models import Reservation, ReservationLine, ReservationStatus
from apps.reservations.services import ReservationLineRequest, ReservationQuery, ReservationService
from apps.shared.exceptions import TransitionNotAllowed
from apps.shared.value_objects import GuestCount, StayPeriod


@pytest.fixture
def today():
    return timezone.now().date()


@pytest.fixture
def stay(today):
    return StayPeriod(today, today + timedelta(days=2))


@pytest.fixture
def guest_count():
    return GuestCount(adults=2, children=0)


@pytest.fixture
def line_request(room_type, stay, guest_count):
    return ReservationLineRequest(
        room_type_id=room_type.id, stay_period=stay, guest_count=guest_count, quantity=1
    )


@pytest.fixture(autouse=True)
def _capacity(tenant, property, room_type, rate_plan, deposit_policy, today):
    AvailabilityService.initialize_horizon(
        tenant_id=tenant.id,
        property_id=property.id,
        room_type_id=room_type.id,
        total_units=3,
        start_date=today,
        horizon_days=10,
    )


@pytest.mark.django_db
class TestReserve:
    def test_creates_reservation_and_lines_and_holds_capacity(
        self, tenant, property, room_type, line_request, stay
    ):
        reservation = ReservationService.reserve(
            tenant=tenant,
            property=property,
            lines=[line_request],
            idempotency_key="r-1",
            guest_email="guest@example.com",
        )
        assert reservation.status == ReservationStatus.HELD
        assert reservation.reservation_ref
        assert ReservationLine.objects.filter(reservation=reservation).count() == 1
        slot = AvailabilitySlot.objects.get(
            tenant_id=tenant.id,
            property_id=property.id,
            room_type_id=room_type.id,
            business_date=stay.arrival,
        )
        assert slot.reserved == 1
        assert slot.sold == 0

    def test_pins_price_snapshot_on_reservation_and_line(self, tenant, property, line_request):
        reservation = ReservationService.reserve(
            tenant=tenant,
            property=property,
            lines=[line_request],
            idempotency_key="r-2",
            guest_email="guest@example.com",
        )
        assert reservation.price_snapshot["total_minor_units"] == 20000  # 2 nights * 10000
        line = reservation.lines.get()
        assert line.price_snapshot["total_minor_units"] == 20000

    def test_pins_deposit_policy_snapshot(self, tenant, property, line_request, deposit_policy):
        reservation = ReservationService.reserve(
            tenant=tenant,
            property=property,
            lines=[line_request],
            idempotency_key="r-3",
            guest_email="guest@example.com",
        )
        pinned = reservation.policy_snapshot["deposit"]
        assert pinned["policy_id"] == deposit_policy.id
        assert pinned["version"] == deposit_policy.version
        assert pinned["answer"]["required"] is True

    def test_resolves_guest_by_email(self, tenant, property, line_request):
        reservation = ReservationService.reserve(
            tenant=tenant,
            property=property,
            lines=[line_request],
            idempotency_key="r-4",
            guest_email="guest@example.com",
        )
        assert reservation.guest_profile is not None
        assert reservation.guest_profile.primary_email == "guest@example.com"

    def test_no_guest_identifier_leaves_guest_profile_null(self, tenant, property, line_request):
        reservation = ReservationService.reserve(
            tenant=tenant,
            property=property,
            lines=[line_request],
            idempotency_key="r-5",
        )
        assert reservation.guest_profile is None

    def test_is_idempotent_per_key(self, tenant, property, line_request):
        first = ReservationService.reserve(
            tenant=tenant,
            property=property,
            lines=[line_request],
            idempotency_key="same-key",
            guest_email="guest@example.com",
        )
        second = ReservationService.reserve(
            tenant=tenant,
            property=property,
            lines=[line_request],
            idempotency_key="same-key",
            guest_email="guest@example.com",
        )
        assert first.id == second.id
        assert Reservation.objects.count() == 1

    def test_insufficient_availability_leaves_zero_rows(
        self, tenant, property, room_type, stay, guest_count
    ):
        big_line = ReservationLineRequest(
            room_type_id=room_type.id,
            stay_period=stay,
            guest_count=guest_count,
            quantity=100,
        )
        with pytest.raises(InsufficientAvailability):
            ReservationService.reserve(
                tenant=tenant,
                property=property,
                lines=[big_line],
                idempotency_key="fail-1",
                guest_email="guest@example.com",
            )
        assert Reservation.objects.count() == 0
        assert ReservationLine.objects.count() == 0

    def test_multi_line_failure_rolls_back_the_whole_reservation(
        self, tenant, property, room_type, stay, guest_count
    ):
        """Line 1 fits, line 2 asks for more than remains — the whole
        reservation (including line 1's already-created hold) must roll
        back; no partial reservation, no partial hold."""
        ok_line = ReservationLineRequest(
            room_type_id=room_type.id,
            stay_period=stay,
            guest_count=guest_count,
            quantity=1,
        )
        overflow_line = ReservationLineRequest(
            room_type_id=room_type.id,
            stay_period=stay,
            guest_count=guest_count,
            quantity=100,
        )
        with pytest.raises(InsufficientAvailability):
            ReservationService.reserve(
                tenant=tenant,
                property=property,
                lines=[ok_line, overflow_line],
                idempotency_key="fail-2",
                guest_email="guest@example.com",
            )
        assert Reservation.objects.count() == 0
        slot = AvailabilitySlot.objects.get(
            tenant_id=tenant.id,
            property_id=property.id,
            room_type_id=room_type.id,
            business_date=stay.arrival,
        )
        assert slot.reserved == 0  # line 1's hold did NOT survive

    def test_requires_at_least_one_line(self, tenant, property):
        with pytest.raises(ValueError):
            ReservationService.reserve(
                tenant=tenant,
                property=property,
                lines=[],
                idempotency_key="empty-1",
            )


@pytest.mark.django_db
class TestExpire:
    def test_releases_hold_and_transitions(self, tenant, property, room_type, line_request, stay):
        reservation = ReservationService.reserve(
            tenant=tenant,
            property=property,
            lines=[line_request],
            idempotency_key="e-1",
            guest_email="guest@example.com",
            hold_minutes=1,
        )
        expired = ReservationService.expire(reservation.id)
        assert expired.status == ReservationStatus.EXPIRED
        slot = AvailabilitySlot.objects.get(
            tenant_id=tenant.id,
            property_id=property.id,
            room_type_id=room_type.id,
            business_date=stay.arrival,
        )
        assert slot.reserved == 0

    def test_repeated_sweep_execution_is_safe(self, tenant, property, line_request):
        reservation = ReservationService.reserve(
            tenant=tenant,
            property=property,
            lines=[line_request],
            idempotency_key="e-2",
            guest_email="guest@example.com",
        )
        ReservationService.expire(reservation.id)
        second = ReservationService.expire(reservation.id)  # already expired
        assert second.status == ReservationStatus.EXPIRED

    def test_overdue_holds_selector(self, tenant, property, line_request):
        reservation = ReservationService.reserve(
            tenant=tenant,
            property=property,
            lines=[line_request],
            idempotency_key="e-3",
            guest_email="guest@example.com",
            hold_minutes=1,
        )
        assert ReservationQuery.overdue_holds().count() == 0
        future = timezone.now() + timedelta(minutes=5)
        overdue = ReservationQuery.overdue_holds(now=future)
        assert list(overdue) == [reservation]


@pytest.mark.django_db
class TestHoldExpiryEnforcement:
    """R0.3 regression: an expired hold must never become a Booking,
    regardless of whether the sweep (``expire()``/Celery beat) has run —
    ``request_payment()``/``convert()`` carry their own authoritative,
    request-time guard, independent of the sweep."""

    @staticmethod
    def _backdate_past_expiry(reservation):
        """Sets ``hold_expiry_at`` to a value that (a) still satisfies the
        DB's ``hold_expiry_at > created_at`` constraint and (b) is already
        in the past by the time the guard checks ``timezone.now()`` a
        moment later — without racing the wall clock."""
        reservation.hold_expiry_at = reservation.created_at + timedelta(microseconds=1)
        reservation.save(update_fields=["hold_expiry_at"])

    def test_valid_hold_converts(self, tenant, property, line_request):
        """Baseline: a hold well inside its TTL converts normally."""
        reservation = ReservationService.reserve(
            tenant=tenant,
            property=property,
            lines=[line_request],
            idempotency_key="hx-1",
            guest_email="guest@example.com",
            hold_minutes=15,
        )
        ReservationService.request_payment(reservation.id, tenant_id=reservation.tenant_id)
        converted = ReservationService.convert(reservation.id, tenant_id=reservation.tenant_id)
        assert converted.status == ReservationStatus.CONVERTED

    def test_expired_hold_cannot_convert(self, tenant, property, room_type, line_request, stay):
        reservation = ReservationService.reserve(
            tenant=tenant,
            property=property,
            lines=[line_request],
            idempotency_key="hx-2",
            guest_email="guest@example.com",
            hold_minutes=15,
        )
        ReservationService.request_payment(reservation.id, tenant_id=reservation.tenant_id)
        self._backdate_past_expiry(reservation)

        with pytest.raises(TransitionNotAllowed):
            ReservationService.convert(reservation.id, tenant_id=reservation.tenant_id)

        # Rejected — and critically, NOT silently converted. The row stays
        # Awaiting_Payment (not yet reconciled to Expired) until the sweep
        # runs; the guard's job is only to make sure nothing can act on it
        # in the meantime, which it did.
        reservation.refresh_from_db()
        assert reservation.status == ReservationStatus.AWAITING_PAYMENT
        slot = AvailabilitySlot.objects.get(
            tenant_id=tenant.id,
            property_id=property.id,
            room_type_id=room_type.id,
            business_date=stay.arrival,
        )
        assert slot.reserved == 1  # hold still held — no Booking, no sale
        assert slot.sold == 0

    def test_expired_hold_cannot_request_payment(self, tenant, property, line_request):
        reservation = ReservationService.reserve(
            tenant=tenant,
            property=property,
            lines=[line_request],
            idempotency_key="hx-3",
            guest_email="guest@example.com",
            hold_minutes=15,
        )
        self._backdate_past_expiry(reservation)

        with pytest.raises(TransitionNotAllowed):
            ReservationService.request_payment(reservation.id, tenant_id=reservation.tenant_id)

        reservation.refresh_from_db()
        assert reservation.status == ReservationStatus.HELD

    def test_exact_expiry_instant_is_not_yet_expired(self, tenant, property, line_request):
        """Boundary: ``hold_expiry_at`` exactly equal to "now" is NOT past
        its deadline (strict ``<``, matching ``ReservationQuery.overdue_holds``'s
        own ``hold_expiry_at__lt=cutoff``) — the guard must not reject a
        request that lands in the same instant the hold expires."""
        reservation = ReservationService.reserve(
            tenant=tenant,
            property=property,
            lines=[line_request],
            idempotency_key="hx-4",
            guest_email="guest@example.com",
            hold_minutes=15,
        )
        # Pin hold_expiry_at one second into the future relative to the
        # guard's own timezone.now() call, to prove the not-yet-expired
        # path deterministically rather than racing the clock.
        reservation.hold_expiry_at = timezone.now() + timedelta(seconds=1)
        reservation.save(update_fields=["hold_expiry_at"])

        updated = ReservationService.request_payment(
            reservation.id, tenant_id=reservation.tenant_id
        )
        assert updated.status == ReservationStatus.AWAITING_PAYMENT

    def test_sweep_and_request_time_guard_agree(self, tenant, property, line_request):
        """Whether the periodic sweep (``expire()``) has already reconciled
        the row to Expired, or it hasn't run yet, a later convert attempt
        must be rejected either way — the guard doesn't depend on the sweep
        having run."""
        reservation = ReservationService.reserve(
            tenant=tenant,
            property=property,
            lines=[line_request],
            idempotency_key="hx-5",
            guest_email="guest@example.com",
            hold_minutes=15,
        )
        ReservationService.request_payment(reservation.id, tenant_id=reservation.tenant_id)
        self._backdate_past_expiry(reservation)

        # The sweep runs first (as Celery beat would).
        ReservationService.expire(reservation.id)
        reservation.refresh_from_db()
        assert reservation.status == ReservationStatus.EXPIRED

        # convert() rejects it too — for the ordinary "not awaiting_payment"
        # reason now, since the sweep already moved it to Expired.
        with pytest.raises(TransitionNotAllowed):
            ReservationService.convert(reservation.id, tenant_id=reservation.tenant_id)
        reservation.refresh_from_db()
        assert reservation.status == ReservationStatus.EXPIRED

    def test_repeated_convert_attempts_after_expiry_stay_consistently_rejected(
        self, tenant, property, room_type, line_request, stay
    ):
        """Idempotency/replay: retrying convert() on an expired-but-not-yet-
        swept reservation must keep failing cleanly and identically, never
        attempt a second inventory release or silently succeed."""
        reservation = ReservationService.reserve(
            tenant=tenant,
            property=property,
            lines=[line_request],
            idempotency_key="hx-6",
            guest_email="guest@example.com",
            hold_minutes=15,
        )
        ReservationService.request_payment(reservation.id, tenant_id=reservation.tenant_id)
        self._backdate_past_expiry(reservation)

        with pytest.raises(TransitionNotAllowed):
            ReservationService.convert(reservation.id, tenant_id=reservation.tenant_id)
        with pytest.raises(TransitionNotAllowed):
            ReservationService.convert(reservation.id, tenant_id=reservation.tenant_id)

        slot = AvailabilitySlot.objects.get(
            tenant_id=tenant.id,
            property_id=property.id,
            room_type_id=room_type.id,
            business_date=stay.arrival,
        )
        assert slot.reserved == 1  # hold untouched by either rejected attempt
        assert slot.sold == 0


@pytest.mark.django_db
class TestCancel:
    def test_releases_hold_and_transitions(self, tenant, property, room_type, line_request, stay):
        reservation = ReservationService.reserve(
            tenant=tenant,
            property=property,
            lines=[line_request],
            idempotency_key="c-1",
            guest_email="guest@example.com",
        )
        cancelled = ReservationService.cancel(
            tenant_id=tenant.id,
            reservation_id=reservation.id,
            idempotency_key="cancel-1",
        )
        assert cancelled.status == ReservationStatus.CANCELLED
        slot = AvailabilitySlot.objects.get(
            tenant_id=tenant.id,
            property_id=property.id,
            room_type_id=room_type.id,
            business_date=stay.arrival,
        )
        assert slot.reserved == 0

    def test_is_idempotent_per_key(self, tenant, property, line_request):
        reservation = ReservationService.reserve(
            tenant=tenant,
            property=property,
            lines=[line_request],
            idempotency_key="c-2",
            guest_email="guest@example.com",
        )
        first = ReservationService.cancel(
            tenant_id=tenant.id,
            reservation_id=reservation.id,
            idempotency_key="same-cancel-key",
        )
        second = ReservationService.cancel(
            tenant_id=tenant.id,
            reservation_id=reservation.id,
            idempotency_key="same-cancel-key",
        )
        assert first.status == second.status == ReservationStatus.CANCELLED

    def test_does_not_consult_policy_service(self, monkeypatch, tenant, property, line_request):
        """M8 ruling: cancellation is hold abandonment only — no penalty ask."""
        reservation = ReservationService.reserve(
            tenant=tenant,
            property=property,
            lines=[line_request],
            idempotency_key="c-3",
            guest_email="guest@example.com",
        )
        from apps.policies.services import PolicyService

        def _boom(*args, **kwargs):
            raise AssertionError("cancel() must not call PolicyService")

        monkeypatch.setattr(PolicyService, "resolve", _boom)
        monkeypatch.setattr(PolicyService, "can_cancel", _boom)
        ReservationService.cancel(
            tenant_id=tenant.id,
            reservation_id=reservation.id,
            idempotency_key="c-3-cancel",
        )  # must not raise


@pytest.mark.django_db
class TestConvert:
    def test_requires_awaiting_payment(self, tenant, property, line_request):
        reservation = ReservationService.reserve(
            tenant=tenant,
            property=property,
            lines=[line_request],
            idempotency_key="v-1",
            guest_email="guest@example.com",
        )
        assert reservation.status == ReservationStatus.HELD
        with pytest.raises(TransitionNotAllowed):
            ReservationService.convert(reservation.id, tenant_id=reservation.tenant_id)

    def test_converts_reserved_to_sold_and_transitions(
        self, tenant, property, room_type, line_request, stay
    ):
        reservation = ReservationService.reserve(
            tenant=tenant,
            property=property,
            lines=[line_request],
            idempotency_key="v-2",
            guest_email="guest@example.com",
        )
        ReservationService.request_payment(reservation.id, tenant_id=reservation.tenant_id)
        converted = ReservationService.convert(reservation.id, tenant_id=reservation.tenant_id)
        assert converted.status == ReservationStatus.CONVERTED
        slot = AvailabilitySlot.objects.get(
            tenant_id=tenant.id,
            property_id=property.id,
            room_type_id=room_type.id,
            business_date=stay.arrival,
        )
        assert slot.reserved == 0
        assert slot.sold == 1

    def test_cannot_convert_twice(self, tenant, property, line_request):
        reservation = ReservationService.reserve(
            tenant=tenant,
            property=property,
            lines=[line_request],
            idempotency_key="v-3",
            guest_email="guest@example.com",
        )
        ReservationService.request_payment(reservation.id, tenant_id=reservation.tenant_id)
        ReservationService.convert(reservation.id, tenant_id=reservation.tenant_id)
        with pytest.raises(TransitionNotAllowed):
            ReservationService.convert(reservation.id, tenant_id=reservation.tenant_id)

    def test_does_not_create_a_booking_reference(self, tenant, property, line_request):
        """M8 ruling: no Booking model dependency, no converted_booking_id."""
        reservation = ReservationService.reserve(
            tenant=tenant,
            property=property,
            lines=[line_request],
            idempotency_key="v-4",
            guest_email="guest@example.com",
        )
        ReservationService.request_payment(reservation.id, tenant_id=reservation.tenant_id)
        converted = ReservationService.convert(reservation.id, tenant_id=reservation.tenant_id)
        assert not hasattr(converted, "converted_booking_id")

    def test_wrong_tenant_id_cannot_convert_another_tenants_reservation(
        self, tenant, tenant2, property, line_request
    ):
        """R0.1 (P0 regression), domain-boundary tier: the guard lives in
        ``ReservationService.convert()`` itself, not only in the API view —
        proven here by calling the service directly with a real reservation
        but the WRONG tenant_id."""
        reservation = ReservationService.reserve(
            tenant=tenant,
            property=property,
            lines=[line_request],
            idempotency_key="v-5",
            guest_email="guest@example.com",
        )
        ReservationService.request_payment(reservation.id, tenant_id=reservation.tenant_id)

        with pytest.raises(Reservation.DoesNotExist):
            ReservationService.convert(reservation.id, tenant_id=tenant2.id)

        reservation.refresh_from_db()
        assert reservation.status == ReservationStatus.AWAITING_PAYMENT

    def test_wrong_tenant_id_cannot_request_payment_on_another_tenants_reservation(
        self, tenant, tenant2, property, line_request
    ):
        """Same domain-boundary guard on the earlier request_payment() step."""
        reservation = ReservationService.reserve(
            tenant=tenant,
            property=property,
            lines=[line_request],
            idempotency_key="v-6",
            guest_email="guest@example.com",
        )

        with pytest.raises(Reservation.DoesNotExist):
            ReservationService.request_payment(reservation.id, tenant_id=tenant2.id)

        reservation.refresh_from_db()
        assert reservation.status == ReservationStatus.HELD


@pytest.mark.django_db
class TestReservationQuery:
    def test_by_reservation_ref(self, tenant, property, line_request):
        reservation = ReservationService.reserve(
            tenant=tenant,
            property=property,
            lines=[line_request],
            idempotency_key="q-1",
            guest_email="guest@example.com",
        )
        found = ReservationQuery.by_reservation_ref(tenant, reservation.reservation_ref)
        assert found == reservation

    def test_active_for_property_excludes_terminal_states(self, tenant, property, line_request):
        held = ReservationService.reserve(
            tenant=tenant,
            property=property,
            lines=[line_request],
            idempotency_key="q-2",
            guest_email="guest@example.com",
        )
        active = ReservationQuery.active_for_property(property)
        assert list(active) == [held]
        ReservationService.cancel(
            tenant_id=tenant.id,
            reservation_id=held.id,
            idempotency_key="q-2-cancel",
        )
        assert ReservationQuery.active_for_property(property).count() == 0
