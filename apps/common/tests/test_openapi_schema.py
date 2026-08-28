"""Phase 13 -- the OpenAPI schema must always generate and be a valid OpenAPI 3
document, and the three doc endpoints must serve without auth. This is a
regression guard: a future view change that makes drf-spectacular throw (not just
warn) would fail here instead of silently breaking `/api/v1/docs/`.
"""
import io

import pytest
from django.core.management import call_command
from rest_framework.test import APIClient


def test_spectacular_schema_generates_and_validates():
    """`manage.py spectacular --validate` exits non-zero only on a hard failure
    or an invalid-schema error -- the per-view "unable to guess serializer"
    messages for our plain APIViews are non-fatal and don't fail this."""
    out, err = io.StringIO(), io.StringIO()
    # raises CommandError on validation failure / non-zero exit
    call_command("spectacular", "--validate", "--format", "openapi-json", stdout=out, stderr=err)
    assert out.getvalue().strip().startswith("{")
    assert '"openapi": "3' in out.getvalue()


@pytest.mark.django_db
class TestDocsEndpoints:
    def test_schema_endpoint_is_public(self):
        resp = APIClient().get("/api/v1/schema/")
        assert resp.status_code == 200
        assert "openapi" in resp.headers["Content-Type"] or resp.headers[
            "Content-Type"
        ].startswith("application/vnd.oai.openapi")

    def test_swagger_ui_renders(self):
        resp = APIClient().get("/api/v1/docs/")
        assert resp.status_code == 200
        assert b"swagger-ui" in resp.content

    def test_redoc_renders(self):
        resp = APIClient().get("/api/v1/redoc/")
        assert resp.status_code == 200
        assert b"redoc" in resp.content.lower()

    def test_cookie_auth_scheme_is_documented(self):
        resp = APIClient().get("/api/v1/schema/", {"format": "json"})
        assert resp.status_code == 200
        schemes = resp.json()["components"]["securitySchemes"]
        assert schemes["cookieAuth"] == {
            "type": "apiKey",
            "in": "cookie",
            "name": "token",
            "description": schemes["cookieAuth"]["description"],
        }
