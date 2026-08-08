"""GeoLocation — a latitude/longitude pair, as a value object.

The bug this prevents: bare ``(lat, lon)`` floats mean a latitude of ``95.0``
can reach a map, a sort, or a radius query without anyone noticing it is
impossible. ``GeoLocation`` refuses out-of-range coordinates at construction.

This value object carries only a few *universal* invariants — the bounds are
true for every coordinate on Earth. What the coordinates *mean* (datum,
projection, distance math, reverse geocoding) is business policy for the search
context (M15), not the kernel.
"""

from dataclasses import dataclass

from apps.shared.value_objects.exceptions import InvalidGeoLocation

_LAT_RANGE = (-90.0, 90.0)
_LON_RANGE = (-180.0, 180.0)


def _normalize_coordinate(name: str, value: object, lo: float, hi: float) -> float:
    if isinstance(value, bool) or not isinstance(value, int | float):
        raise InvalidGeoLocation(f"{name} must be a number, got {value!r}.")
    number = float(value)
    if not lo <= number <= hi:
        raise InvalidGeoLocation(f"{name} must be between {lo} and {hi}, got {value!r}.")
    return number


@dataclass(frozen=True, slots=True)
class GeoLocation:
    """A position on Earth. Latitude and longitude are always stored as floats."""

    latitude: float
    longitude: float

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "latitude", _normalize_coordinate("latitude", self.latitude, *_LAT_RANGE)
        )
        object.__setattr__(
            self,
            "longitude",
            _normalize_coordinate("longitude", self.longitude, *_LON_RANGE),
        )

    def __str__(self) -> str:
        return f"({self.latitude}, {self.longitude})"
