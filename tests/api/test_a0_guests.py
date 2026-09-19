"""API tests for the Guests surface (A0).

Creation delegates to ``GuestService.resolve()`` (find-or-create, M5) — never
a raw ``GuestProfile.objects.create``, so a second create with the same email
must return the SAME guest, not a duplicate.
"""

import pytest

from tests.api.conftest import VIEWER_EMAIL, VIEWER_PASSWORD, grant_second_membership
from tests.api.helpers import login as _login


class TestGuestCreate:
    @pytest.mark.django_db
    def test_happy_path_creates_a_guest(self, api, a0_world):
        tenant = a0_world["tenant"]
        _login(api, VIEWER_EMAIL, VIEWER_PASSWORD)

        resp = api.post(
            "/api/guests/create/",
            {"email": "guest@example.com", "given_name": "Ada", "family_name": "Lovelace"},
            format="json",
            HTTP_X_TENANT_ID=str(tenant.pk),
        )

        assert resp.status_code == 201
        assert resp.data["primary_email"] == "guest@example.com"

    @pytest.mark.django_db
    def test_resolve_is_find_or_create_delegated_to_the_service(self, api, a0_world):
        tenant = a0_world["tenant"]
        _login(api, VIEWER_EMAIL, VIEWER_PASSWORD)

        first = api.post(
            "/api/guests/create/",
            {"email": "same@example.com"},
            format="json",
            HTTP_X_TENANT_ID=str(tenant.pk),
        )
        second = api.post(
            "/api/guests/create/",
            {"email": "same@example.com"},
            format="json",
            HTTP_X_TENANT_ID=str(tenant.pk),
        )

        assert first.data["id"] == second.data["id"]

    @pytest.mark.django_db
    def test_missing_email_and_phone_is_400(self, api, a0_world):
        _login(api, VIEWER_EMAIL, VIEWER_PASSWORD)
        resp = api.post(
            "/api/guests/create/", {}, format="json", HTTP_X_TENANT_ID=str(a0_world["tenant"].pk)
        )
        assert resp.status_code == 400

    @pytest.mark.django_db
    def test_unauthenticated_returns_403(self, api, a0_world):
        resp = api.post(
            "/api/guests/create/",
            {"email": "x@example.com"},
            format="json",
            HTTP_X_TENANT_ID=str(a0_world["tenant"].pk),
        )
        assert resp.status_code == 403


class TestGuestListAndDetail:
    @pytest.mark.django_db
    def test_search_by_email_substring(self, api, a0_world):
        tenant = a0_world["tenant"]
        _login(api, VIEWER_EMAIL, VIEWER_PASSWORD)
        api.post(
            "/api/guests/create/",
            {"email": "findme@example.com"},
            format="json",
            HTTP_X_TENANT_ID=str(tenant.pk),
        )

        resp = api.get("/api/guests/", {"q": "findme"}, HTTP_X_TENANT_ID=str(tenant.pk))

        assert resp.status_code == 200
        assert len(resp.data["results"]) == 1
        assert resp.data["results"][0]["primary_email"] == "findme@example.com"

    @pytest.mark.django_db
    def test_missing_tenant_context_returns_403(self, api, a0_world):
        grant_second_membership(a0_world["viewer"])
        _login(api, VIEWER_EMAIL, VIEWER_PASSWORD)
        assert api.get("/api/guests/").status_code == 403

    @pytest.mark.django_db
    def test_detail_unknown_guest_is_404(self, api, a0_world):
        _login(api, VIEWER_EMAIL, VIEWER_PASSWORD)
        resp = api.get("/api/guests/999999/", HTTP_X_TENANT_ID=str(a0_world["tenant"].pk))
        assert resp.status_code == 404

    @pytest.mark.django_db
    def test_cross_tenant_guest_is_invisible(self, api, a0_world):
        from apps.guests.services import GuestService
        from apps.tenants.models import Tenant
        from apps.tenants.services import TenantService

        TenantService.provision(
            code="beta", name="Beta", base_currency="NGN", owner_email="beta-owner@x.example"
        )
        beta = Tenant.objects.get(code="beta")
        beta_guest = GuestService.resolve(beta, email="beta-guest@example.com")

        _login(api, VIEWER_EMAIL, VIEWER_PASSWORD)
        resp = api.get(f"/api/guests/{beta_guest.pk}/", HTTP_X_TENANT_ID=str(a0_world["tenant"].pk))

        assert resp.status_code == 404
