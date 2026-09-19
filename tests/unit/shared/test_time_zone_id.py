"""Unit tests for the TimeZoneId value object.

Test order follows the M1.1 convention:
happy path → validation failures → equality → immutability → business operations → edge cases.
"""

from datetime import datetime
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import pytest

from apps.shared.value_objects import InvalidTimeZone, TimeZoneId, ValueObjectError


def _case_insensitive_tzdata() -> bool:
    """True when the host resolves a differently-cased IANA key to the same
    tzdata entry — e.g. the default case-insensitive APFS volume on macOS.
    ``TimeZoneId`` delegates validation entirely to stdlib ``zoneinfo`` (by
    design, see its module docstring: the registry is the authoritative
    source), so on such a host ``ZoneInfo("africa/lagos")`` resolves
    successfully via a case-insensitive filesystem lookup instead of
    raising — a real difference in what the *host* considers a valid path,
    not a defect in this value object. Probed directly (not via
    ``platform.system()``) so the skip only ever fires when the actual
    condition it names is true, on any OS/filesystem combination."""
    try:
        ZoneInfo("africa/lagos")
    except (ZoneInfoNotFoundError, ValueError):
        return False
    return True


class TestHappyPath:
    def test_constructs_from_an_iana_identifier(self):
        tz = TimeZoneId("Africa/Lagos")

        assert tz.name == "Africa/Lagos"

    def test_accepts_utc(self):
        assert TimeZoneId("UTC").name == "UTC"

    def test_strips_trailing_whitespace(self):
        # zoneinfo tolerates trailing whitespace on some platforms; we strip so
        # the stored identifier is canonical everywhere.
        assert TimeZoneId("Africa/Lagos ").name == "Africa/Lagos"

    def test_str_returns_the_identifier(self):
        assert str(TimeZoneId("Africa/Lagos")) == "Africa/Lagos"


class TestValidationFailures:
    @pytest.mark.parametrize(
        "bad",
        [
            "",                     # empty
            "Bogus/Zone",           # not in the registry
            pytest.param(
                "africa/lagos",     # wrong case — identifiers are case-sensitive
                marks=pytest.mark.skipif(
                    _case_insensitive_tzdata(),
                    reason=(
                        "host resolves IANA keys case-insensitively (e.g. the "
                        "default case-insensitive APFS volume on macOS) — "
                        "TimeZoneId correctly delegates to stdlib zoneinfo, "
                        "whose case-sensitivity itself is filesystem-dependent "
                        "here, not a defect in this value object"
                    ),
                ),
            ),
            "Africa/Lagos/Extra",   # too deep
            "Africa/ Lagos",        # space inside a component survives stripping
            "..",
        ],
    )
    def test_rejects_an_unknown_or_malformed_identifier(self, bad):
        with pytest.raises(InvalidTimeZone):
            TimeZoneId(bad)

    @pytest.mark.parametrize("bad", [1, None, ["Africa/Lagos"]])
    def test_rejects_a_non_string(self, bad):
        with pytest.raises(InvalidTimeZone):
            TimeZoneId(bad)

    def test_failure_is_catchable_as_a_value_object_error(self):
        with pytest.raises(ValueObjectError):
            TimeZoneId("Bogus/Zone")


class TestEquality:
    def test_equal_by_value(self):
        assert TimeZoneId("Africa/Lagos") == TimeZoneId("Africa/Lagos")

    def test_different_zones_are_not_equal(self):
        assert TimeZoneId("Africa/Lagos") != TimeZoneId("Europe/Paris")

    def test_hashable(self):
        assert len({TimeZoneId("Africa/Lagos"), TimeZoneId("Africa/Lagos")}) == 1


class TestImmutability:
    def test_assignment_raises(self):
        tz = TimeZoneId("Africa/Lagos")

        with pytest.raises(AttributeError):
            tz.name = "Europe/Paris"


class TestBusinessOperations:
    def test_to_zoneinfo_resolves_the_engine(self):
        assert TimeZoneId("Africa/Lagos").to_zoneinfo() == ZoneInfo("Africa/Lagos")

    def test_lagos_and_paris_are_different_zones_with_the_same_january_offset(self):
        # The "a timezone is not an offset" proof: same offset in January,
        # different zones, different offsets in July.
        lagos = TimeZoneId("Africa/Lagos").to_zoneinfo()
        paris = TimeZoneId("Europe/Paris").to_zoneinfo()

        assert lagos != paris
        assert lagos.utcoffset(datetime(2026, 1, 15)) == paris.utcoffset(datetime(2026, 1, 15))
        assert lagos.utcoffset(datetime(2026, 7, 15)) != paris.utcoffset(datetime(2026, 7, 15))


class TestEdgeCases:
    def test_error_message_names_the_offending_value(self):
        with pytest.raises(InvalidTimeZone, match="Bogus/Zone"):
            TimeZoneId("Bogus/Zone")
