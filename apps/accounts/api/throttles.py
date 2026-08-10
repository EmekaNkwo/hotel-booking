"""Request throttling for the auth boundary (M2.4 step 5)."""

from django.conf import settings
from rest_framework.throttling import AnonRateThrottle


class AuthLoginThrottle(AnonRateThrottle):
    """Brute-force limiter for the session-login endpoint.

    ``AnonRateThrottle`` keys on the client IP — there is no auth context to
    key on at login — so a burst of password guesses is bounded at the app
    boundary. The rate is read from settings on every request (a property, not
    a class attribute) so tests can shrink it with ``override_settings``.
    """

    scope = "login"

    @property
    def rate(self) -> str:
        return settings.AUTH_LOGIN_THROTTLE_RATE
