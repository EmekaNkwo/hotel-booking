"""Exceptions for the Availability & Inventory Engines (M7, DDS S6+7)."""


class InsufficientAvailability(Exception):
    """Not enough remaining capacity to satisfy a consume/convert request.

    Raised by ``AvailabilitySlotRepository`` (R1, DR-05) whenever ANY night
    in a requested window cannot satisfy the demand — the whole window is
    checked, under lock, before a single row is written, so a caller never
    observes a partial multi-night consumption.
    """
