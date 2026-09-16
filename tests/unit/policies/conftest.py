"""Policy test fixtures.

Reuses ``tenant`` and ``property`` from ``tests/unit/conftest.py`` (shared across
all unit-tier tests). Adds ``tenant2`` for tenant-isolation tests that need a
second, distinct tenant.
"""
import pytest

from apps.tenants.models import Tenant


@pytest.fixture
def tenant2():
    """A second tenant, distinct from ``tenant``, for isolation tests."""
    return Tenant.objects.create(code="globex", name="Globex Hotels", base_currency="NGN")