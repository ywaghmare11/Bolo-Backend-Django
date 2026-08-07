import pytest
from django.core.cache import cache


@pytest.fixture(autouse=True)
def _clear_cache():
    """ScopedRateThrottle (apps/auth/views.py:RequestOtpView) persists counters in the
    default cache, which -- unlike the DB -- isn't reset between tests by Django's test
    runner. Without this, tests that call POST /auth/request-otp/ more than a handful of
    times across a session would start tripping the 5/min throttle on unrelated tests."""
    cache.clear()
    yield
    cache.clear()
