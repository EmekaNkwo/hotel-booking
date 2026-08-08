"""Unit tests for the GeoLocation value object.

Test order follows the M1.1 convention:
happy path → validation failures → equality → immutability → business operations → edge cases.
"""

import pytest

from apps.shared.value_objects import GeoLocation, InvalidGeoLocation, ValueObjectError


class TestHappyPath:
    def test_constructs_from_latitude_and_longitude(self):
        g = GeoLocation(6.5244, 3.3792)

        assert g.latitude == 6.5244
        assert g.longitude == 3.3792

    def test_str_is_a_coordinate_pair(self):
        assert str(GeoLocation(6.5244, 3.3792)) == "(6.5244, 3.3792)"

    def test_boundary_latitudes_are_valid(self):
        assert GeoLocation(90.0, 0.0).latitude == 90.0
        assert GeoLocation(-90.0, 0.0).latitude == -90.0

    def test_boundary_longitudes_are_valid(self):
        assert GeoLocation(0.0, 180.0).longitude == 180.0
        assert GeoLocation(0.0, -180.0).longitude == -180.0


class TestValidationFailures:
    @pytest.mark.parametrize("bad", [90.1, -90.1, 91, -200])
    def test_rejects_latitude_out_of_range(self, bad):
        with pytest.raises(InvalidGeoLocation):
            GeoLocation(bad, 0.0)

    @pytest.mark.parametrize("bad", [180.1, -180.1, 181, -200])
    def test_rejects_longitude_out_of_range(self, bad):
        with pytest.raises(InvalidGeoLocation):
            GeoLocation(0.0, bad)

    @pytest.mark.parametrize("bad", ["6.5", None, True])
    def test_rejects_a_non_number_coordinate(self, bad):
        with pytest.raises(InvalidGeoLocation):
            GeoLocation(bad, 0.0)

    def test_failure_is_catchable_as_a_value_object_error(self):
        with pytest.raises(ValueObjectError):
            GeoLocation(95.0, 0.0)


class TestEquality:
    def test_equal_by_value(self):
        assert GeoLocation(6.5, 3.3) == GeoLocation(6.5, 3.3)

    def test_different_coordinates_are_not_equal(self):
        assert GeoLocation(6.5, 3.3) != GeoLocation(6.6, 3.3)

    def test_hashable(self):
        assert len({GeoLocation(6.5, 3.3), GeoLocation(6.5, 3.3)}) == 1


class TestImmutability:
    def test_assignment_raises(self):
        g = GeoLocation(6.5, 3.3)

        with pytest.raises(AttributeError):
            g.latitude = 7.0


class TestBusinessOperations:
    def test_integer_input_is_normalized_to_float(self):
        assert GeoLocation(6, 3).latitude == 6.0

    def test_int_and_float_inputs_are_equal(self):
        assert GeoLocation(6, 3) == GeoLocation(6.0, 3.0)


class TestEdgeCases:
    def test_error_message_names_the_field_and_bounds(self):
        with pytest.raises(InvalidGeoLocation, match="latitude"):
            GeoLocation(95.0, 0.0)
