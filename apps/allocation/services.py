"""Allocation Engine (M11, SDD S11.6, DDS S12, DMS S12, DR-11).

Authoritative references:
- SDD S11.6 (Allocation Engine — "which physical room?"), S9.3 (Room state
  machine, reused unmodified)
- DDS S12 — Allocation (``allocation_record`` schema + locking)
- DMS S12 — Allocation aggregate, invariants #1-#5
- Implementation roadmap M11

``AllocationService.allocate_line()`` is the ONLY entry point. It composes
``RoomQuery`` (M3, read-only) and ``RoomStateMachine.apply()`` (M3,
unmodified) — it NEVER writes ``Room.operational_state`` directly, never
touches ``AvailabilitySlot``/Pricing/Reservation/Booking economics, and
never resolves guest identity (it reads the guest already on the booking,
exactly like ``BookingService.confirm()`` did with Reservation in M9).

Portfolio scope note: in this system, allocation IS the physical check-in
boundary —

    BookingLine.confirmed -> physical Room allocated -> BookingLine.checked_in

There is no separate "room pre-assigned" vs. "guest physically checked in"
state; a future milestone would have to deliberately introduce that
distinction rather than assume this model already supports it.
"""

from dataclasses import asdict, dataclass, field

from apps.allocation.exceptions import BookingLineNotAllocatable, NoEligibleRoom
from apps.allocation.models import AllocationRecord
from apps.bookings.models import BookingLine, BookingStatus
from apps.rooms.models import Room, RoomQuery
from apps.rooms.services import RoomStateMachine
from apps.shared.services.idempotency import IdempotencyService
from apps.shared.services.outbox import OutboxService


@dataclass(frozen=True, slots=True)
class AllocationCriteria:
    """The immutable input set a scoring decision is made from (DMS S12).

    Not a Shared Kernel value object — like ``ReservationLineRequest`` (M8)
    and ``ReservationLine`` fan-out (M9), this composes allocation-specific
    inputs, not cross-domain vocabulary.
    """

    booking_line_id: int
    room_type_id: int
    guest_profile_id: int | None
    candidate_room_ids: tuple[int, ...]

    def to_dict(self) -> dict:
        return {
            "booking_line_id": self.booking_line_id,
            "room_type_id": self.room_type_id,
            "guest_profile_id": self.guest_profile_id,
            "candidate_room_ids": list(self.candidate_room_ids),
        }


@dataclass(frozen=True, slots=True)
class RoomScore:
    """One candidate's score + the factor that produced it (explainability,
    FR-ALL-02). ``stay_continuity`` is 1 if the guest previously stayed in
    this exact room, else 0 — the only scored factor in the v1 scorer
    (M11 ruling); ``room_id`` breaks every tie deterministically."""

    room_id: int
    stay_continuity: int

    def to_dict(self) -> dict:
        return asdict(self)

    @property
    def sort_key(self) -> tuple[int, int]:
        # Higher stay_continuity wins; among equals, lowest room_id wins
        # (DMS invariant #2: deterministic for the same inputs).
        return (-self.stay_continuity, self.room_id)


@dataclass(frozen=True, slots=True)
class AllocationDecision:
    criteria: AllocationCriteria
    scores: tuple[RoomScore, ...] = field(default_factory=tuple)

    def ordered_room_ids(self) -> list[int]:
        return [s.room_id for s in sorted(self.scores, key=lambda s: s.sort_key)]

    def reason_for(self, room_id: int) -> str:
        score = next(s for s in self.scores if s.room_id == room_id)
        if score.stay_continuity:
            return "stay continuity: guest previously occupied this room"
        return "deterministic tie-break: lowest eligible room id"


def _score_candidates(criteria: AllocationCriteria) -> AllocationDecision:
    """Pure scoring: value objects in, an ordered decision out (no DB
    writes, no locking — the locked re-check happens in ``allocate_line``)."""
    prior_rooms: set[int] = set()
    if criteria.guest_profile_id is not None:
        prior_rooms = set(
            BookingLine.objects.filter(
                booking__guest_profile_id=criteria.guest_profile_id,
                room_id__in=criteria.candidate_room_ids,
            )
            .exclude(pk=criteria.booking_line_id)
            .values_list("room_id", flat=True)
        )
    scores = tuple(
        RoomScore(room_id=room_id, stay_continuity=1 if room_id in prior_rooms else 0)
        for room_id in criteria.candidate_room_ids
    )
    return AllocationDecision(criteria=criteria, scores=scores)


class AllocationService:
    """Deterministic, audited physical room assignment (SDD S11.6)."""

    @classmethod
    def allocate_line(
        cls, *, tenant_id: int, booking_line_id: int, idempotency_key: str, actor=None
    ) -> AllocationRecord:
        """Assign a physical room to ``booking_line_id`` — ONE atomic
        transaction (``IdempotencyService`` supplies the outer boundary,
        matching the M7-M9 discipline).

        Lock order (DDS D9, corrected R0.5): ``BookingLine`` first, then
        every property/type-matching candidate ``Room``, in ascending
        ``room_id`` order — NOT in guest-specific score order. Score order
        varies per guest (``stay_continuity`` depends on that guest's prior
        stays), so locking in score order let two concurrent allocations
        for different guests lock two contested rooms in opposite orders
        and deadlock (found in review). Locking every candidate up front in
        one fixed, guest-independent order makes that AB-BA pattern
        structurally impossible: every transaction contesting the same
        rooms walks the same sequence, so they can only ever queue behind
        each other, never form a cycle. The stay-continuity preference
        still decides which of the candidates found vacant is chosen —
        only the LOCK order changed, not the selection outcome.
        """
        request_payload = {"booking_line_id": booking_line_id}

        def _execute() -> dict:
            booking_line = BookingLine.objects.select_for_update().get(pk=booking_line_id)
            if booking_line.status != BookingStatus.CONFIRMED or booking_line.room_id is not None:
                raise BookingLineNotAllocatable(
                    f"BookingLine {booking_line_id} is not allocatable "
                    f"(status={booking_line.status!r}, room_id={booking_line.room_id!r})"
                )

            guest_profile_id = booking_line.booking.guest_profile_id
            # R0.2: scoped to the booking's own property — RoomType is
            # tenant-wide, not property-scoped, so without this a
            # multi-property tenant reusing a room-type code could have a
            # booking at Property A allocated a physical room at Property B.
            candidate_ids = list(
                RoomQuery.vacant_clean_candidates(
                    booking_line.room_type_id, property_id=booking_line.booking.property_id
                )
                .for_tenant(tenant_id)
                .values_list("id", flat=True)
            )
            criteria = AllocationCriteria(
                booking_line_id=booking_line.id,
                room_type_id=booking_line.room_type_id,
                guest_profile_id=guest_profile_id,
                candidate_room_ids=tuple(candidate_ids),
            )
            decision = _score_candidates(criteria)

            # Locked re-check (M11 ruling S3): the scored read above is
            # unlocked. Every candidate is locked here, in ascending
            # room_id order (R0.5) — not score order — and its
            # still-vacant state re-checked before it's eligible to win.
            vacant_by_id: dict[int, Room] = {}
            for candidate_id in sorted(candidate_ids):
                locked = Room.objects.select_for_update().get(pk=candidate_id)
                if locked.operational_state == Room.OperationalState.VACANT_CLEAN:
                    vacant_by_id[locked.id] = locked

            room = None
            for candidate_id in decision.ordered_room_ids():
                if candidate_id in vacant_by_id:
                    room = vacant_by_id[candidate_id]
                    break
            if room is None:
                raise NoEligibleRoom(
                    f"no eligible room for BookingLine {booking_line_id} "
                    f"(room_type={booking_line.room_type_id}); "
                    f"{len(candidate_ids)} candidate(s) considered, none available"
                )

            # Room's own FSM — never a direct operational_state write.
            room.current_booking_line_id = booking_line.id
            RoomStateMachine.apply(room, "allocate", actor=actor, reason="allocated at check-in")

            # Plain field mutation, not a WorkflowRunner transition (M11
            # ruling S1): the guards that matter here are the row lock, the
            # precondition check above, AllocationRecord's UniqueConstraint,
            # and Room's own FSM guard on the physical unit — a dedicated
            # BookingLine FSM would add ceremony without a second
            # transition to justify it yet. A future milestone may
            # introduce a formal BookingLine workflow if additional
            # meaningful line-level transitions (e.g. early departure,
            # room move) require one.
            booking_line.room = room
            booking_line.status = BookingStatus.CHECKED_IN
            booking_line.save(update_fields=["room", "status", "updated_at"])

            record = AllocationRecord.objects.create(
                tenant_id=tenant_id,
                property_id=booking_line.booking.property_id,
                booking_line=booking_line,
                room=room,
                chosen_by=actor,
                override=False,
                criteria=criteria.to_dict(),
                scores={str(s.room_id): s.to_dict() for s in decision.scores},
                reason=decision.reason_for(room.id),
            )

            OutboxService.record_event(
                event_type="room.allocated",
                tenant_id=tenant_id,
                aggregate_type="allocationrecord",
                aggregate_id=str(record.id),
                payload={
                    "booking_line_id": booking_line.id,
                    "room_id": room.id,
                    "reason": record.reason,
                },
            )
            return {"allocation_record_id": record.id}

        response = IdempotencyService(tenant_id=tenant_id, scope="allocation.allocate_line").run(
            idempotency_key, request_payload, execute=_execute
        )
        return AllocationRecord.objects.get(pk=response["allocation_record_id"])


class AllocationQuery:
    """Read-only selectors over ``allocation_record`` (mirrors ``BookingQuery``)."""

    @staticmethod
    def by_booking_line(booking_line) -> AllocationRecord | None:
        return AllocationRecord.objects.filter(booking_line=booking_line).first()

    @staticmethod
    def by_room(room):
        return AllocationRecord.objects.filter(room=room).order_by("-created_at")

    @staticmethod
    def for_property(property):
        return AllocationRecord.objects.filter(property=property).order_by("-created_at")
