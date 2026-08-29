"""Phase 15c -- multi-format member bulk-import ETL pipeline.

Split in two: pure-function tests on apps/platform_admin/etl.py (no DB), and
end-to-end API tests through POST /platform-admin/tenants/:id/members/import
(real DB, real .xlsx/.csv/.json payloads).
"""
import io
import json

import pandas as pd
import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from rest_framework.test import APIClient

from apps.audit.models import AuditLog
from apps.common.enums import AuditActorType, OrgRoleLevel
from apps.common.exceptions import ValidationError
from apps.platform_admin import etl
from apps.platform_admin.models import PlatformAdmin
from apps.platform_admin.tokens import issue_admin_access_token
from apps.tenants.factories import TenantFactory
from apps.tenants.models import TenantMembership
from apps.users.factories import UserFactory
from apps.users.models import User


# --------------------------------------------------------------------- ETL unit

class TestExtract:
    def test_csv_utf8_sig_strips_bom(self):
        raw = "﻿name,email,role\nAsha,asha@x.com,MID\n".encode("utf-8-sig")
        df = etl.extract(raw, "m.csv")
        assert list(df.columns) == ["name", "email", "role"]

    def test_csv_latin1_fallback(self):
        raw = "name,email,role\nRen\xe9,rene@x.com,MID\n".encode("latin-1")
        valid, _ = etl.transform(etl.extract(raw, "m.csv"))
        assert valid[0]["name"] == "Ren\xe9"

    def test_xlsx_first_sheet(self):
        buf = io.BytesIO()
        pd.DataFrame([{"Name": "Zoe", "Email": "zoe@x.com", "Role": "mid"}]).to_excel(
            buf, index=False, engine="openpyxl",
        )
        valid, _ = etl.transform(etl.extract(buf.getvalue(), "m.xlsx"))
        assert valid[0]["email"] == "zoe@x.com"

    def test_json_array(self):
        raw = json.dumps([{"name": "Al", "email": "al@x.com", "role": "EXECUTOR"}]).encode()
        valid, _ = etl.transform(etl.extract(raw, "m.json"))
        assert valid[0]["role_level"] == "EXECUTOR"

    def test_json_wrapped_in_members_key(self):
        raw = json.dumps({"members": [{"name": "Bo", "email": "bo@x.com", "role": "TOP"}]}).encode()
        valid, _ = etl.transform(etl.extract(raw, "m.json"))
        assert valid[0]["name"] == "Bo"

    def test_unsupported_extension_raises_invalid_file(self):
        with pytest.raises(ValidationError) as exc:
            etl.extract(b"whatever", "m.txt")
        assert exc.value.code == "INVALID_FILE"

    def test_unparseable_bytes_raise_invalid_file(self):
        with pytest.raises(ValidationError) as exc:
            etl.extract(b"\x00\x01\x02 not a spreadsheet", "m.xlsx")
        assert exc.value.code == "INVALID_FILE"


class TestTransform:
    def _df(self, rows):
        return pd.DataFrame(rows, dtype=str).fillna("")

    def test_header_aliases_normalised(self):
        df = self._df([{"Full Name": "A", "E-Mail": "a@x.com", "Role Level": "MID", "Designation": "HoD"}])
        valid, errors = etl.transform(df)
        assert errors == []
        assert valid[0]["name"] == "A"
        assert valid[0]["role_label"] == "HoD"

    def test_boolean_coercion(self):
        df = self._df([
            {"name": "A", "email": "a@x.com", "role": "MID", "can broadcast": "yes"},
            {"name": "B", "email": "b@x.com", "role": "MID", "can broadcast": "0"},
            {"name": "C", "email": "c@x.com", "role": "MID", "can broadcast": "TRUE"},
        ])
        valid, _ = etl.transform(df)
        assert [v["can_broadcast"] for v in valid] == [True, False, True]

    def test_formula_injection_neutralised(self):
        df = self._df([
            {"name": "=SUM(A1:A2)", "email": "a@x.com", "role": "MID"},
            {"name": "@Reboot", "email": "b@x.com", "role": "TOP"},
        ])
        valid, _ = etl.transform(df)
        assert [v["name"] for v in valid] == ["'=SUM(A1:A2)", "'@Reboot"]

    def test_bad_role_rejected_per_row(self):
        df = self._df([
            {"name": "A", "email": "a@x.com", "role": "MID"},
            {"name": "B", "email": "b@x.com", "role": "Boss"},
        ])
        valid, errors = etl.transform(df)
        assert len(valid) == 1
        assert errors == [{"row": 3, "field": "roleLevel",
                           "reason": "must be one of EXECUTOR, MID, TOP"}]

    def test_bad_email_rejected_per_row(self):
        df = self._df([{"name": "A", "email": "not-an-email", "role": "MID"}])
        valid, errors = etl.transform(df)
        assert valid == []
        assert errors[0]["field"] == "email"

    def test_missing_name_rejected(self):
        df = self._df([{"name": "", "email": "a@x.com", "role": "MID"}])
        _, errors = etl.transform(df)
        assert errors[0]["field"] == "name"

    def test_within_file_dedup_keeps_last(self):
        df = self._df([
            {"name": "Asha v1", "email": "asha@x.com", "role": "MID"},
            {"name": "Asha v2", "email": "ASHA@x.com", "role": "TOP"},
        ])
        valid, errors = etl.transform(df)
        assert [v["name"] for v in valid] == ["Asha v2"]
        assert errors == [{"row": 2, "field": "email",
                           "reason": "duplicate email within the file (a later row was used instead)"}]

    def test_missing_required_column_raises_invalid_file(self):
        df = self._df([{"name": "A", "email": "a@x.com"}])  # no role
        with pytest.raises(ValidationError) as exc:
            etl.transform(df)
        assert exc.value.code == "INVALID_FILE"

    def test_empty_file_raises_invalid_file(self):
        with pytest.raises(ValidationError):
            etl.transform(self._df([]).reindex(columns=["name", "email", "role_level"]))

    def test_over_row_cap_raises_invalid_file(self, monkeypatch):
        monkeypatch.setattr(etl, "MAX_ROWS", 2)
        df = self._df([{"name": f"U{i}", "email": f"u{i}@x.com", "role": "MID"} for i in range(3)])
        with pytest.raises(ValidationError):
            etl.transform(df)

    def test_unknown_language_defaults_to_en(self):
        df = self._df([{"name": "A", "email": "a@x.com", "role": "MID", "language": "FR"}])
        valid, _ = etl.transform(df)
        assert valid[0]["preferred_lang"] == "EN"


# --------------------------------------------------------------- API integration

@pytest.fixture
def admin():
    return PlatformAdmin.objects.create(name="Ops Admin", email="admin@bolo.internal")


@pytest.fixture
def client(admin):
    c = APIClient()
    c.cookies["admin_token"] = issue_admin_access_token(admin.id, admin.email, admin.role)
    return c


def _upload(client, tenant_id, content: bytes, filename: str):
    upload = SimpleUploadedFile(filename, content, content_type="application/octet-stream")
    return client.post(
        f"/api/v1/platform-admin/tenants/{tenant_id}/members/import/",
        {"file": upload},
        format="multipart",
    )


def _csv(rows_text: str) -> bytes:
    return ("name,email,role,can_broadcast\n" + rows_text).encode()


@pytest.mark.django_db
class TestImportApi:
    def test_csv_creates_members_and_memberships(self, client):
        tenant = TenantFactory()
        body = _csv("Asha,asha@abc.edu,MID,yes\nRaj,raj@abc.edu,executor,no\n")
        resp = _upload(client, tenant.id, body, "members.csv")

        assert resp.status_code == 200
        assert resp.data["data"] == {"created": 2, "updated": 0, "skipped": 0, "errors": []}
        asha = User.objects.get(email="asha@abc.edu")
        assert asha.tenant_id == tenant.id
        m = TenantMembership.objects.get(tenant=tenant, user=asha)
        assert m.role_level == OrgRoleLevel.MID
        assert m.can_broadcast is True

    def test_import_is_idempotent(self, client):
        tenant = TenantFactory()
        body = _csv("Asha,asha@abc.edu,MID,no\n")
        _upload(client, tenant.id, body, "m.csv")
        resp = _upload(client, tenant.id, _csv("Asha Updated,asha@abc.edu,TOP,yes\n"), "m.csv")

        assert resp.data["data"] == {"created": 0, "updated": 1, "skipped": 0, "errors": []}
        assert User.objects.filter(email="asha@abc.edu").count() == 1
        m = TenantMembership.objects.get(tenant=tenant, user__email="asha@abc.edu")
        assert m.role_level == OrgRoleLevel.TOP
        assert m.can_broadcast is True

    def test_xlsx_end_to_end(self, client):
        tenant = TenantFactory()
        buf = io.BytesIO()
        pd.DataFrame(
            [{"Name": "Zoe", "E-mail": "zoe@abc.edu", "Role": "mid"}],
        ).to_excel(buf, index=False, engine="openpyxl")
        resp = _upload(client, tenant.id, buf.getvalue(), "members.xlsx")

        assert resp.status_code == 200
        assert resp.data["data"]["created"] == 1
        assert User.objects.filter(email="zoe@abc.edu", tenant=tenant).exists()

    def test_json_end_to_end(self, client):
        tenant = TenantFactory()
        body = json.dumps([{"name": "Al", "email": "al@abc.edu", "role": "EXECUTOR"}]).encode()
        resp = _upload(client, tenant.id, body, "members.json")
        assert resp.data["data"]["created"] == 1

    def test_partial_failure_reports_errors(self, client):
        tenant = TenantFactory()
        body = _csv("Good,good@abc.edu,MID,no\nBad,bad@abc.edu,Boss,no\n,noname@abc.edu,MID,no\n")
        resp = _upload(client, tenant.id, body, "m.csv")

        data = resp.data["data"]
        assert data["created"] == 1
        assert data["skipped"] == 2
        assert {e["field"] for e in data["errors"]} == {"roleLevel", "name"}

    def test_email_belonging_to_another_tenant_is_skipped(self, client):
        other = TenantFactory()
        UserFactory(tenant=other, email="taken@abc.edu")
        tenant = TenantFactory()
        resp = _upload(client, tenant.id, _csv("X,taken@abc.edu,MID,no\n"), "m.csv")

        data = resp.data["data"]
        assert data["created"] == 0
        assert data["skipped"] == 1
        assert data["errors"][0]["reason"] == "this email already belongs to a different tenant"

    def test_no_file_is_400(self, client):
        tenant = TenantFactory()
        resp = client.post(
            f"/api/v1/platform-admin/tenants/{tenant.id}/members/import/", {}, format="multipart",
        )
        assert resp.status_code == 400
        assert resp.data["error"]["code"] == "INVALID_FILE"

    def test_bad_extension_is_400(self, client):
        tenant = TenantFactory()
        resp = _upload(client, tenant.id, b"nope", "members.txt")
        assert resp.status_code == 400
        assert resp.data["error"]["code"] == "INVALID_FILE"

    def test_unknown_tenant_is_404(self, client):
        resp = _upload(
            client, "00000000-0000-0000-0000-000000000000", _csv("A,a@x.com,MID,no\n"), "m.csv",
        )
        assert resp.status_code == 404

    def test_unauthenticated_is_401(self):
        tenant = TenantFactory()
        resp = _upload(APIClient(), tenant.id, _csv("A,a@x.com,MID,no\n"), "m.csv")
        assert resp.status_code == 401

    def test_writes_bulk_imported_audit_row_with_counts(self, client, admin):
        tenant = TenantFactory()
        body = _csv("Good,good@abc.edu,MID,no\nBad,bad@abc.edu,Boss,no\n")
        _upload(client, tenant.id, body, "m.csv")

        log = AuditLog.objects.get(action="MEMBERS_BULK_IMPORTED", entity_id=str(tenant.id))
        assert log.entity_type == "TENANT"
        assert log.actor_id is None
        assert log.actor_type == AuditActorType.PLATFORM_ADMIN
        assert str(log.tenant_id) == str(tenant.id)
        assert log.metadata == {
            "platformAdminId": str(admin.id),
            "platformAdminEmail": admin.email,
            "created": 1,
            "updated": 0,
            "skipped": 1,
        }

    def test_failed_import_writes_no_audit_row(self, client):
        tenant = TenantFactory()
        _upload(client, tenant.id, b"nope", "members.txt")  # 400
        assert not AuditLog.objects.filter(action="MEMBERS_BULK_IMPORTED").exists()
