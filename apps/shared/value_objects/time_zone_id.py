"""TimeZoneId — an IANA timezone identifier, as a value object.

The bug this prevents: storing a timezone as ``UTC+1``. Lagos and Paris are both
``UTC+1`` in January, but Lagos has no daylight saving while Paris becomes
``UTC+2`` in summer — and a fixed offset goes stale the moment a government
changes its rules. A *timezone is not an offset*: an offset is a snapshot of
now, an identifier is the rule from which the correct offset can be derived for
any moment. ``TimeZoneId`` stores the rule.

Validation delegates to Python's stdlib ``zoneinfo`` (the IANA tz database)
rather than maintaining a local list — the registry is the authoritative source,
and construction is the check.
"""

from dataclasses import dataclass
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from apps.shared.value_objects.exceptions import InvalidTimeZone


@dataclass(frozen=True, slots=True)
class TimeZoneId:
    """A valid IANA timezone identifier, e.g. ``"Africa/Lagos"``."""
    name: str

    def __post_init__(self) -> None:
        if not isinstance(self.name, str):
            raise InvalidTimeZone(f"TimeZoneId must be a string, got {self.name!r}.")
        name = self.name.strip()
        try:
            ZoneInfo(name)
        except (ZoneInfoNotFoundError, ValueError) as exc:
            # ValueError also covers malformed keys (e.g. "" or "..") that the
            # registry rejects before lookup.
            raise InvalidTimeZone(f"Unknown timezone identifier: {name!r}.") from exc
        # zoneinfo tolerates trailing whitespace on some platforms but not
        # others; strip so the stored identifier is canonical everywhere.
        object.__setattr__(self, "name", name)

    def __str__(self) -> str:
        return self.name

    def to_zoneinfo(self) -> ZoneInfo:
        """The zoneinfo engine behind this identifier (for offset/DST math)."""
        return ZoneInfo(self.name)
