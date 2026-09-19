"""Exceptions for the Allocation Engine (M11, DDS S12, DR-11)."""


class NoEligibleRoom(Exception):
    """No candidate room survived scoring + the pessimistic re-check.

    Raised when every ``VACANT_CLEAN`` room of the required type either
    never existed or lost the race to another allocator between the
    unlocked scoring read and the locked re-check (SDD S11.6, DMS S12
    invariant #1).
    """


class BookingLineNotAllocatable(Exception):
    """The requested ``BookingLine`` is not eligible for allocation right now.

    Raised when the line is not ``confirmed`` or already has a room
    assigned — the Python-level precondition check under the line's own
    lock (the DB backstop is ``AllocationRecord.UniqueConstraint(booking_line)``).
    """
