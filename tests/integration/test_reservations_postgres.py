"""Postgres integration tests — Reservation concurrency proofs (M8).

Skipped (not failed) when collected under the SQLite unit settings — mirrors
``tests/integration/test_availability_postgres.py``.

Two real, independent connections/transactions per race (Django opens one
connection per OS thread lazily — no mocking of concurrency), exactly the
``TestAntiOversellRace`` shape from M7.
"""

import threading
from datetime import date, timedelta

import pytest
from django.db import connection
from django.utils import timezone

from apps.availability.models import AvailabilitySlot
from apps.availability.services import AvailabilityService
from apps.policies.services import PolicyService
from apps.pricing.services import PricingService
from apps.properties.models import Property
from apps.reservations.models import Reservation, ReservationLine, ReservationStatus
from apps.reservations.services import ReservationLineRequest, ReservationService
from apps.rooms.models import RoomType
from apps.shared.exceptions import TransitionNotAllowed
from apps.shared.value_objects import GuestCount, StayPeriod
from apps.tenants.models import Tenant

pytestmark = pytest.mark.skipif(
    connection.vendor != "postgresql", reason="real concurrent connections require Postgres"
)


def _bootstrap(*, total_units: int, nights: int = 2):
    tenant = Tenant.objects.create(
        code=f"res{timezone.now().timestamp()}", name="Res Race", base_currency="NGN"
    )
    property_ = Property.objects.create(
        tenant=tenant,
        code="RES1",
        name="Res Hotel",
        status=Property.Status.ACTIVE,
        currency="USD",
        timezone="UTC",
        check_in_time="14:00:00",
        check_out_time="12:00:00",
    )
    room_type = RoomType.objects.create(
        tenant=tenant,
        code="RES-KING",
        name="Res King",
        status=RoomType.Status.ACTIVE,
        max_occupancy=2,
    )
    rate_plan = PricingService.create_rate_plan(
        tenant=tenant,
        property=property_,
        room_type=room_type,
        code="RES-RACK",
        base_rate_minor_units=10000,
        currency=property_.currency,
    )
    PricingService.activate_rate_plan(rate_plan)
    draft = PolicyService.create_draft(
        tenant,
        "deposit",
        {"required": False},
        date(2020, 1, 1),
    )
    PolicyService.publish(draft.id)

    today = timezone.now().date()
    AvailabilityService.initialize_horizon(
        tenant_id=tenant.id,
        property_id=property_.id,
        room_type_id=room_type.id,
        total_units=total_units,
        start_date=today,
        horizon_days=nights,
    )
    stay = StayPeriod(today, today + timedelta(days=nights))
    return tenant, property_, room_type, stay


class TestConcurrentReserveRace:
    """Two real connections racing for the last unit."""

    @pytest.mark.django_db(transaction=True)
    def test_exactly_one_reserve_wins_the_last_unit(self):
        tenant, property_, room_type, stay = _bootstrap(total_units=1)
        line = ReservationLineRequest(
            room_type_id=room_type.id,
            stay_period=stay,
            guest_count=GuestCount(adults=1, children=0),
            quantity=1,
        )

        results: dict[str, tuple[Reservation | None, Exception | None]] = {}
        barrier = threading.Barrier(2)

        def _attempt(caller: str, idempotency_key: str) -> None:
            try:
                barrier.wait(timeout=10)
                reservation = ReservationService.reserve(
                    tenant=tenant,
                    property=property_,
                    lines=[line],
                    idempotency_key=idempotency_key,
                    guest_email=f"{caller}@example.com",
                )
                results[caller] = (reservation, None)
            except Exception as exc:  # noqa: BLE001 — captured for assertion
                results[caller] = (None, exc)
            finally:
                connection.close()

        thread_a = threading.Thread(target=_attempt, args=("A", "res-race-key-A"))
        thread_b = threading.Thread(target=_attempt, args=("B", "res-race-key-B"))
        thread_a.start()
        thread_b.start()
        thread_a.join(timeout=15)
        thread_b.join(timeout=15)

        assert set(results) == {"A", "B"}
        successes = [c for c, (res, exc) in results.items() if exc is None]
        failures = [(c, exc) for c, (res, exc) in results.items() if exc is not None]
        assert len(successes) == 1, f"expected exactly one winner, got {results!r}"
        assert len(failures) == 1, f"expected exactly one loser, got {results!r}"

        loser, loser_exc = failures[0]
        assert type(loser_exc).__name__ == "InsufficientAvailability", (
            f"loser must fail with InsufficientAvailability, got {loser_exc!r}"
        )

        # Loser leaves ZERO Reservation/ReservationLine rows.
        assert Reservation.objects.filter(tenant=tenant).count() == 1
        assert ReservationLine.objects.filter(reservation__tenant=tenant).count() == 1

        # Final slot state: reserved=1, sold=0, remaining=0 on every night.
        slots = AvailabilitySlot.objects.filter(
            tenant_id=tenant.id,
            property_id=property_.id,
            room_type_id=room_type.id,
        ).order_by("business_date")
        assert [s.reserved for s in slots] == [1, 1]
        assert [s.sold for s in slots] == [0, 0]
        assert [s.remaining for s in slots] == [0, 0]


class TestConcurrentExpireVsConvertRace:
    """Two real connections: one expires, one converts, same reservation."""

    @pytest.mark.django_db(transaction=True)
    def test_exactly_one_transition_wins(self):
        tenant, property_, room_type, stay = _bootstrap(total_units=5)
        line = ReservationLineRequest(
            room_type_id=room_type.id,
            stay_period=stay,
            guest_count=GuestCount(adults=1, children=0),
            quantity=2,
        )
        reservation = ReservationService.reserve(
            tenant=tenant,
            property=property_,
            lines=[line],
            idempotency_key="expire-convert-setup",
            guest_email="racer@example.com",
        )
        ReservationService.request_payment(reservation.id, tenant_id=reservation.tenant_id)
        reservation.refresh_from_db()
        assert reservation.status == ReservationStatus.AWAITING_PAYMENT

        results: dict[str, tuple[Reservation | None, Exception | None]] = {}
        barrier = threading.Barrier(2)

        def _expire() -> None:
            try:
                barrier.wait(timeout=10)
                results["expire"] = (ReservationService.expire(reservation.id), None)
            except Exception as exc:  # noqa: BLE001
                results["expire"] = (None, exc)
            finally:
                connection.close()

        def _convert() -> None:
            try:
                barrier.wait(timeout=10)
                results["convert"] = (ReservationService.convert(reservation.id, tenant_id=reservation.tenant_id), None)
            except Exception as exc:  # noqa: BLE001
                results["convert"] = (None, exc)
            finally:
                connection.close()

        thread_expire = threading.Thread(target=_expire)
        thread_convert = threading.Thread(target=_convert)
        thread_expire.start()
        thread_convert.start()
        thread_expire.join(timeout=15)
        thread_convert.join(timeout=15)

        assert set(results) == {"expire", "convert"}

        reservation.refresh_from_db()
        slots = AvailabilitySlot.objects.filter(
            tenant_id=tenant.id,
            property_id=property_.id,
            room_type_id=room_type.id,
        ).order_by("business_date")

        expire_outcome, expire_exc = results["expire"]
        convert_outcome, convert_exc = results["convert"]

        if convert_exc is None:
            # convert() won the lock first: reservation converted, expire()
            # found it already outside {Held, Awaiting_Payment} and was a
            # documented no-op (it does NOT raise — see ReservationService.expire).
            assert reservation.status == ReservationStatus.CONVERTED
            assert expire_exc is None
            assert expire_outcome.status == ReservationStatus.CONVERTED  # unchanged no-op
            assert [s.sold for s in slots] == [2, 2]
            assert [s.reserved for s in slots] == [0, 0]
        else:
            # expire() won the lock first: reservation expired, convert()'s
            # explicit Awaiting_Payment guard rejects cleanly.
            assert reservation.status == ReservationStatus.EXPIRED
            assert isinstance(convert_exc, TransitionNotAllowed)
            assert [s.reserved for s in slots] == [0, 0]
            assert [s.sold for s in slots] == [0, 0]

        # Never both released AND sold, never neither: exactly one of
        # {sold==2, reserved==0-from-release} holds across all nights.
        total_committed = sum(s.sold for s in slots) + sum(s.reserved for s in slots)
        assert total_committed in (0, 4)  # 0 = fully released; 4 = fully sold (2 units x 2 nights)
