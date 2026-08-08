"""Unit tests for typed ids.

Test order follows the M1.1 convention:
happy path → validation failures → equality → immutability → business operations → edge cases.
"""

import pytest

from apps.shared.value_objects import (
    EntityId,
    GuestId,
    InvalidId,
    PropertyId,
    RoomTypeId,
    TenantId,
    UserId,
    ValueObjectError,
)


class TestHappyPath:
    def test_constructs_from_an_int(self):
        assert TenantId(5) == 5

    def test_is_a_drop_in_for_an_int(self):
        assert int(TenantId(5)) == 5
        assert str(TenantId(5)) == "5"

    def test_accepts_zero(self):
        assert TenantId(0) == 0

    def test_constructs_all_planned_ids(self):
        assert UserId(1) == 1
        assert PropertyId(2) == 2
        assert RoomTypeId(3) == 3
        assert GuestId(4) == 4


class TestValidationFailures:
    @pytest.mark.parametrize("bad", [-1, -100])
    def test_rejects_negative_values(self, bad):
        with pytest.raises(InvalidId):
            TenantId(bad)

    @pytest.mark.parametrize("bad", [1.5, "5", None, [5]])
    def test_rejects_a_non_int(self, bad):
        with pytest.raises(InvalidId):
            TenantId(bad)

    def test_rejects_a_bool(self):
        # True is an int subclass; True must not silently mean id 1.
        with pytest.raises(InvalidId):
            TenantId(True)

    def test_failure_is_catchable_as_a_value_object_error(self):
        with pytest.raises(ValueObjectError):
            TenantId(-1)


class TestEquality:
    def test_equal_by_value(self):
        assert TenantId(5) == TenantId(5)

    def test_different_values_are_not_equal(self):
        assert TenantId(5) != TenantId(6)

    def test_hashable(self):
        assert len({TenantId(5), TenantId(5)}) == 1


class TestImmutability:
    def test_ints_are_immutable_by_nature(self):
        tenant = TenantId(5)

        # There is no attribute to assign on an int.
        assert not hasattr(tenant, "value")


class TestBusinessOperations:
    def test_usable_as_a_dict_key(self):
        mapping = {TenantId(5): "Acme Hotels"}

        assert mapping[TenantId(5)] == "Acme Hotels"

    def test_type_is_preserved(self):
        assert type(TenantId(5)) is TenantId
        assert isinstance(TenantId(5), EntityId)

    def test_distinct_types_are_distinct_classes(self):
        # The type-safety payoff: TenantId and PropertyId are different types,
        # so a type checker catches a swapped-argument mistake at compile time.
        assert TenantId is not PropertyId


class TestEdgeCases:
    def test_error_message_names_the_type(self):
        with pytest.raises(InvalidId, match="TenantId"):
            TenantId(-1)
