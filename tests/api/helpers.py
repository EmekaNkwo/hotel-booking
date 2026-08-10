"""Shared helpers for the M2.3 API tests."""


def login(client, email, password):
    """Establish a session via the real login endpoint."""
    return client.post(
        "/api/auth/login/",
        {"email": email, "password": password},
        format="json",
    )
