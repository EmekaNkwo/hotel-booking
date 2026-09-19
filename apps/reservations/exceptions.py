"""Exceptions for the Reservation Engine (M8, SDD S11.4, DDS S9)."""


class ReservationLineInvalid(Exception):
    """A reservation line's input failed structural validation before any
    service (Pricing/Policy/Inventory) was ever called."""
